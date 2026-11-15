"""Gettext catalogue: per-request language, translated templates and API error texts."""

from __future__ import annotations

import gettext
from functools import lru_cache
from typing import TYPE_CHECKING, Any, cast

from fastapi.exception_handlers import http_exception_handler as default_http_exception_handler
from fastapi.templating import Jinja2Templates
from jinja2 import Environment, FileSystemLoader
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.settings import settings

if TYPE_CHECKING:
    from starlette.requests import Request
    from starlette.responses import Response
    from starlette.templating import _TemplateResponse

SUPPORTED_LANGUAGES = ("en", "nl")
DEFAULT_LANGUAGE = "en"
_DOMAIN = "messages"
_Q_PARAM = "q"
_VARY_TOKEN = "Accept-Language"  # noqa: S105 - a header name, not a password


def N_(message: str) -> str:  # noqa: N802 - the gettext keyword that marks a string for extraction
    """Mark a string for the catalogue and return it unchanged; `translate` looks it up per request."""
    return message


def negotiate_language(accept_language: str | None) -> str:
    """Return the supported language the Accept-Language header ranks highest, else English."""
    best, best_q = DEFAULT_LANGUAGE, 0.0
    for part in (accept_language or "").split(","):
        tag, *params = part.split(";")
        language = tag.strip().lower().split("-")[0]
        if language not in SUPPORTED_LANGUAGES:
            continue
        q = 1.0
        for param in params:
            name, _, value = param.partition("=")
            if name.strip().lower() == _Q_PARAM:
                try:
                    q = float(value.strip())
                except ValueError:
                    q = -1.0
        if not 0.0 <= q <= 1.0:  # also rejects nan; an out-of-range weight is a malformed entry
            continue
        if q > best_q:
            best, best_q = language, q
    return best


@lru_cache(maxsize=len(SUPPORTED_LANGUAGES))
def _translations(language: str) -> gettext.NullTranslations:
    # English has no catalogue: the msgids are the English text.
    return gettext.translation(_DOMAIN, settings.locale_path, [language], fallback=True)


def request_language(request: Request) -> str:
    """Return the language this request is answered in."""
    return negotiate_language(request.headers.get("accept-language"))


def translate(language: str, message: str) -> str:
    """Translate one message, leaving it as is when the catalogue has no entry."""
    return _translations(language).gettext(message)


@lru_cache(maxsize=len(SUPPORTED_LANGUAGES))
def _templates(language: str) -> Jinja2Templates:
    env = Environment(
        loader=FileSystemLoader(settings.templates_path),
        cache_size=400,
        auto_reload=settings.debug,
        autoescape=True,
        extensions=["jinja2.ext.i18n"],
    )
    env.install_gettext_translations(_translations(language), newstyle=True)  # ty: ignore[unresolved-attribute]
    return Jinja2Templates(env=env)


def _vary_on_language(response: Response) -> None:
    """Add Accept-Language to the response's Vary header, keeping values already there."""
    existing = response.headers.get("Vary")
    if not existing:
        response.headers["Vary"] = _VARY_TOKEN
    elif _VARY_TOKEN.lower() not in existing.lower():
        response.headers["Vary"] = f"{existing}, {_VARY_TOKEN}"


def render(request: Request, name: str, context: dict[str, Any]) -> _TemplateResponse:
    """Render a template in the request's language, marking the response as varying on it."""
    language = request_language(request)
    response = _templates(language).TemplateResponse(request, name, {**context, "lang": language})
    _vary_on_language(response)
    return response


async def http_exception_handler(request: Request, exc: Exception) -> Response:
    """Answer an HTTP error in the request's language, then as FastAPI would."""
    http_exc = cast("StarletteHTTPException", exc)  # registered for this class only
    language = request_language(request)
    detail = http_exc.detail
    if isinstance(detail, str):
        detail = translate(language, detail)
    elif isinstance(detail, dict) and isinstance(detail.get("message"), str):
        detail = {**detail, "message": translate(language, detail["message"])}
    response = await default_http_exception_handler(
        request, StarletteHTTPException(http_exc.status_code, detail, http_exc.headers)
    )
    _vary_on_language(response)
    return response
