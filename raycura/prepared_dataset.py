"""Fail-closed adapter for the approved, immutable latest-208 combined dataset.

Prepared record/participant IDs are authoritative; their integrity is checked
against the frozen package manifest and cross-file native identity keys. No
private key regeneration, source merging, interpolation or sign conversion occurs.
"""
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

from .config import NAMES, CHANNELS, COMPANY_COLUMNS, PHASES
from .gait_dataset import Dataset, KEY, canonicalize
from .analysis_utils import sha256

EXPECTED = {
    "healthy_comparison": (23, 46),
    "flatfoot_observational": (17, 34),
    "patient_source": (11, 22),
    "other_unclassified": (53, 106),
}
EXTRA = ("pelvic_tilt", "hip_rotation", "knee_rotation")
# The prepared export defines the sample coordinates exactly, in percentage points.
EXPORTED_CYCLE_PERCENT = tuple(range(101))
REQUIRED = (
    "waveforms_latest_208.csv", "phases_latest_208.csv",
    "assessment_index_latest_208.csv", "normative_baselines_10_by_side.csv",
    "normative_baselines_3_latest_healthy_by_side.csv", "anatomy_definitions.csv",
    "superseded_23_assessments.csv", "duplicate_exports_46.csv",
)

def require(ok, message):
    if not bool(ok):
        raise ValueError(message)

def read_csv(path):
    return pd.read_csv(path, keep_default_na=False, float_precision="round_trip",
                       dtype={"patient_id": str, "record_id": str, "participant": str})

def boolean(series):
    text = series.astype(str).str.strip().str.lower()
    require(text.isin(["true", "false"]).all(), f"Invalid Boolean field {series.name}")
    return text.eq("true")

def verified_paths(root):
    root = Path(root).resolve()
    manifest_path = root / "07 - Documentation and Audit" / "Original Codex Source Manifest.json"
    mapping_path = root / "07 - Documentation and Audit" / "Filename Map.csv"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    mapping = pd.read_csv(mapping_path, keep_default_na=False)
    required_mapping = mapping[mapping["Original prepared ZIP filename"].isin(REQUIRED)]
    require(not required_mapping["Original prepared ZIP filename"].duplicated().any(), "Duplicate filename-map entries")
    by_name = required_mapping.set_index("Original prepared ZIP filename")
    paths, hashes = {}, {str(manifest_path): sha256(manifest_path), str(mapping_path): sha256(mapping_path)}
    for name in REQUIRED:
        require(name in by_name.index and name in manifest["outputs"], f"Missing package source: {name}")
        entry = by_name.loc[name]
        path = (root / entry["Friendly organized path"]).resolve()
        require(path.is_relative_to(root), "Package path escapes the prepared dataset")
        expected = manifest["outputs"][name]["sha256"]
        require(entry["Original SHA256"] == expected, f"Manifest/map checksum mismatch: {name}")
        require(path.is_file() and sha256(path) == expected, f"Prepared source checksum mismatch: {name}")
        paths[name] = path
        hashes[str(path)] = expected
    return paths, hashes, manifest

def load_prepared_dataset(cfg, identities=None):
    paths, hashes, manifest = verified_paths(cfg["prepared_data"])
    original_index = read_csv(paths["assessment_index_latest_208.csv"])
    index = canonicalize(original_index)
    wave = canonicalize(read_csv(paths["waveforms_latest_208.csv"]))
    phase_rows = read_csv(paths["phases_latest_208.csv"])
    phase = canonicalize(phase_rows)
    require(len(index) == 208 and len(wave) == 21008 and len(phase) == 1664,
            "Expected 208 assessments, 21008 waveform rows and 1664 phase rows")
    required_meta = ["record_id", "participant", "category"] + KEY
    for table in (index, wave, phase):
        require(all(c in table for c in required_meta), "Missing identity/category columns")
        require(table[KEY].ne("").all().all(), "Missing native identity, side or timestamp")
        require(table._side.isin(["left", "right"]).all(), "Invalid limb side")
        require(table.category.isin(EXPECTED).all(), "Unknown participant category")
        require(table.record_id.str.fullmatch(r"R-[0-9a-f]{16}").all(), "Invalid prepared record IDs")
        require(table.participant.str.fullmatch(r"S-[0-9a-f]{16}").all(), "Invalid prepared participant IDs")
    require(index.record_id.is_unique and not index.duplicated(KEY).any(), "Duplicate assessment identity")
    require(not index.duplicated(["participant", "_side"]).any(), "Multiple selected captures per participant/side")
    require(index.participant.nunique() == 104 and index._side.value_counts().to_dict() == {"left": 104, "right": 104},
            "Expected 104 participants and 104 recordings on each side")
    require(index.groupby("participant").size().eq(2).all(), "Each participant must have two selected limbs")
    require(index.groupby("participant").category.nunique().eq(1).all(), "Participant categories conflict")
    require(index.groupby("participant")["_id"].nunique().eq(1).all()
            and index.groupby("participant")["_name"].nunique().eq(1).all(), "Participant/native identity mismatch")
    require(index.groupby(["_id", "_name"]).participant.nunique().eq(1).all(), "Native identity split across participants")
    for category, (people, captures) in EXPECTED.items():
        group = index[index.category.eq(category)]
        require(len(group) == captures and group.participant.nunique() == people, f"Incorrect category count: {category}")
    for flag, category in [("normal_comparison_member", "healthy_comparison"),
                           ("flatfoot_observational", "flatfoot_observational"),
                           ("patient_source_member", "patient_source")]:
        for table in (index, wave):
            require(flag in table and boolean(table[flag]).equals(table.category.eq(category)),
                    f"Conflicting category membership: {flag}")
    require("selected_capture_in_original_normal_export" in index, "Missing original-capture provenance")
    original_flag = boolean(index.selected_capture_in_original_normal_export)
    require(int(original_flag.sum()) == 37 and not (original_flag & ~index.category.eq("healthy_comparison")).any(),
            "Expected 37 retained original healthy capture keys and nine replacement captures")
    index["_reference_original"] = original_flag
    keyed = index.set_index("record_id", drop=False)
    expected_ids = set(keyed.index)
    for table in (wave, phase):
        require(set(table.record_id) == expected_ids, "Waveform/phase/index record mismatch")
        for rid, g in table.groupby("record_id", sort=False):
            item = keyed.loc[rid]
            for col in ["participant", "category", "gender"] + KEY:
                require(g[col].eq(item[col]).all(), f"Cross-file identity/category mismatch: {rid}:{col}")
    require(all(ch in wave for ch in NAMES), "Missing required motion channel")
    records, curves, phases, provenance = [], [], {}, []
    for rid, item in keyed.sort_index().iterrows():
        group = wave[wave.record_id.eq(rid)].sort_values("gait_percentage", kind="stable")
        grid = pd.to_numeric(group.gait_percentage, errors="coerce").to_numpy(float)
        require(np.array_equal(grid, EXPORTED_CYCLE_PERCENT), f"Invalid 101-point grid: {rid}")
        values = group[NAMES].to_numpy(float).T
        require(values.shape == (10, 101) and np.isfinite(values).all(), f"Nonfinite or missing motion values: {rid}")
        p = phase[phase.record_id.eq(rid)].sort_values("phase", kind="stable")
        require(p.phase.tolist() == list("ABCDEFGH"), f"Incomplete or duplicated phase labels: {rid}")
        require(p.phase_name.tolist() == list(PHASES.values()), f"Historical phase-name mismatch: {rid}")
        pv = pd.to_numeric(p.percentage, errors="coerce").to_numpy(float)
        ft = pd.to_numeric(p.frametime, errors="coerce").to_numpy(float)
        require(np.isfinite(pv).all() and pv[0] == 0 and pv[-1] == 100 and (np.diff(pv) > 0).all(),
                f"Invalid historical phase percentages: {rid}")
        require(np.isfinite(ft).all() and ft[0] == 0 and (np.diff(ft) > 0).all(), f"Invalid historical FrameTime: {rid}")
        phases[rid] = pv.tolist()
        healthy = item.category == "healthy_comparison"
        flat = item.category == "flatfoot_observational"
        records.append(dict(record_id=rid, participant=item.participant, side=item._side,
            assessment_time=item._time, patient_id=item.patient_id, name=item["name"], gender=item.gender,
            category=item.category, source_exports=item.waveform_source_exports,
            assessment_time_source=item.assessment_time,
            phase_source_exports=item.phase_source_exports,
            normal_comparison_member=healthy, patient_source_member=item.category == "patient_source",
            selected_capture_in_original_normal_export=bool(item["_reference_original"]),
            cohort="challenge" if item.category == "patient_source" else "development",
            reference_original=bool(item["_reference_original"]), reference_participant=healthy,
            flatfoot_observational=flat, in_flatfoot_subset=flat,
            historical_marks_available=True, historical_marks_verification="unverified_manual_annotations",
            source_gait_label=item.source_gait_label, source_gait_label_status=item.source_gait_label_status,
            conflicting_channels="", dataset_protocol="prepared_latest208"))
        curves.append(values)
        provenance.extend(dict(record_id=rid, channel=ch, source=str(paths["waveforms_latest_208.csv"]),
                               source_exports=item.waveform_source_exports, finite_samples=101) for ch in NAMES)
    frame = pd.DataFrame(records)
    for rid in frame.loc[frame.category.eq("healthy_comparison"), "record_id"]:
        require(bool(keyed.loc[rid, "normal_comparison_member"]), "Healthy membership missing")
    duplicates = read_csv(paths["duplicate_exports_46.csv"])
    excluded = read_csv(paths["superseded_23_assessments.csv"])
    require(len(duplicates) == 46 and duplicates.restored_samples.sum() == 202, "Incorrect duplicate/restoration audit")
    require(len(excluded) == 23 and excluded.record_id.is_unique and not set(excluded.record_id) & expected_ids,
            "Superseded assessment present in primary data or invalid exclusion audit")
    require(set(excluded.selected_record_id) <= expected_ids, "Superseded replacement not selected")
    for _, item in excluded.iterrows():
        selected = keyed.loc[item.selected_record_id]
        require(item.participant == selected.participant and item.side.lower() == selected._side
                and pd.Timestamp(item.assessment_time) < pd.Timestamp(selected._time), "Invalid superseded replacement link")
    anatomy = read_csv(paths["anatomy_definitions.csv"])
    source_to_channel = {alias: ch for ch, (_, aliases) in CHANNELS.items() for alias in aliases}
    require(len(anatomy) == 10 and anatomy.source_channel.is_unique, "Expected ten unique anatomical definitions")
    require({source_to_channel.get(c.lower()) for c in anatomy.source_channel} == set(NAMES), "Anatomical channel mapping incomplete")
    ten = read_csv(paths["normative_baselines_10_by_side.csv"])
    three = read_csv(paths["normative_baselines_3_latest_healthy_by_side.csv"])
    # The immutable, verified package is authoritative. Runtime ingestion does
    # not require the older source directories or concatenate their exports.
    original = ten[ten.side.str.lower().eq("left")].sort_values("gait_percentage").copy()
    original.columns = [str(c).lower() for c in original]
    require(np.array_equal(original.gait_percentage, EXPORTED_CYCLE_PERCENT), "Company baseline grid mismatch")
    company = np.full((10, 101), np.nan)
    for ch, col in COMPANY_COLUMNS.items():
        require(col in original, f"Missing original company baseline: {col}")
        require(np.isfinite(original[col].to_numpy(float)).all(), f"Nonfinite company baseline: {ch}")
        company[NAMES.index(ch)] = original[col].to_numpy(float)
    require(len(ten) == 202 and len(three) == 202, "Expected 202 side-specific baseline rows")
    baseline_by_side = {}
    arr = np.asarray(curves)
    for side in ("left", "right"):
        full = ten[ten.side.str.lower().eq(side)].sort_values("gait_percentage")
        extra = three[three.side.str.lower().eq(side)].sort_values("gait_percentage")
        require(np.array_equal(full.gait_percentage, EXPORTED_CYCLE_PERCENT)
                and np.array_equal(extra.gait_percentage, EXPORTED_CYCLE_PERCENT),
                "Invalid side-specific baseline grid")
        require(extra.n_participants.eq(23).all() and extra.n_assessments.eq(23).all(), "Incorrect three-baseline construction population")
        full.columns = [str(c).lower() for c in full]
        baseline = company.copy()
        for ch, col in COMPANY_COLUMNS.items():
            require(np.array_equal(full[col].to_numpy(float), company[NAMES.index(ch)]), f"Company baseline changed: {ch}")
        mask = frame.reference_participant & frame.side.eq(side)
        require(mask.sum() == 23, "Expected 23 latest normal-comparison curves per side")
        for ch in EXTRA:
            c = NAMES.index(ch)
            values = extra[ch + "_mean_deg"].to_numpy(float)
            require(np.array_equal(values, full["exploratory_" + ch + "_mean_deg"].to_numpy(float)), "Three/ten baseline mismatch")
            require(np.isfinite(values).all() and np.allclose(values, arr[mask.to_numpy(), c].mean(axis=0), atol=1e-12, rtol=0),
                    f"Baseline does not match latest healthy recordings: {side}:{ch}")
            baseline[c] = values
        baseline_by_side[side] = baseline
    return Dataset(frame, arr, phases, pd.DataFrame(provenance), duplicates, excluded,
        pd.DataFrame({"record_id": frame.loc[frame.in_flatfoot_subset, "record_id"], "matched_existing": True}),
        hashes, company, np.full((10, 101), np.nan), baseline_by_side=baseline_by_side,
        anatomy=anatomy, phase_rows=phase_rows, dataset_protocol="prepared_latest208", input_manifest=manifest)
