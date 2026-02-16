from momentum_companion.triggers.synthetic import SyntheticTriggerEngine


class DummyExecutor:
    def __init__(self):
        self.calls = []

    def submit_order(self, order_spec):
        self.calls.append(order_spec)
        return "ok"


def test_synthetic_arm_fire():
    exec = DummyExecutor()
    trig = SyntheticTriggerEngine(exec)
    trig.arm_stop("AAPL", 10.0, "SELL")
    trig.on_quote({"symbol": "AAPL", "bid": 9.9, "ask": 10.1, "qty": 1})
    assert exec.calls
