"""Evaluate four experimental movement conditions on one prepared Raycura limb.

Adapted from myogait by Frederic Fer, Institut de Myologie. See MYOGAIT_LICENSE.txt.
The predicates use recorded angles and fixed exported-cycle coordinates.
"""
from collections import Counter
from dataclasses import dataclass
import csv
import json
import operator

import numpy as np

from .myogait_adapter import LimbAssessment
from .prepared_dataset import EXPORTED_CYCLE_PERCENT


SOURCE_COMMIT = "524ee4629e26b4aa104a2f036e077b835fd263e7"
SOURCE_FILE = "myogait/analysis.py"
SOURCE_SHA256 = "ae7279a63b03169b4891c9cb7433e656543cdbebb9f739acf71396bf2e6a2126"
SOURCE_URL = f"https://github.com/IDMDataHub/myogait/blob/{SOURCE_COMMIT}/{SOURCE_FILE}"
ASSUMPTIONS = (
    "One exported limb recording supplies the angle curves.",
    "Windows use inclusive percentages of the exported cycle. Physical support and swing timing are unverified.",
    "The experimental angle thresholds use the exported zero as neutral. Anatomical zero is unverified.",
)


@dataclass(frozen=True)
class Criterion:
    channel: str
    statistic: str
    start: int
    end: int
    comparison: str
    threshold: float


@dataclass(frozen=True)
class Rule:
    id: str
    title: str
    source_alias: str
    source_function: str
    criteria: tuple[Criterion, ...]


RULES = (
    Rule("myogait_late_knee_flexion", "Lower late-window knee flexion", "spastic", "detect_pathologies",
         (Criterion("knee_flexion", "maximum", 60, 100, "<", 40.0),)),
    Rule("myogait_hip_ankle_combination", "High late-window hip flexion with small ankle span", "steppage", "detect_pathologies",
         (Criterion("hip_flexion", "maximum", 60, 100, ">", 45.0),
          Criterion("ankle_dorsiflexion", "span", 0, 100, "<", 15.0))),
    Rule("myogait_elevated_knee_position", "Knee angle remains elevated throughout the recording", "crouch", "detect_pathologies",
         (Criterion("knee_flexion", "minimum", 0, 100, ">", 15.0),)),
    Rule("myogait_nonpositive_early_ankle", "Ankle angle stays non-positive in the early window", "equinus", "detect_equinus",
         (Criterion("ankle_dorsiflexion", "maximum", 0, 60, "<=", 0.0),)),
)
_SUMMARIES = {"maximum": np.max, "minimum": np.min, "span": np.ptp}
_COMPARISONS = {"<": operator.lt, ">": operator.gt, "<=": operator.le}


def _usable_curve(assessment, channel):
    motion = assessment.motions.get(channel)
    if motion is None:
        return None, "missing channel"
    status = motion.measurements.get("measurement_status")
    if status != "usable":
        return None, f"quality status {status or 'unknown'}"
    try:
        curve = np.asarray(motion.recorded)
    except (TypeError, ValueError):
        return None, "invalid angle array"
    if curve.shape != (101,) or curve.dtype.kind not in "iuf" or np.ma.is_masked(motion.recorded):
        return None, "expected 101 numeric angles"
    if not np.isfinite(curve).all():
        return None, "nonfinite angle"
    return curve.astype(float, copy=False), None


def evaluate_myogait_rules(assessment: LimbAssessment) -> list[dict]:
    """Return all four outcomes, including per-channel inputs and abstention reasons."""
    rid, side = assessment.metadata["record_id"], assessment.metadata["side"]
    if not rid or side not in ("left", "right"):
        raise ValueError("A recording ID and limb side are required for rule evaluation.")
    grid_ok = np.array_equal(assessment.grid_percent, EXPORTED_CYCLE_PERCENT)
    results = []
    for rule in RULES:
        observed, windows, predicates = {}, {}, []
        unavailable, failed = [], []
        for term in rule.criteria:
            ch = term.channel
            windows[ch] = [term.start, term.end]
            predicates.append(dict(channel=ch, statistic=term.statistic, operator=term.comparison,
                                   threshold_deg=term.threshold))
            curve, reason = _usable_curve(assessment, ch) if grid_ok else (None, "invalid cycle grid")
            if reason:
                unavailable.append(f"{ch}: {reason}")
                observed[ch] = None
                continue
            value = float(_SUMMARIES[term.statistic](curve[term.start:term.end + 1]))
            observed[ch] = value
            if not _COMPARISONS[term.comparison](value, term.threshold):
                failed.append(f"{ch}: {term.statistic} outside rule condition")
        status = "matched"
        if unavailable:
            status = "not_evaluated"
        elif failed:
            status = "not_matched"
        results.append(dict(
            record_id=rid, side=side, rule_id=rule.id, display_name=rule.title, status=status,
            required_channels=list(windows), input_windows=windows, observed_values=observed,
            threshold_predicates=predicates, assumptions=list(ASSUMPTIONS),
            source_reference=dict(url=SOURCE_URL, commit=SOURCE_COMMIT, file=SOURCE_FILE,
                                  function=rule.source_function, alias=rule.source_alias),
            reasons=unavailable or failed,
        ))
    return results


def summarize_rule_results(by_record):
    """Count statuses per rule and distinct recordings with at least one match."""
    counts = {rule.id: Counter(matched=0, not_matched=0, not_evaluated=0) for rule in RULES}
    matched_recordings = 0
    for results in by_record.values():
        for r in results:
            counts[r["rule_id"]][r["status"]] += 1
        matched_recordings += any(r["status"] == "matched" for r in results)
    return dict(assessments=len(by_record), evaluations=sum(sum(c.values()) for c in counts.values()),
                matched_assessments=matched_recordings, by_rule={k:dict(v) for k,v in counts.items()})


def write_rule_results_csv(path, by_record):
    """Keep one row per evaluation and serialize compound evidence as standard JSON."""
    fields = ("record_id", "side", "rule_id", "display_name", "status", "required_channels",
              "input_windows", "observed_values", "threshold_predicates", "assumptions",
              "source_reference", "reasons")
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for results in by_record.values():
            for result in results:
                writer.writerow({k: json.dumps(v, allow_nan=False) if isinstance(v, (dict, list)) else v
                                 for k, v in result.items()})
