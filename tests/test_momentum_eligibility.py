import pytest
from momentum_companion.evaluation.momentum_eligibility import RvolObservation, calculate_time_adjusted_rvol, classify_momentum_eligibility

def classify(room, rvol=2.0, structure=True):
    return classify_momentum_eligibility(entry_price=100,decision_ts_ms=1000,detector_structure_valid=structure,
        resistance_levels=[{"type":"PMH","price":100*(1+room/100),"available_at_ms":1000}],resistance_evidence_complete=True,
        rvol={"status":"available","value":rvol,"history_sessions":20})

@pytest.mark.parametrize("room,expected",[(7.99,"monitor_only"),(8.0,"trade_candidate"),(10.0,"preferred_candidate")])
def test_room_boundaries(room,expected): assert classify(room)["classification"]==expected

@pytest.mark.parametrize("value,expected",[(1.99,"monitor_only"),(2.0,"trade_candidate")])
def test_rvol_boundaries(value,expected): assert classify(8,value)["classification"]==expected

def test_detector_arrow_alone_never_candidate(): assert classify(12,3,False)["classification"]=="monitor_only"

def test_missing_inputs_are_unavailable():
    common=dict(entry_price=100,decision_ts_ms=1000,detector_structure_valid=True)
    assert classify_momentum_eligibility(**common,resistance_levels=[],resistance_evidence_complete=False,rvol={"status":"available","value":2})["classification"]=="unavailable"
    assert classify_momentum_eligibility(**common,resistance_levels=[{"type":"PMH","price":110,"available_at_ms":900}],resistance_evidence_complete=True,rvol={"status":"unavailable","value":None,"explanation":"missing"})["classification"]=="unavailable"

def test_future_evidence_and_sessions_do_not_leak():
    result=classify_momentum_eligibility(entry_price=100,decision_ts_ms=1000,detector_structure_valid=True,
        resistance_levels=[{"type":"future","price":101,"available_at_ms":1001}],resistance_evidence_complete=True,
        rvol={"status":"available","value":2})
    assert result["classification"]=="unavailable"
    history=[RvolObservation(f"2026-08-{day:02d}","regular",60,100) for day in range(1,21)]
    history.append(RvolObservation("2026-09-30","regular",60,1))
    rvol=calculate_time_adjusted_rvol(trading_date="2026-09-29",market_phase="regular",phase_offset_seconds=60,cumulative_volume=200,history=history)
    assert rvol["value"]==pytest.approx(2.0)

def test_rvol_requires_twenty_prior_same_phase_observations():
    history=[RvolObservation(f"2026-08-{day:02d}","premarket",60,100) for day in range(1,20)]
    result=calculate_time_adjusted_rvol(trading_date="2026-09-29",market_phase="premarket",phase_offset_seconds=60,cumulative_volume=200,history=history)
    assert result["status"]=="unavailable" and "requires 20" in result["explanation"]

def test_duplicate_recordings_on_one_symbol_date_count_once():
    history=[]
    for day in range(1,21):
        history.append(RvolObservation(f"2026-08-{day:02d}","regular",60,100))
    history.append(RvolObservation("2026-08-20","regular",60,200))
    result=calculate_time_adjusted_rvol(trading_date="2026-09-29",market_phase="regular",phase_offset_seconds=60,cumulative_volume=200,history=history)
    assert result["status"]=="available"
    assert result["history_sessions"]==20
    assert result["median_prior_cumulative_volume"]==100

def test_distinct_dates_count_separately_but_current_and_future_never_do():
    history=[RvolObservation(f"2026-08-{day:02d}","premarket",60,100) for day in range(1,21)]
    history += [RvolObservation("2026-09-29","premarket",60,1),RvolObservation("2026-09-30","premarket",60,1)]
    result=calculate_time_adjusted_rvol(trading_date="2026-09-29",market_phase="premarket",phase_offset_seconds=60,cumulative_volume=200,history=history)
    assert result["status"]=="available" and result["value"]==pytest.approx(2.0)
