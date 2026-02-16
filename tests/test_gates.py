class DummyStream:
    def __init__(self, connected: bool, fresh: bool):
        self._connected = connected
        self._fresh = fresh

    def connection_state(self):
        return "CONNECTED" if self._connected else "DISCONNECTED"

    def is_fresh(self, now_ms: int):
        return self._fresh


from momentum_companion.gates import evaluate_gate


def test_gate_enabled_when_all_true():
    gate = evaluate_gate(True, DummyStream(True, True), True, True, 0)
    assert gate.enabled is True


def test_gate_disabled_when_stale():
    gate = evaluate_gate(True, DummyStream(True, False), True, True, 0)
    assert gate.enabled is False
