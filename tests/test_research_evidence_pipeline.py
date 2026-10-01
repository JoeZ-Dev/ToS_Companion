from datetime import date, datetime
from zoneinfo import ZoneInfo

from momentum_companion.evaluation.momentum_eligibility import classify_momentum_eligibility
from momentum_companion.evaluation.prospective_holdout import _causal_resistance_levels
from momentum_companion.evaluation.schwab_retention_canary import analyze_response
from momentum_companion.recording.rvol_enrollment import EnrollmentRvolEvidenceCollector
from momentum_companion.recording.trigger_context import (
    attach_detector_resistance_evidence,
    build_trigger_context,
)


ET = ZoneInfo("America/New_York")


def _ms(day, hour, minute=0):
    return int(datetime.fromisoformat(f"{day}T{hour:02d}:{minute:02d}:00").replace(tzinfo=ET).timestamp()*1000)


def test_canary_excludes_server_rows_outside_requested_bounds():
    start, end = _ms("2026-08-01", 0), _ms("2026-08-03", 0)
    response = {"symbol":"XYZ","candles":[
        {"datetime":_ms("2026-08-01",8),"volume":1},
        {"datetime":_ms("2026-08-01",10),"volume":1},
        {"datetime":_ms("2026-08-03",8),"volume":1},
    ]}
    result=analyze_response(symbol="XYZ",response=response,requested_start_ms=start,requested_end_ms=end,receipt_timestamp="locked")
    assert result["returned_trading_dates"]==["2026-08-01"]
    assert result["api_response_metadata"]["out_of_requested_bounds_candle_count"]==1


def test_wrapped_nearest_resistance_is_parsed_with_source_and_distance():
    group={"detector_events":[{"observation_ts_ms":900,"trigger_context":{
        "context_as_of_ts_ms":900,
        "session_levels":{key:{"available":True,"value":value} for key,value in {
            "premarket_high":110,"opening_range_high":109,"regular_session_high":108,"vwap":100}.items()},
        "structural_levels":{"nearest_resistance":{"available":True,"value":{
            "price":112,"source":"micro_resistance_15m","distance_pct":12}}},
    }}]}
    levels,complete=_causal_resistance_levels(group,1000)
    nearest=next(item for item in levels if item["type"]=="micro_resistance_15m")
    assert nearest["price"]==112 and nearest["distance_pct"]==12
    assert complete is False


def test_unavailable_orh_and_rth_do_not_imply_complete():
    group={"detector_events":[{"observation_ts_ms":900,"trigger_context":{
        "session_levels":{
            "premarket_high":{"available":True,"value":110},
            "opening_range_high":{"available":False,"value":None},
            "regular_session_high":{"available":False,"value":None},
            "vwap":{"available":True,"value":100},
        }}}]}
    assert _causal_resistance_levels(group,1000)[1] is False


def test_prior_day_high_participates_and_broken_level_is_not_next_overhead():
    stamp=_ms("2026-09-29",10)
    context=build_trigger_context(symbol_state={
        "quote":{"ts_ms":stamp,"last":100},
        "history_bars":[
            {"time":_ms("2026-09-28",10)//1000,"open":105,"high":111,"low":104,"close":110,"volume":10},
            {"time":_ms("2026-09-29",8)//1000,"open":99,"high":105,"low":98,"close":100,"volume":10},
            {"time":_ms("2026-09-29",9,30)//1000,"open":100,"high":104,"low":99,"close":103,"volume":10},
        ],
        "bars_10s":[],"ae_snapshot":{"vwap":101,"micro":{"micro_resistance_15m":109},"levels":{"nearest_resistance":{"price":102,"source":"broken_structure"}}},
    },bar={"close":100,"volume":1},observation_ts_ms=stamp)
    types={item["source_type"]:item for item in context["resistance_registry"]["candidates"]}
    assert types["prior_day_high"]["price"]==111
    enriched=attach_detector_resistance_evidence(context,{"evidence":{"breakout_level":102}})
    broken=next(item for item in enriched["resistance_registry"]["candidates"] if item["source_type"].endswith("breakout_level"))
    assert broken["role"]=="broken_level"
    assert enriched["resistance_registry"]["selected_nearest_overhead_resistance"]["price"] != 102


def test_incomplete_registry_makes_eligibility_unavailable():
    result=classify_momentum_eligibility(entry_price=100,decision_ts_ms=1000,
        detector_structure_valid=True,resistance_levels=[{"type":"PMH","price":110,"available_at_ms":900}],
        resistance_evidence_complete=False,rvol={"status":"available","value":3})
    assert result["classification"]=="unavailable"


def test_enrollment_excludes_current_session_and_never_overwrites_complete(tmp_path):
    rows=[]
    for index in range(40):
        day=date.fromordinal(date(2026,7,20).toordinal()+index)
        if day.weekday()>=5: continue
        rows.extend([{"datetime":_ms(day.isoformat(),8),"volume":10},{"datetime":_ms(day.isoformat(),10),"volume":20}])
    rows.extend([{"datetime":_ms("2026-09-01",8),"volume":999},{"datetime":_ms("2026-09-01",10),"volume":999}])
    class Rest:
        def __init__(self): self.rows=rows
        def fetch_price_history(self,*args): return {"candles":self.rows}
    collector=EnrollmentRvolEvidenceCollector(Rest(),tmp_path,calendar_days=50,minimum_interval_seconds=0,
        now_provider=lambda:datetime(2026,9,1,12,tzinfo=ET))
    first=collector.enroll("XYZ",decision_date=date(2026,9,1))
    assert all(item["trading_date"]<"2026-09-01" for item in first["sessions"])
    assert first["coverage"]["complete"] is True
    collector.rest.rows=[]
    second=collector.enroll("XYZ",decision_date=date(2026,9,1))
    assert second==first


def test_evidence_attachment_does_not_mutate_detector_observation():
    observation={"evidence":{"breakout_level":10.0},"state":"BREAKOUT"}
    before={"evidence":dict(observation["evidence"]),"state":observation["state"]}
    attach_detector_resistance_evidence({"price":{"available":True,"value":9.5},"context_as_of_ts_ms":1},observation)
    assert observation==before
