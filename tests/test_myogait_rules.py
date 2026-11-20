"""Boundary, quality and isolation checks for the four exported-angle predicates."""
from types import SimpleNamespace

import numpy as np
import pytest

from raycura.myogait_rules import evaluate_myogait_rules


def assessment():
    channels = ("knee_flexion", "hip_flexion", "ankle_dorsiflexion")
    motions = {ch: SimpleNamespace(recorded=np.zeros(101), measurements={"measurement_status": "usable"})
               for ch in channels}
    return SimpleNamespace(metadata={"record_id": "limb", "side": "left"}, motions=motions,
                           grid_percent=tuple(range(101)), phase_protocol_verified=False)


@pytest.mark.parametrize("rule,channel,index,value,expected", [
    (0, "knee_flexion", 59, 40., True),
    (0, "knee_flexion", 60, 40., False),
    (0, "knee_flexion", 100, np.nextafter(40., 0.), True),
    (0, "knee_flexion", 100, 40., False),
    (3, "ankle_dorsiflexion", 0, 1., False),
    (3, "ankle_dorsiflexion", 60, 0., True),
    (3, "ankle_dorsiflexion", 60, np.nextafter(0., 1.), False),
    (3, "ankle_dorsiflexion", 61, 1., True),
])
def test_inclusive_windows(rule, channel, index, value, expected):
    limb = assessment()
    limb.motions[channel].recorded[index] = value
    result = evaluate_myogait_rules(limb)[rule]
    assert result["status"] == ("matched" if expected else "not_matched")
    assert limb.phase_protocol_verified is False


@pytest.mark.parametrize("index", [0, 60, 100])
def test_whole_knee_strict_minimum(index):
    limb = assessment()
    knee = limb.motions["knee_flexion"].recorded
    knee[:] = np.nextafter(15., 20.)
    assert evaluate_myogait_rules(limb)[2]["status"] == "matched"
    knee[index] = 15.
    assert evaluate_myogait_rules(limb)[2]["status"] == "not_matched"


@pytest.mark.parametrize("hip,ankle,matched", [
    (45., 14., False), (46., 15., False), (45., 15., False),
    (np.nextafter(45., 50.), np.nextafter(15., 0.), True),
])
def test_combination_requires_both_terms(hip, ankle, matched):
    limb = assessment()
    limb.motions["hip_flexion"].recorded[60] = hip
    limb.motions["ankle_dorsiflexion"].recorded[0] = ankle
    result = evaluate_myogait_rules(limb)[1]
    assert result["status"] == ("matched" if matched else "not_matched")
    assert result["input_windows"] == {"hip_flexion": [60, 100], "ankle_dorsiflexion": [0, 100]}
    assert result["observed_values"] == {"hip_flexion": hip, "ankle_dorsiflexion": ankle}


@pytest.mark.parametrize("issue", ["missing", "short", "suspect", "unusable", "nan", "inf", "text", "masked"])
def test_bad_channel_only_withholds_dependent_rules(issue):
    limb = assessment()
    motion = limb.motions["ankle_dorsiflexion"]
    if issue == "missing":
        del limb.motions["ankle_dorsiflexion"]
    elif issue in ("suspect", "unusable"):
        motion.measurements["measurement_status"] = issue
    elif issue == "short":
        motion.recorded = np.zeros(100)
    elif issue == "text":
        motion.recorded = ["0"] * 101
    elif issue == "masked":
        motion.recorded = np.ma.masked_equal(motion.recorded, 0)
    else:
        motion.recorded[100] = float(issue)
    results = evaluate_myogait_rules(limb)
    assert [r["status"] for r in results] == ["matched", "not_evaluated", "not_matched", "not_evaluated"]
    assert results[1]["reasons"] and results[1]["observed_values"]["ankle_dorsiflexion"] is None
    assert results[1]["observed_values"]["hip_flexion"] == 0.


def test_grid_identity_and_inputs():
    limb = assessment()
    before = evaluate_myogait_rules(limb)
    limb.manual_marks = [("A", 73)]
    limb.motions["hip_flexion"].selected_reference = np.arange(101)
    assert evaluate_myogait_rules(limb) == before
    limb.grid_percent = tuple(reversed(limb.grid_percent))
    assert all(r["status"] == "not_evaluated" for r in evaluate_myogait_rules(limb))
    limb.metadata["side"] = "unknown"
    with pytest.raises(ValueError, match="side"):
        evaluate_myogait_rules(limb)


def test_unrelated_curve_and_other_limb_cannot_affect_current_decisions():
    limb = assessment()
    before = evaluate_myogait_rules(limb)
    other = assessment()
    other.metadata["side"] = "right"
    other.motions["knee_flexion"].recorded[:] = 80.
    assert evaluate_myogait_rules(other)[0]["status"] == "not_matched"
    limb.motions["pelvic_tilt"] = SimpleNamespace(recorded=np.full(101, np.nan), measurements={})
    assert evaluate_myogait_rules(limb) == before


def test_display_preserves_threshold_side_and_reports_unavailable():
    from raycura.assessment_reports import export_html, rule_results_markdown
    limb = assessment()
    near = np.nextafter(40., 0.)
    limb.motions["knee_flexion"].recorded[60] = near
    del limb.motions["ankle_dorsiflexion"]
    shown = rule_results_markdown(evaluate_myogait_rules(limb))
    assert f"{near}° (requires < 40°)" in shown
    assert "requires &lt; 40°" in export_html(shown, [])
    assert "not evaluated" in shown and "missing channel" in shown
    assert "spastic" not in shown and "steppage" not in shown
