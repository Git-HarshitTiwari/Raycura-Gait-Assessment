"""Answer supported questions with the selected walk's measurements and published definitions."""
import math
import re

from .config import CHANNELS, NAMES
from .patient_language import (CHECK_GUIDES, CYCLE_GUIDE, DEFINITIONS, METHOD_NOTE, compare_walks,
                               degrees, directional, graph_guide, metric_example, rule_description)
from .evidence_assistant import corpus

METRIC_TERMS = {
    "rom_deg": r"\b(rom|range of (motion|movement)|movement span|excursion|how far)\b",
    "rms_difference_deg": r"\b(rms[e]?|curve (difference|gap)|overall (curve )?difference|difference between (the )?curves)\b",
    "mean_offset_deg": r"\b(offset|average (angular )?(shift|offset)|signed (mean )?offset)\b",
}
CLINICAL = r"\b(pain\w*|sore\w*|weak\w*|injur\w*|stroke|diseas\w*|diagnos\w*|treat\w*|surg\w*|medicat\w*|fracture|limp\w*|abnormal\w*|muscl\w*|arthritis|contracture|normal gait|walking normally)\b"


def explain_walk(store, rid, question, selected):
    record = store.records.loc[rid]
    side = record.side
    q = question.lower().replace("-", " ")
    docs = {d["id"]:d for d in corpus()}
    def reply(title, paragraphs, source_ids=(), mode="saved_explanation"):
        return dict(record_id=rid, side=side, mode=mode,
                    cards=[dict(id="walk_explanation",title=title,text=" ".join(paragraphs),
                                record_id=rid,side=side,source_ids=list(source_ids))],
                    sources=[docs[k] for k in source_ids])
    def scope(message):
        return reply("What I can answer",[message],mode="scope_help")

    if re.search(CLINICAL,q):
        return reply("What the recording can tell you",
                     ["These angles show how the joints moved. They cannot identify an injury, a diagnosis, a painful area or a weak muscle.",
                      "You can ask which pattern was seen or how far a joint moved."],["ISB2024","ATTias2019"])
    if re.search(r"\b(speed|cadence|pressure|force|stress|friction|medication|steps per minute)\b",q):
        return scope("This assessment measures angles. It does not supply that measurement.")
    both = bool(re.search(r"\b(which (leg|side|walk) (moved (more|less)|had a (larger|smaller) range)|both (walks|sides|legs)|compare (the |my |these )?(two )?(walks|sides|legs)|left (and|vs|versus) right|right (and|vs|versus) left)\b",q))
    if not both and re.search(r"\b"+("right" if side=="left" else "left")+r"\b",q):
        return scope("The "+side+" walk is selected. Switch the walk selector to ask about the other side.")

    # Resolve explicit anatomical words. A joint alone may use the selected plane;
    # asking about a different joint with several planes requires clarification.
    joints = {("pelvic" if j=="pelvis" else j) for j in re.findall(r"\b(hip|knee|ankle|pelvic|pelvis)\b",q)}
    asks_why_45 = bool(re.fullmatch(r"\s*why (?:use |is (?:it |the cutoff )?)?45\s*(?:°|degrees?)?\s*[?.!]*\s*",q))
    condition = asks_why_45 or bool(re.search(r"\b(rule|pattern|check|match|cutoff|threshold)\w*\b",q))
    degree_45 = bool(re.search(r"\b45\s*(?:°|degrees?\b)",q))
    hip_ankle = condition and (joints == {"hip","ankle"} or asks_why_45 or
                               (degree_45 and joints <= {"hip","ankle"}))
    if len(joints)>1 and not hip_ankle:
        return scope("Please choose one motion or name a specific movement check.")
    motion = selected
    if len(joints)==1 and not hip_ankle:
        joint = next(iter(joints))
        candidates = [ch for ch in NAMES if ch.startswith(joint+"_")]
        terms = {"rotation":r"rotat|turning", "flexion":r"flexion|extension|bend|straighten",
                 "abduction":r"abduct|adduct|varus|valgus|sideways", "obliquity":r"obliqu|sideways",
                 "tilt":r"\btilt\b"}
        matched = [ch for ch in candidates if ch.split("_",1)[1] in terms and re.search(terms[ch.split("_",1)[1]],q)]
        if len(matched)==1: motion=matched[0]
        elif len(candidates)==1: motion=candidates[0]
        elif selected not in candidates or len(matched)>1:
            return scope("Which "+joint+" movement do you mean? Choose it in the motion selector or include its full name.")
    channel = CHANNELS[motion][0]
    metric = store.measurements[rid].set_index("channel").loc[motion]
    directions = store.cfg["interpretation"]["verified_direction_conventions"][motion]
    guide = graph_guide(motion, directions)
    percentages = re.findall(r"(?<![\w.])([+-]?\d+(?:\.\d+)?)\s*(?:%|percent\b)", question.lower().replace("−", "-"))
    asks_about_axis = re.search(r"\b(axis|axes|higher line|lower line|rising line|falling line|read (this |the |my )?graph)\b", q)
    if asks_about_axis or (percentages and "mean" in q and not re.search(r"angle|bend|offset|range",q)):
        return reply("How to read this graph",[CYCLE_GUIDE, guide,
                     "The vertical scale is the recorded angle in degrees. A higher line describes the angle, not the quality of the walk."])
    if percentages and not condition:
        if (both or len(percentages) != 1 or not re.search(r"\b(at|when)\b",q)
                or not (joints or re.search(r"\b(angle|line|curve|reading|graph|value|movement)\b",q))):
            return scope("To read one recorded angle, select a walk and ask for its angle at one percentage of the cycle.")
        point = float(percentages[0])
        if not point.is_integer() or not 0 <= point <= 100:
            return scope("The graph contains recorded angles at whole percentages from 0% to 100%. Choose one of those points.")
        value = store.arrays["curves"][store.positions[rid], NAMES.index(motion), int(point)]
        if not math.isfinite(value):
            return scope("The recorded angle is unavailable at that point.")
        return reply(channel+" · "+side+" walk",[
            f"At {point:g}% of this cycle, the recorded angle was {directional(value, directions)}.", guide])
    if (not condition and re.search(r"\d\s*(degrees?\b|°)",q)):
        past_bend = re.fullmatch(r"\s*did (?:my |the |this )?(?:left |right )?(?:hip|knee) bend (?:past|beyond) (\d+(?:\.\d+)?)\s*(?:degrees?|°)\s*[?.!]*\s*",q)
        if past_bend and motion in ("hip_flexion","knee_flexion") and math.isfinite(metric["max_deg"]):
            maximum = metric["max_deg"]
            verdict = "Yes." if maximum > float(past_bend[1]) else "No."
            return reply(channel+" · "+side+" walk",[f"{verdict} The greatest recorded bend anywhere in this cycle was {degrees(maximum)}."])
        return scope("Please name the movement and whether you mean the whole cycle, a marked phase or an angle at one percentage.")
    fields = [k for k,p in METRIC_TERMS.items() if re.search(p,q)]
    rows = store.corridor(rid,motion)
    named = [r for r in rows if r["phase"].lower().replace("-"," ") in q]
    phase_question = named or re.search(r"\b(corridor|phase (range|angle)|reference range)\b",q)
    if both and phase_question:
        return scope("The phase table shows both walks side by side. For the exact reading here, select one walk and name the phase.")
    if both:
        pair = store.assessment(record.participant)["comparison"].get(motion)
        if not pair: return reply(channel,["There is no same-day comparison for these two walks."])
        return reply("Comparing the two walks",[compare_walks(motion,pair),DEFINITIONS["rms_difference_deg"].replace("Curve difference","This calculation")])
    if phase_question:
        if named:
            readings = [f"At {row['phase']} ({row['pct']:g}% of the {side} walk), the angle was {row['reading']}. "
                        f"The report range is {row['range']}. This reading is {row['position'].lower()}." for row in named]
            return reply(channel+" · marked angles",readings+[f"The BeyondGait reference table is on page {named[0]['page']}."])
        return reply("Reference ranges at marked points",["Each phase has a printed range of angles for this movement.",
            f"The phase comparison table for {channel.lower()} shows all eight readings for the {side} walk alongside those limits.",
            "A value outside a range describes that marked point and does not establish a diagnosis."])
    if fields:
        return reply(channel+" · "+side+" walk",[DEFINITIONS[k]+" "+metric_example(k,metric,motion) for k in fields],
                     ["BAKER2009"] if not "mean_offset_deg" in fields else ["IOSA2014"])
    if condition:
        rules=store.interpretations[rid]["source_rule_results"]
        if hip_ankle: rules=[r for r in rules if r["rule_id"]=="myogait_hip_ankle_combination"]
        else:
            rules=[r for r in rules if motion in r["required_channels"]]
            if "early" in q and motion=="ankle_dorsiflexion":rules=[r for r in rules if r["rule_id"]=="myogait_nonpositive_early_ankle"]
            if "late" in q and motion=="knee_flexion":rules=[r for r in rules if r["rule_id"]=="myogait_late_knee_flexion"]
        if not rules:return reply(channel,["There is no dedicated pattern check for this movement. You can still compare its angles at all eight marks."])
        parts=[]
        for r in rules:
            status={"matched":"Seen in this walk.","not_matched":"This combination was not seen." if len(r["required_channels"])==2 else "This pattern was not seen.",
                    "not_evaluated":"This pattern could not be checked."}[r["status"]]
            parts.extend([CHECK_GUIDES[r["rule_id"]],rule_description(r),status])
        return reply(("Hip and ankle" if hip_ankle else channel)+" · movement checks",parts+[METHOD_NOTE],["MYOGAIT_RULES"])
    if re.fullmatch(r"(what (does|do) (my |the |this )?([a-z ]+ )?(measurement|measurements|angles?|graph|curve) (show|mean)|explain (this|my|the) (measurement|graph|motion|walk))\s*[?!.]*",q.strip()):
        return reply(channel+" · "+side+" walk",[CYCLE_GUIDE,guide]+[metric_example(k,metric,motion) for k in DEFINITIONS],["BAKER2009","IOSA2014"])
    if re.search(r"\b(review|summari[sz]e|summary|findings?|observations?)\b",q) and (
            re.search(r"\b(walk|assessment|recorded|movement|graph|gait|hip|knee|ankle|pelvis|pelvic)\b",q)
            or q.strip(" ?.!" ) in {"summary","my findings","findings","show findings"}):
        return None  # Stage 5 selects verified report cards; their presentation is localized below.
    return scope("I can explain range of motion, offset, curve differences, recorded patterns and phase comparisons. Try “What does offset mean?” or “Which pattern was seen?”")
