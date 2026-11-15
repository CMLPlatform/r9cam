"""Tests for the gettext catalogue: language negotiation, translated pages and API errors."""

import gettext
import json
import re
from pathlib import Path

import pytest
from babel.messages.extract import DEFAULT_KEYWORDS, extract_from_dir
from babel.messages.frontend import parse_mapping_cfg
from babel.messages.pofile import read_po
from httpx import AsyncClient

from app.core.i18n import negotiate_language

APP_DIR = Path(__file__).resolve().parents[2] / "app"
LOCALE_DIR = APP_DIR / "locale"
NL_PO = LOCALE_DIR / "nl" / "LC_MESSAGES" / "messages.po"
STRINGS_BLOCK_RE = re.compile(
    r'<script type="application/json" id="i18n-strings" nonce="([^"]+)">(.*?)</script>', re.DOTALL
)
NL = {"Accept-Language": "nl"}
FR = {"Accept-Language": "fr-FR, de;q=0.8"}
LOGIN_FORM = {"api_key": "wrong", "redirect_url": "/"}


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (None, "en"),
        ("", "en"),
        ("nl", "nl"),
        ("nl-NL,nl;q=0.9,en;q=0.8", "nl"),
        ("en-GB,en;q=0.9,nl;q=0.8", "en"),
        ("de, nl;q=0.5", "nl"),
        ("fr-FR, de;q=0.8", "en"),
        ("nl;q=0", "en"),
        ("*", "en"),
        ("nl;q=bogus", "en"),
    ],
)
def test_negotiate_language(header: str | None, expected: str) -> None:
    """The highest-ranked supported language wins, and English is the fallback."""
    assert negotiate_language(header) == expected


@pytest.mark.parametrize("path", ["/", "/setup"])
class TestTranslatedPages:
    """Both HTML pages follow Accept-Language."""

    async def test_dutch_request_gets_dutch_html(self, unauthed_client: AsyncClient, path: str) -> None:
        """Accept-Language nl gives Dutch text and lang=nl."""
        resp = await unauthed_client.get(path, headers=NL)
        assert '<html lang="nl">' in resp.text
        assert "Accept-Language" in resp.headers["vary"]
        assert "Startpagina" in resp.text
        assert ">Home</a>" not in resp.text

    @pytest.mark.parametrize("headers", [{}, {"Accept-Language": "en"}, FR])
    async def test_english_and_unknown_get_english_html(
        self, unauthed_client: AsyncClient, path: str, headers: dict[str, str]
    ) -> None:
        """English and unsupported languages give English text."""
        resp = await unauthed_client.get(path, headers=headers)
        assert '<html lang="en">' in resp.text
        assert "Accept-Language" in resp.headers["vary"]
        assert ">Home</a>" in resp.text

    @pytest.mark.parametrize(("headers", "theme_auto"), [({}, "Theme: Auto"), (NL, "Thema: automatisch")])
    async def test_strings_block_is_valid_json_with_the_page_nonce(
        self, unauthed_client: AsyncClient, path: str, headers: dict[str, str], theme_auto: str
    ) -> None:
        """The JS strings block is JSON in the page language, under the CSP nonce."""
        resp = await unauthed_client.get(path, headers=headers)
        match = STRINGS_BLOCK_RE.search(resp.text)
        assert match, "no i18n-strings block"
        assert f"'nonce-{match.group(1)}'" in resp.headers["content-security-policy"]
        strings = json.loads(match.group(2))
        assert strings["site"]["theme"]["auto"] == theme_auto
        assert strings["page"]


async def test_api_error_is_translated(unauthed_client: AsyncClient) -> None:
    """An HTTPException detail follows Accept-Language."""
    resp = await unauthed_client.post("/auth/login", data=LOGIN_FORM, headers=NL)
    assert resp.status_code == 403
    assert resp.json() == {"detail": "Ongeldige API-sleutel"}
    assert "Accept-Language" in resp.headers["vary"]


async def test_api_error_stays_english_by_default(unauthed_client: AsyncClient) -> None:
    """Without Accept-Language the detail stays English."""
    resp = await unauthed_client.post("/auth/login", data=LOGIN_FORM)
    assert resp.json() == {"detail": "Invalid API Key"}


class TestCatalogue:
    """Keep the committed catalogue in step with the code and fully translated."""

    def test_pot_is_current(self) -> None:
        """The template holds exactly the strings extraction finds in the code."""
        with (APP_DIR.parent / "babel.cfg").open() as handle:
            method_map, options_map = parse_mapping_cfg(handle)
        extracted = {
            message
            for _file, _line, message, _comments, _context in extract_from_dir(
                APP_DIR,
                method_map=method_map,
                options_map=options_map,
                keywords={**DEFAULT_KEYWORDS, "N_": None},
            )
            if message
        }
        with (LOCALE_DIR / "messages.pot").open("rb") as handle:
            pot = {m.id for m in read_po(handle) if m.id}
        assert extracted == pot, "messages.pot is stale: run `just i18n-update`"

    def test_dutch_catalogue_is_complete(self) -> None:
        """No Dutch message is empty or fuzzy, and none is missing."""
        with LOCALE_DIR.joinpath("messages.pot").open("rb") as handle:
            pot = {m.id for m in read_po(handle) if m.id}
        with NL_PO.open("rb") as handle:
            nl = read_po(handle, locale="nl")
        assert {m.id for m in nl if m.id} == pot, "messages.po is out of date: run `just i18n-update`"
        problems = [m.id for m in nl if m.id and (not m.string or m.fuzzy)]
        assert not problems, f"untranslated or fuzzy Dutch messages: {problems}"

    def test_compiled_catalogue_matches_po(self) -> None:
        """The committed .mo holds what the .po says."""
        with NL_PO.open("rb") as handle:
            nl = read_po(handle, locale="nl")
        compiled = gettext.translation("messages", LOCALE_DIR, ["nl"])
        stale = [m.id for m in nl if m.id and compiled.gettext(str(m.id)) != m.string]
        assert not stale, f"messages.mo is stale: run `just i18n-compile`: {stale}"
