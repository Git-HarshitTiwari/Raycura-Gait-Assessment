"""Transparent descriptive metrics; no clinical decision thresholds."""
import numpy as np
import pandas as pd
from .config import NAMES, COMPANY_COLUMNS
from .analysis_utils import rms

# Saved separately from the user-facing measurement table. The interpreter and
# adapter use the in-memory values before export.
INTERNAL_METRICS = (
    "largest_adjacent_change_deg", "centered_rms_difference_deg", "linear_slope",
    "linear_intercept_deg", "linear_r2", "offset_energy_fraction", "cohort_median_individual_rom_deg",
)

PRIMARY_LABELS = {
    "rom_deg": "Movement span (°)",
    "rms_difference_deg": "Overall curve difference (° RMS)",
    "mean_offset_deg": "Average angular shift (°)",
}

DETAIL_LABELS = {
    "min_deg": "Minimum recorded angle (°)",
    "max_deg": "Maximum recorded angle (°)",
    "reference_mean_curve_rom_deg": "Span of the selected reference curve (°)",
    "rom_difference_from_mean_curve_deg": "Recorded span minus selected reference span (°)",
    "largest_signed_difference_deg": "Recorded minus reference at the largest gap (°)",
    "largest_difference_grid_pct": "Unique location of largest gap (% of exported cycle)",
}

def quality(x, limits):
    x = np.asarray(x, float)
    if x.shape != (101,):
        return "unusable", ["invalid_sample_count"]
    if not np.isfinite(x).all():
        return "unusable", ["missing_or_nonfinite_samples"]
    flags = []
    if np.max(np.abs(x)) > limits["max_absolute_angle_deg"]:
        flags.append("absolute_angle_over_technical_review_limit")
    if np.ptp(x) > limits["max_excursion_deg"]:
        flags.append("excursion_over_technical_review_limit")
    if np.max(np.abs(np.diff(x))) > limits["max_adjacent_step_deg"]:
        flags.append("large_adjacent_sample_change")
    if np.ptp(x) <= limits["flat_tolerance_deg"]:
        flags.append("flat_channel")
    return ("suspect" if flags else "usable"), flags

def metrics(x, reference=None):
    """Calculate retained measurements in degrees on matching 101-point grids."""
    x = np.asarray(x, float)
    if x.shape != (101,) or not np.isfinite(x).all():
        return {}
    hi, lo = float(x.max()), float(x.min())
    result = dict(min_deg=lo, max_deg=hi, rom_deg=hi-lo,
        largest_adjacent_change_deg=float(np.max(np.abs(np.diff(x)))))
    if reference is None:
        return result
    r = np.asarray(reference, float)
    if r.shape != x.shape:
        raise ValueError("The reference must match the 101-point recorded curve.")
    if not np.isfinite(r).all():
        return result
    delta = x-r
    offset = float(delta.mean())
    ref_centered, centered = r-r.mean(), x-x.mean()
    var = float(np.dot(ref_centered, ref_centered))
    slope = float(np.dot(ref_centered, centered) / var) if var>1e-12 else np.nan
    intercept = float(x.mean()-slope*r.mean())
    residual = x-(intercept+slope*r)
    total = float(np.dot(centered,centered))
    r2 = float(1-np.dot(residual,residual)/total) if total>1e-12 and var>1e-12 else np.nan
    maxgap = int(np.argmax(np.abs(delta)))
    # Ties within numerical precision cannot identify a single cycle position.
    tied = np.isclose(np.abs(delta), abs(delta[maxgap]), rtol=0, atol=1e-10)
    signed_gap = float(delta[maxgap])
    if np.any(delta[tied] > 0) and np.any(delta[tied] < 0):
        signed_gap = np.nan
    error = float(rms(delta))
    result.update(reference_mean_curve_rom_deg=float(np.ptp(r)),
        rom_difference_from_mean_curve_deg=float(np.ptp(x)-np.ptp(r)),
        rms_difference_deg=error, mean_offset_deg=offset,
        centered_rms_difference_deg=float(rms(delta-offset)),
        linear_slope=slope, linear_intercept_deg=intercept, linear_r2=r2,
        offset_energy_fraction=float(offset**2/error**2) if error>1e-12 else 0.,
        largest_difference_grid_pct=maxgap if np.count_nonzero(tied)==1 else np.nan,
        largest_signed_difference_deg=signed_gap)
    return result

def assess_dataset(data, cfg):
    n = len(data.records)
    states = np.empty((n,10),dtype="U16")
    reasons = {}
    for i in range(n):
        for c,ch in enumerate(NAMES):
            states[i,c], reasons[i,c] = quality(data.curves[i,c], cfg["technical_quality"])
    prepared = data.dataset_protocol == "prepared_latest208"
    ref_base = data.records["reference_participant" if prepared else "reference_original"].to_numpy(bool)
    # The prepared loader verifies 23 healthy people per side. Both the API and
    # the batch export must reject a quality setting that removes a reference limb.
    if prepared and np.any(states[ref_base] != "usable"):
        raise ValueError("Prepared comparisons require 22 or 23 usable same-side healthy peers.")
    people = data.records.participant.to_numpy()
    sides = data.records.side.to_numpy()
    rows = []
    references = np.full_like(data.curves,np.nan)
    cohort_means = np.full_like(data.curves,np.nan)
    low, high = np.full_like(data.curves,np.nan), np.full_like(data.curves,np.nan)
    for i, record in data.records.iterrows():
        candidates = ref_base & (people!=record.participant) & (sides==record.side)
        for c,ch in enumerate(NAMES):
            usable_ref = candidates & (states[:,c]=="usable")
            vals = data.curves[usable_ref,c]
            if len(vals):
                cohort_means[i,c] = vals.mean(axis=0)
                low[i,c], high[i,c] = np.quantile(vals,[.05,.95],axis=0)
            company = ch in COMPANY_COLUMNS and np.isfinite(data.company[c]).all()
            approved = (data.baseline_by_side[record.side][c]
                        if prepared and data.baseline_by_side is not None else None)
            # Published means stay immutable. For a healthy participant's
            # evaluation the cohort comparator excludes that person's data.
            ref = (data.company[c] if company else
                   approved if prepared and not record.reference_participant else cohort_means[i,c])
            references[i,c] = ref
            reference_status = ("company_mean_numeric_comparison" if company else
                "exploratory_same_side_cohort_participant_excluded" if prepared and record.reference_participant else
                "approved_exploratory_same_side_mean" if prepared else
                "exploratory_same_side_cohort" if len(vals) else "unavailable")
            directions = cfg.get("interpretation", {}).get("verified_direction_conventions", {})
            item = dict(record_id=record.record_id, participant=record.participant, side=record.side,
                channel=ch, measurement_status=states[i,c], quality_flags=";".join(reasons[i,c]),
                reference_status=reference_status,
                anatomical_direction_status="company_documented" if ch in directions else "unverified",
                anatomical_zero_status="verified" if directions.get(ch, {}).get("anatomical_zero_verified") else "unverified",
                reference_participants=None if company else (23 if prepared and not record.reference_participant else
                    int(data.records.loc[usable_ref,"participant"].nunique())),
                reference_excludes_participant=None if company else True,
                reference_population_inclusion="unknown" if company else "participant_excluded" if record.reference_participant else "not_reference_member",
                cohort_reference_participants=int(data.records.loc[usable_ref,"participant"].nunique()),
                cohort_reference_excludes_participant=True, reference_is_normal_limit=False)
            item.update(metrics(data.curves[i,c],ref))
            if approved is not None:
                item.update(approved_baseline_population_inclusion="unknown" if company else
                        "includes_assessed_participant" if record.reference_participant else "not_reference_member",
                    approved_baseline_construction_participants=None if company else 23)
            if states[i,c]!="unusable" and len(vals):
                item["cohort_median_individual_rom_deg"] = float(np.median(np.ptp(vals, axis=1)))
            rows.append(item)
    return pd.DataFrame(rows), states, references, cohort_means, low, high

def compare_recordings(data, states):
    """All consecutive genuine same-side visits; only unambiguous same-date side pairs."""
    table = data.records.copy()
    table["_date"] = pd.to_datetime(table.assessment_time).dt.date
    pairs = []
    def append(a,b,kind):
        elapsed = abs((pd.Timestamp(b.assessment_time)-pd.Timestamp(a.assessment_time)).total_seconds())/60
        for c,ch in enumerate(NAMES):
            ok = states[a.name,c]=="usable" and states[b.name,c]=="usable"
            row = dict(participant=a.participant,first_record=a.record_id,second_record=b.record_id,
                comparison=kind,channel=ch,elapsed_minutes=elapsed,comparable_numeric=ok,
                acquisition_conditions_matched=False,independent_clinical_confirmation=False)
            if ok:
                x,y = data.curves[a.name,c],data.curves[b.name,c]
                row.update(first_rom_deg=float(np.ptp(x)),second_rom_deg=float(np.ptp(y)),
                    rom_difference_deg=float(np.ptp(y)-np.ptp(x)),rms_between_recordings_deg=float(rms(y-x)),
                    mean_offset_deg=float(np.mean(y-x)))
            pairs.append(row)
    for _,g in table.groupby(["participant","side"]):
        g=g.sort_values("assessment_time")
        for j in range(1,len(g)):
            append(g.iloc[j-1],g.iloc[j],"consecutive_same_side_recordings")
    for _,g in table.groupby(["participant","_date"]):
        if len(g)==2 and set(g.side)=={"left","right"}:
            append(g[g.side=="left"].iloc[0],g[g.side=="right"].iloc[0],"left_then_right_separate_walks")
    return pd.DataFrame(pairs)
