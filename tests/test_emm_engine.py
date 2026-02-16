from momentum_companion.execution.emm_engine import EMMEngine


class DummyRest:
    def place_order(self, account_id, payload):
        return f"{account_id}-oid"

    def replace_order(self, account_id, oid, payload):
        return oid


def test_emm_timeout():
    emm = EMMEngine(DummyRest())
    status = emm.execute("acc1", "BUY", 1, 10.0, {"emm_max_chase_duration_s": 0.001}, {"ask": 10.0})
    assert status == "emm_timeout"
