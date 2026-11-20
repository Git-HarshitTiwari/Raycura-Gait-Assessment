"""Bind the selected recording to fixed, citable assessment facts."""
import math

from .config import CHANNELS
from .myogait_rules import RULES, SOURCE_URL


def rule_evidence(result):
    """Format saved rule inputs consistently for the report and assistant."""
    evidence = []
    for condition in result["threshold_predicates"]:
        channel = condition["channel"]
        start, end = result["input_windows"][channel]
        observed = result["observed_values"][channel]
        angle = "unavailable"
        if observed is not None:
            shown = f"{observed:.2f}"
            if float(shown) == condition["threshold_deg"] and observed != condition["threshold_deg"]:
                shown = str(observed)
            angle = f"{shown}°"
        comparison = "≤" if condition["operator"] == "<=" else condition["operator"]
        evidence.append(f"{CHANNELS[channel][0]}, {start}–{end}% {condition['statistic']} "
                        f"{angle} (requires {comparison} {condition['threshold_deg']:g}°)")
    if result["status"] == "not_evaluated":
        evidence.extend(result["reasons"])
    return evidence


def _angle(value):
    return f"{value:.2f}°" if value is not None and math.isfinite(value) else "unavailable"


def _rule_cards(results, rid, side):
    """Use saved outcomes for this limb, including non-matches and missing inputs."""
    if {r["rule_id"] for r in results} != {r.id for r in RULES} or len(results) != len(RULES):
        raise ValueError("Incomplete or duplicate rule evidence for this recording.")
    outcomes = []
    matches = []
    withheld = 0
    checks = {
        "myogait_late_knee_flexion": "Inspect the late maximum and the whole-cycle knee span to see how much movement was recorded.",
        "myogait_hip_ankle_combination": "Inspect the hip maximum and ankle span separately. Their windows differ, so timing of compensation is unknown.",
        "myogait_elevated_knee_position": "Review the minimum across the entire curve and check the recorded neutral position before interpreting extension.",
        "myogait_nonpositive_early_ankle": "Review the ankle trace around the exported zero and check the neutral-position calibration before interpreting this sign.",
    }
    for result in results:
        status = result["status"]
        if result["record_id"] != rid or result["side"] != side:
            raise ValueError("Rule evidence belongs to a different recording or side.")
        if result["source_reference"]["url"] != SOURCE_URL or status not in ("matched", "not_matched", "not_evaluated"):
            raise ValueError("Unrecognized rule source or outcome.")
        title = result["display_name"]
        text = f"{title} — {status.replace('_', ' ')}. " + ". ".join(rule_evidence(result)) + "."
        if status == "matched":
            matches.append(title)
            text += " " + checks[result["rule_id"]]
        withheld += status == "not_evaluated"
        outcomes.append(dict(id=result["rule_id"], kind="source_rule", title=title, text=text,
            status=status, channels=result["required_channels"], source_ids=["MYOGAIT_RULES","ISB2024"]))
    summary = f"{len(matches)} of {len(results)} recorded movement conditions matched. {withheld} could not be evaluated."
    if matches:
        summary += " Matched conditions include " + ", ".join(matches) + "."
    limitation = " The windows use exported cycle percentages. Anatomical zero and physical phase timing are unverified."
    for card in outcomes:
        card["text"] += limitation
    return outcomes + [dict(id="rule_summary", kind="rule_summary", title="Recorded movement conditions",
                            text=summary + limitation, source_ids=["MYOGAIT_RULES","ISB2024"])]


def approved_cards(measurements,interpretation,ml=None,comparisons=None):
    """Construct cards only from rows belonging to the selected recording and side."""
    rid = interpretation["record_id"]
    if measurements.empty or set(measurements.record_id) != {rid} or measurements.channel.duplicated().any():
        raise ValueError("Expected unique motion measurements for the selected recording.")
    sides = set(measurements.side)
    if len(sides) != 1 or not sides <= {"left", "right"}:
        raise ValueError("Expected a single limb side.")
    side = next(iter(sides))
    if ml is not None and not ml.empty and set(ml.record_id) != {rid}:
        raise ValueError("ML rows belong to another recording.")
    if comparisons is not None and len(comparisons) and not ((comparisons.first_record == rid) | (comparisons.second_record == rid)).all():
        raise ValueError("Paired comparisons include another assessment.")
    cards=[]
    for _,r in measurements.iterrows():
        cards.append(dict(id="measurement_"+r.channel,title=CHANNELS[r.channel][0],kind="measurement",
            channels=[r.channel],
            text=(f"Recorded movement span {_angle(r.rom_deg)}. RMS difference from the selected reference mean "
                  f"{_angle(r.rms_difference_deg)}. Signed mean offset {_angle(r.mean_offset_deg)}. "
                  if r.measurement_status != "unusable" else "Measurements withheld. ") +
                 f"Quality: {r.measurement_status}. Reference: {r.reference_status}.",
            source_ids=["IOSA2014","BAKER2009"]))
    for c in interpretation["cards"]:
        cards.append(dict(id=c["id"],title=c["title"],kind=c["kind"],
            channels=c["channels"], text=c["observation"]+" "+c["interpretation"]+" Next check: "+c["next_check"],source_ids=c["source_ids"]))
    if "source_rule_results" in interpretation:
        cards.extend(_rule_cards(interpretation["source_rule_results"],rid,side))
    documented = "anatomical_direction_status" in measurements and measurements.anatomical_direction_status.eq("company_documented").all()
    direction_text = ("The company documents the positive and negative angle directions. " if documented else "")
    cards.append(dict(id="muscle_evidence_status",title="Muscle-function evidence",kind="evidence_status",
        text=(direction_text + "No complete muscle-specific finding is supported for this recording. Anatomical zero and physical support timing have not been independently verified. These angles cannot establish a particular muscle's activation or weakness, pain, or a diagnosis." if not interpretation["muscle_suggestion_count"] else "The recorded assessment contains a conditional examination suggestion. The cause and muscle activity remain undetermined."),source_ids=["ATTias2019","ISB2024"]))
    if ml is not None:
        enabled=int(ml.learned_flag_enabled.sum());eligible=int(ml.eligibility.eq("eligible").sum())
        cards.append(dict(id="ml_evidence_status",title="Learned movement relationships",kind="evidence_status",
            text=f"{eligible} channels have eligible candidate predictions; {enabled} channels passed all gates for learned review flags. Predictions describe statistical relationships among recorded curves. Good prediction does not establish healthy gait; individual uncertainty intervals and diagnostic accuracy are unestimated.",source_ids=["ISB2024"]))
    if comparisons is not None:
        count=len(comparisons[["first_record","second_record"]].drop_duplicates()) if len(comparisons) else 0
        cards.append(dict(id="repeat_evidence_status",title="Repeat and side evidence",kind="evidence_status",
            text=f"{count} paired recording comparisons are available for this assessment. Left/right recordings are separate walks. Acquisition conditions are not confirmed as matched, so recorded differences are not synchronized asymmetry or proven progression.",source_ids=["ISB2024"]))
    for card in cards:
        card.update(record_id=rid, side=side)
    return cards
