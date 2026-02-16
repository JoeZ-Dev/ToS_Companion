from momentum_companion.data.schema import init_db
from momentum_companion.state.app_state import AppStateStore


def test_app_state_set_get(tmp_path):
    db_path = tmp_path / "data.db"
    init_db(db_path)
    store = AppStateStore(str(db_path))
    assert store.get("missing") is None
    store.set("foo", "bar")
    assert store.get("foo") == "bar"
