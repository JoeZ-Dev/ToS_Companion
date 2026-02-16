import time
from pathlib import Path

from momentum_companion.clients.token_provider import TokenProvider


def test_token_provider_refresh(tmp_path):
    refreshed = {}

    def refresh_cb(old):
        refreshed["called"] = True
        return {"access_token": "new", "expires_at": time.time() + 3600}

    token_path = tmp_path / "tokens.json"
    provider = TokenProvider(refresh_callback=refresh_cb, token_path=token_path)
    # seed cache
    provider.set_access_token("old", expires_at=time.time() + 1)
    # force refresh path
    time.sleep(1.1)
    token = provider()
    assert token == "new"
    assert refreshed.get("called") is True

    # explicit refresh call
    refreshed.clear()
    provider.refresh()
    assert refreshed.get("called") is True
