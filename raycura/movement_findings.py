"""Generate descriptive motion observations and evidence-gated examination cards."""
import numpy as np
from .config import NAMES, CHANNELS

def card(id,title,channels,observation,interpretation,next_check,sources,kind="movement",**extra):
    return dict(id=id,title=title,channels=channels,observation=observation,
        interpretation=interpretation,next_check=next_check,source_ids=sources,
        kind=kind,clinical_status="undetermined",**extra)

def muscle_rules(curves, reference, states, cfg, record_id):
    """Anatomical predicates use only independently documented conventions.

    Synthetic unit tests exercise these rules. Default records have no such
    documentation, so anatomical hypotheses are withheld rather than guessed.
    """
    icfg=cfg["interpretation"]
    signs=icfg["verified_direction_conventions"]
    outcomes=[]
    patterns=[("hip_flexor_pattern",["knee_flexion","hip_flexion","pelvic_tilt"]),
              ("hamstring_pattern",["knee_flexion","pelvic_tilt","ankle_dorsiflexion"])]
    for rule,chs in patterns:
        reasons=[]
        if any(states[NAMES.index(ch)]!="usable" for ch in chs): reasons.append("required_channel_not_usable")
        for ch in chs:
            convention=signs.get(ch,{})
            if convention.get("positive_direction") not in {"knee_flexion":"flexion","hip_flexion":"flexion","pelvic_tilt":"anterior","ankle_dorsiflexion":"dorsiflexion"}.values():
                reasons.append(f"direction_unverified:{ch}")
            expected={"knee_flexion":"flexion","hip_flexion":"flexion","pelvic_tilt":"anterior","ankle_dorsiflexion":"dorsiflexion"}[ch]
            if convention.get("positive_direction")!=expected or convention.get("multiplier") not in (-1,1) or not convention.get("evidence") or not convention.get("anatomical_zero_verified"):
                reasons.append(f"documented_convention_required:{ch}")
        if any(not np.isfinite(reference[NAMES.index(ch)]).all() for ch in chs): reasons.append("required_reference_unavailable")
        stance=icfg.get("verified_stance_by_record",{}).get(record_id)
        if rule=="hamstring_pattern":
            if not icfg["verified_phase_protocol"] or not stance or not stance.get("evidence"):
                reasons.append("independently_verified_support_interval_required")
        if reasons:
            outcomes.append(dict(rule=rule,status="withheld",reasons=sorted(set(reasons)),card=None)); continue
        def value(ch): return curves[NAMES.index(ch)]*signs[ch]["multiplier"]
        def diff(ch): return (curves[NAMES.index(ch)]-reference[NAMES.index(ch)])*signs[ch]["multiplier"]
        # Sustained flexed knee positioning, not merely reduced ROM. 90% coverage
        # and angular cutoffs are conservative operational choices, not diagnoses.
        k=(value("knee_flexion")>5)&(diff("knee_flexion")>5)
        if rule=="hip_flexor_pattern":
            co=k & (diff("hip_flexion")>5) & (diff("pelvic_tilt")>3)
            complete=bool(np.mean(k)>=.9 and np.mean(co)>=.8)
            desc="Sustained flexed knee positioning co-occurs with increased hip flexion and anterior pelvic tilt relative to the selected references."
            lead="Consider examining hip-extension mobility and iliopsoas-related flexibility to clarify this complete movement combination. This does not establish an iliopsoas contracture."
            follow="Compare active and passive hip extension with pelvic stabilization, and review other causes of sustained flexed posture."
        else:
            start,end=stance.get("start_pct"),stance.get("end_pct")
            if not isinstance(start,(float,int)) or not isinstance(end,(float,int)) or not 0<=start<end<=100:
                outcomes.append(dict(rule=rule,status="withheld",reasons=["invalid_verified_support_interval"],card=None)); continue
            mask=(np.arange(101)>=start)&(np.arange(101)<=end)
            co=k & (diff("pelvic_tilt")< -3) & (diff("ankle_dorsiflexion")>5)
            complete=bool(np.mean(k)>=.9 and np.mean(co[mask])>=.8)
            desc="Sustained flexed knee positioning co-occurs with posterior pelvic tilt and increased ankle dorsiflexion in a verified support interval."
            lead="Consider examining hamstring-related flexibility and knee-extension mobility. The experimental pattern does not prove hamstring impairment in this person."
            follow="Review knee extension with controlled hip position, pelvic posture, and alternative joint or acquisition explanations."
        c=card(rule,"Conditional muscle-function examination",chs,desc,lead,follow,["ATTias2019"],kind="muscle_function",
            alternatives=["Other joint restrictions or movement strategies", "Reference or acquisition differences"],
            evidence_basis="experimental_restriction_study_not_patient_diagnosis") if complete else None
        outcomes.append(dict(rule=rule,status="matched" if complete else "not_matched",reasons=[] if complete else ["complete_cooccurring_pattern_absent"],card=c))
    return outcomes

def interpret_record(record, curves, reference, states, metric_rows, cfg):
    rows={r["channel"]:r for r in metric_rows}
    cards=[]
    d=cfg["descriptive_rules"]
    for c,ch in enumerate(NAMES):
        r=rows[ch]
        if states[c]!="usable" or not np.isfinite(reference[c]).all(): continue
        title=CHANNELS[ch][0]
        if (r.get("offset_energy_fraction",0)>=d["offset_energy_fraction"]
                and abs(r.get("mean_offset_deg",0))>=d["minimum_offset_deg"]
                and r.get("linear_r2",0)>=.9 and .85<=r.get("linear_slope",0)<=1.15):
            cards.append(card("offset_"+ch,"Offset dominates the difference",[ch],
                f"{title} averaged {r['mean_offset_deg']:+.2f}° relative to its selected reference curve.",
                "The waveform is largely shifted while retaining a similar scale and shape. This does not establish reduced joint movement or an affected muscle.",
                "Check anatomical zero, sensor alignment and posture; compare an eligible same-side repeat before interpreting the absolute angle.",
                ["IOSA2014","ISB2024"],family="offset_dominated",threshold_basis="engineering_review_rule"))
        med=r.get("cohort_median_individual_rom_deg",np.nan)
        if (np.isfinite(med) and med>0 and r["rom_deg"] < med*d["reduced_excursion_ratio"]
                and med-r["rom_deg"]>=d["minimum_excursion_difference_deg"]
                and 0<r.get("linear_slope",0)<.85 and r.get("linear_r2",0)>=.5):
            cards.append(card("excursion_"+ch,"Smaller recorded excursion with similar shape",[ch],
                f"{title} spanned {r['rom_deg']:.2f}°. The median individual span among the same-side comparison recordings was {med:.2f}°.",
                "The reduced movement span is supported by the waveform fit as well as its extrema. Passive stiffness, weakness, symptoms and cause remain unknown.",
                "Check whether the reduced span repeats under comparable walking conditions; compare active and passive joint mobility if relevant.",
                ["IOSA2014"],family="reduced_excursion",threshold_basis="engineering_review_rule"))
    anatomical=muscle_rules(curves,reference,states,cfg,record["record_id"])
    cards.extend(x["card"] for x in anatomical if x["card"] is not None)
    return dict(record_id=record["record_id"],cards=cards,muscle_rules=anatomical,
                muscle_suggestion_count=sum(c["kind"]=="muscle_function" for c in cards),
                clinical_status="undetermined",rule_library_clinician_reviewed=False)
