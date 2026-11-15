"""Tests for local direct-connection helpers."""

from __future__ import annotations

import socket
from types import SimpleNamespace
from typing import TYPE_CHECKING

from pydantic import HttpUrl

from app.core.settings import settings
from app.pairing.routers.local_access import get_candidate_urls

if TYPE_CHECKING:
    import pytest

LAN_IP = "192.168.1.50"


class TestGetCandidateUrls:
    """Tests for get_candidate_urls."""

    def test_prefers_physical_interfaces_over_docker_bridges(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A Docker bridge should not outrank a real LAN interface."""
        monkeypatch.setattr(
            "app.utils.network.psutil.net_if_addrs",
            lambda: {
                "docker0": [SimpleNamespace(family=socket.AF_INET, address="172.17.0.1")],
                "eth0": [SimpleNamespace(family=socket.AF_INET, address="192.168.1.50")],
                "lo": [SimpleNamespace(family=socket.AF_INET, address="127.0.0.1")],
            },
        )

        urls = get_candidate_urls()

        assert urls == ["http://192.168.1.50:8018"]

    def test_uses_https_and_the_configured_port_when_tls_is_on(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """With a certificate set the local API speaks HTTPS, on the port from base_url."""
        monkeypatch.setattr("app.pairing.routers.local_access.find_lan_ips", lambda: [LAN_IP])
        monkeypatch.setattr(settings, "tls_cert_file", "/certs/cert.pem")
        monkeypatch.setattr(settings, "tls_key_file", "/certs/key.pem")
        monkeypatch.setattr(settings, "base_url", HttpUrl("https://camera.example:8443/"))

        assert get_candidate_urls() == [f"https://{LAN_IP}:8443"]

    def test_keeps_the_default_port_when_base_url_scheme_differs(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A proxy-facing https base_url without local TLS must not leak its port 443 into LAN URLs."""
        monkeypatch.setattr("app.pairing.routers.local_access.find_lan_ips", lambda: [LAN_IP])
        monkeypatch.setattr(settings, "base_url", HttpUrl("https://camera.example/"))

        assert get_candidate_urls() == [f"http://{LAN_IP}:8018"]

    def test_tls_without_an_explicit_base_url_port_uses_the_api_port(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Pydantic fills 443 for a port-less https base_url; the device still listens on API_PORT."""
        monkeypatch.setattr("app.pairing.routers.local_access.find_lan_ips", lambda: [LAN_IP])
        monkeypatch.setattr(settings, "tls_cert_file", "/certs/cert.pem")
        monkeypatch.setattr(settings, "tls_key_file", "/certs/key.pem")
        monkeypatch.setattr(settings, "base_url", HttpUrl("https://camera.example/"))

        assert get_candidate_urls() == [f"https://{LAN_IP}:8018"]

    def test_uses_the_base_url_port_without_tls(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A custom plain-HTTP port in base_url shows up in the candidate URLs."""
        monkeypatch.setattr("app.pairing.routers.local_access.find_lan_ips", lambda: [LAN_IP])
        monkeypatch.setattr(settings, "base_url", HttpUrl("http://127.0.0.1:9000/"))

        assert get_candidate_urls() == [f"http://{LAN_IP}:9000"]
