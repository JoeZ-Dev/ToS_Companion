import json
from fastapi.testclient import TestClient
from momentum_companion.evaluation.trade_review import DETECTOR_TOOLTIP, TradeReviewStore
from momentum_companion.review import ReviewCorpus
from momentum_companion.web import create_app
from test_web_app import FakeReplayEngine, FakeRuntime

def artifact():
    def result(value):
        return {"available":True,"reason":None,"legs":[{"status":"TRADE","decision_ts_ms":1000,"entry_ts_ms":1100,"entry_price":10,"stop_price":9.5,"target_price":11,"exit_ts_ms":2000,"exit_price":11,"exit_reason":"TARGET","realized_r":value,"realized_pct":10,"mfe_r":2.1,"mae_r":-.2}]}
    return {"kind":"offline_counterfactual_execution_research","classification":"exploratory_historical_comparison_not_validation","code_revision":"fixture","paired_production_vs_confirmed_detector_stop":{"overall":{"both_policies_traded":1}},"opportunities":[{"opportunity_id":"OPP-1","session_id":"missing","trading_date":"2026-09-23","symbol":"XYZ","review_ts_ms":1000,"pattern_types":["LOCAL_RESISTANCE_BREAKOUT"],"human_label":"clear","policy_results":{"production_baseline":result(1),"confirmed_detector_stop":result(2)}}]}

def test_historical_rows_paired_and_accessible_markers(tmp_path):
    (tmp_path/"counterfactual-results.json").write_text(json.dumps(artifact()))
    store=TradeReviewStore(tmp_path,ReviewCorpus(tmp_path/"recordings")); rows=store.opportunities(run_id="root");detail=store.detail("root","OPP-1");chart=store.chart("root","OPP-1")
    assert rows["count"]==1 and rows["opportunities"][0]["realized_r"]==2
    assert detail["paired_comparison"]["paired_r_delta"]==1
    assert detail["paired_comparison"]["decomposition"]=="delayed_entry_execution_effect"
    assert chart["markers"][0]["tooltip"]==DETECTOR_TOOLTIP
    assert all(m["accessible_label"] and m["tooltip"] for m in chart["markers"])

def test_missing_artifacts_leave_normal_app_available(tmp_path):
    with TestClient(create_app(FakeRuntime(),replay_engine=FakeReplayEngine(),research_output_root=tmp_path)) as client:
        assert client.get("/api/health").status_code==200; payload=client.get("/api/trade-review/runs").json()
    assert payload["available"] is False and "No research artifacts" in payload["empty_state"]

def test_api_and_accessibility_copy(tmp_path):
    (tmp_path/"counterfactual-results.json").write_text(json.dumps(artifact()))
    with TestClient(create_app(FakeRuntime(),replay_engine=FakeReplayEngine(),research_output_root=tmp_path)) as client:
        assert client.get("/api/trade-review/runs").json()["available"] is True
        assert client.get("/api/trade-review/opportunities",params={"run_id":"root"}).json()["count"]==1
        assert client.get("/api/trade-review/chart/OPP-1",params={"run_id":"root"}).json()["detector_marker_disclaimer"]==DETECTOR_TOOLTIP
        html=client.get("/").text; js=client.get("/app-20260922-13.js").text
    assert "TRADE REVIEW" in html.upper() and DETECTOR_TOOLTIP in html and "accessible_label" in js
