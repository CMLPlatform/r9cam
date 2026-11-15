"""The relay allowlist must name routes the app really serves, behind the expected auth."""

import re

import pytest
from httpx import AsyncClient

from app.main import app
from r9cam_models import RELAY_ALLOWED_EXACT_COMMANDS, RELAY_ALLOWED_PREFIX_COMMANDS, relay_command_is_allowed

_PARAM = re.compile(r"\{[^}]+\}")
_UNAUTHENTICATED = {401, 403}


def _operations() -> dict[tuple[str, str], dict]:
    """Return the app's served (METHOD, concrete path) operations from its OpenAPI schema."""
    schema = app.openapi()
    return {
        (method.upper(), _PARAM.sub("x", path)): op
        for path, item in schema["paths"].items()
        for method, op in item.items()
    }


@pytest.mark.parametrize(("method", "path"), sorted(RELAY_ALLOWED_EXACT_COMMANDS))
def test_exact_allowlist_entry_has_an_authenticated_route(method: str, path: str) -> None:
    """Every exact entry is a served route that declares an API-key security scheme."""
    operation = _operations().get((method, path))

    assert operation is not None, f"no {method} route serves allowlisted relay path {path}"
    assert operation.get("security"), f"{method} {path} is relayable but not behind auth"


@pytest.mark.parametrize(("method", "path"), sorted(RELAY_ALLOWED_EXACT_COMMANDS))
async def test_exact_allowlist_entry_rejects_missing_credentials(
    unauthed_client: AsyncClient, method: str, path: str
) -> None:
    """Every exact entry answers 401/403 without credentials."""
    response = await unauthed_client.request(method, path)

    assert response.status_code in _UNAUTHENTICATED


@pytest.mark.parametrize(("method", "prefix"), sorted(RELAY_ALLOWED_PREFIX_COMMANDS))
def test_prefix_allowlist_entry_has_a_route_under_it(method: str, prefix: str) -> None:
    """Every prefix entry has a public served route beneath it."""
    matches = [(m, p, op) for (m, p), op in _operations().items() if m == method and p.startswith(prefix)]

    assert matches, f"no {method} route lives under allowlisted relay prefix {prefix}"
    for _, path, operation in matches:
        assert relay_command_is_allowed(method, path)
        # HLS preview is served without credentials by design.
        assert not operation.get("security")
