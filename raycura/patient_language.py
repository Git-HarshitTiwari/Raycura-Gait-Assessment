"""Patient-facing descriptions of saved motion results and company report intervals."""
import json
import math
import re
from functools import lru_cache

from .config import CHANNELS, NAMES, PHASES, ROOT

MOVEMENTS = {
    "pelvic_obliquity": "side-to-side pelvic tilt", "pelvic_rotation": "pelvic turning",
    "pelvic_tilt": "forward and backward pelvic tilt", "hip_flexion": "forward and backward hip movement",
    "hip_abduction": "sideways hip movement", "hip_rotation": "hip turning",
    "knee_flexion": "knee bending and straightening", "knee_abduction": "sideways knee angling",
    "knee_rotation": "knee turning", "ankle_dorsiflexion": "upward and downward ankle movement",
}
CHECK_NAMES = {
    "myogait_hip_ankle_combination": "Extra hip bend late in the cycle together with a small ankle movement",
    "myogait_late_knee_flexion": "Less knee bend late in the cycle",
    "myogait_elevated_knee_position": "A knee that stayed bent throughout the cycle",
    "myogait_nonpositive_early_ankle": "An ankle angle that stayed at or below the recorded zero early in the cycle",
}
CHECK_GUIDES = {
    "myogait_hip_ankle_combination": "This check looks for two things together: the hip bending past 45° in the last 40% of the cycle and the ankle moving through less than 15° over the whole cycle.",
    "myogait_late_knee_flexion": "This check looks for a knee that never reaches 40° of bend during the last 40% of the cycle.",
    "myogait_elevated_knee_position": "This check looks for a knee angle that stays above 15° of bend throughout the cycle.",
    "myogait_nonpositive_early_ankle": "This check looks for an ankle angle that never rises above its recorded zero during the first 60% of the cycle.",
}
METHOD_NOTE = "The cutoffs come from the published myogait software rule. They define the pattern being checked. They are separate from the reference ranges at the eight marked points."
DEFINITIONS = {
    "rom_deg": "Range of motion is how far the angle moved from its lowest to its highest point during this walk.",
    "rms_difference_deg": "Curve difference compares angles at the same 101 positions in the cycle. It gives one gap in degrees, with larger gaps carrying more weight.",
    "mean_offset_deg": "Offset tells you whether the recorded angle sat higher or lower than the reference curve on average. Differences in opposite directions can cancel.",
}
METRIC_TITLES = {"rom_deg":"Range of motion","rms_difference_deg":"Curve difference","mean_offset_deg":"Average offset"}

CYCLE_GUIDE = "Read from left to right through one walking cycle. At 50% you are halfway through that recorded cycle."


def graph_guide(motion, directions):
    """Explain the signed vertical axis using the configured anatomical convention."""
    terms = {
        "lift": "the recorded side of the pelvis lifting", "drop": "that side lowering",
        "anterior": "the pelvis tilting forward", "posterior": "the pelvis tilting backward",
        "external rotation": "outward turning", "internal rotation": "inward turning",
        "flexion": "the joint bending", "extension": "the joint straightening",
        "abduction": "the thigh moving away from the body's midline", "adduction": "the thigh moving toward the midline",
        "valgus": "the knee angling inward", "varus": "the knee angling outward",
        "dorsiflexion": "the foot tipping up toward the shin", "plantarflexion": "the foot pointing down",
    }
    positive = directions["positive_direction"].replace("_", " ")
    negative = directions["negative_direction"].replace("_", " ")
    up = terms.get(positive, positive)
    down = terms.get(negative, negative)
    joint = motion.split("_")[0]
    if joint in ("hip", "knee"):
        up, down = up.replace("the joint", "the "+joint), down.replace("the joint", "the "+joint)
    return f"A rising line shows {up}. A falling line shows {down}."


def display_name(raw):
    """Uppercase the first letter of each name part, preserving the remaining spelling."""
    return re.sub(r"(^|[\s’'.-])([^\W\d_])", lambda m: m[1] + m[2].upper(), raw.strip())


def degrees(value):
    return ("−" if value < 0 else "") + f"{abs(value):.2f}".rstrip("0").rstrip(".") + "°"


def difference_size(value):
    return "less than 0.01°" if 0 < abs(value) < 0.005 else degrees(abs(value))


def directional(value, directions):
    direction = directions["positive_direction" if value > 0 else "negative_direction"].replace("_"," ")
    return "0°" if value == 0 else f"{difference_size(value)} {direction}"


@lru_cache(maxsize=1)
def phase_ranges():
    source = json.loads((ROOT/"evidence"/"phase_angle_ranges.json").read_text(encoding="utf-8"))
    if source["phase_order"] != list(PHASES) or set(source["motions"]) != set(NAMES):
        raise ValueError("Reference ranges do not cover the configured phases and motions.")
    for spec in source["motions"].values():
        if len(spec["bounds"]) != 8 or any(not (math.isfinite(a) and math.isfinite(b) and a <= b) for a,b in spec["bounds"]):
            raise ValueError("Invalid phase reference interval.")
    return source["motions"]


def phase_comparison(values, marks, motion, directions):
    """Read the angle at each exact manual grid mark. Use unrounded, inclusive limits."""
    spec = phase_ranges()[motion]
    rows = []
    for mark,(low,high) in zip(marks,spec["bounds"],strict=True):
        pct = mark["pct"]
        value = float(values[int(pct)]) if 0 <= pct <= 100 and float(pct).is_integer() else math.nan
        if not math.isfinite(value):
            reading,position,gap = "Unavailable","Unavailable",None
        else:
            reading = directional(value,directions)
            gap = max(low-value,value-high,0.0)
            position = "Within range" if gap == 0 else difference_size(gap)+" outside"
        rows.append(dict(phase=mark["name"],pct=pct,angle=value if math.isfinite(value) else None,
                         reading=reading,low=low,high=high,range=directional(low,directions)+" to "+directional(high,directions),
                         position=position,gap=gap,page=spec["page"]))
    return rows


def compare_walks(motion, pair):
    gap = pair["rangeDifference"]
    movement = MOVEMENTS[motion]
    span = (f"The right walk showed {difference_size(gap)} {'less' if gap < 0 else 'more'} {movement} than the left."
            if gap else f"Both walks covered the same range of {movement}.")
    rms = degrees(pair["rms"])
    return span + f" Comparing the angles point by point gives a gap of {rms} across the cycle (RMS)."


def describe_observation(card, metric, group_rom):
    """Give a saved finding plain wording using the original recording and comparison values."""
    motion = card["channels"][0]
    if card.get("family") == "reduced_excursion":
        return card | dict(
            title="A smaller range of movement",
            observation=(f"The range for {MOVEMENTS[motion]} was {degrees(metric['rom_deg'])}. "
                         f"The middle value in the comparison group for this side was {degrees(group_rom)}."),
            interpretation="The curve followed a similar overall shape to the reference, but the angle moved through a smaller range.",
            next_check="Check whether the same difference appears on another walk recorded under similar conditions.")
    if card.get("family") == "offset_dominated":
        return card | dict(
            title="A similar movement at a different angle",
            observation=metric_example("mean_offset_deg", metric, motion),
            interpretation="Most of the gap comes from the whole curve sitting higher or lower. Its shape and size were similar to the reference.",
            next_check="Check the starting posture and sensor position before drawing a conclusion from the angle.")
    return card


def rule_description(rule):
    if rule["status"] == "not_evaluated":
        return "There were too few usable measurements to check this pattern."
    values = rule["observed_values"]
    rid = rule["rule_id"]
    if rid == "myogait_hip_ankle_combination":
        detail = (f"The hip reached {degrees(values['hip_flexion'])} of bend late in the cycle. "
                  f"The ankle moved through {degrees(values['ankle_dorsiflexion'])} over the whole cycle.")
    elif rid == "myogait_nonpositive_early_ankle":
        detail = f"The highest ankle angle in the first 60% of the cycle was {degrees(values['ankle_dorsiflexion'])}."
    elif rid == "myogait_late_knee_flexion":
        detail = f"The greatest knee bend in the last 40% of the cycle was {degrees(values['knee_flexion'])}."
    else:
        detail = f"The lowest knee angle during this walk was {degrees(values['knee_flexion'])}."
    return detail


def metric_example(field, metric, motion):
    val = metric[field]
    if val is None or not math.isfinite(val):
        return "This measurement is unavailable for this walk."
    name = MOVEMENTS[motion]
    if field == "rom_deg":
        return (f"The range for {name} was {degrees(val)}. "
                f"The recorded angle went from {degrees(metric['min_deg'])} to {degrees(metric['max_deg'])}.")
    if field == "rms_difference_deg":
        return f"For {name}, the overall gap from the reference curve was {degrees(val)} (RMS)."
    if val == 0:
        return f"For {name}, the average recorded angle equalled the reference average."
    return f"For {name}, the recorded angle averaged {difference_size(val)} {'below' if val < 0 else 'above'} the reference curve."
