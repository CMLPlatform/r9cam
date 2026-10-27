"""Start the API server, over HTTPS when TLS_CERT_FILE and TLS_KEY_FILE are set.

``fastapi run`` cannot pass certificate options to uvicorn, so the image starts here.
"""

import uvicorn

from app.core.settings import settings


def main() -> None:
    """Run uvicorn with the options the image used to pass to ``fastapi run``."""
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",  # noqa: S104 # the API serves the LAN; INSTALL.md keeps port 8018 on a trusted network
        port=8018,
        proxy_headers=True,
        # Trust X-Forwarded-* only from a reverse proxy on the Pi itself.
        forwarded_allow_ips="127.0.0.1,::1",
        ssl_certfile=settings.tls_cert_file or None,
        ssl_keyfile=settings.tls_key_file or None,
    )


if __name__ == "__main__":
    main()
