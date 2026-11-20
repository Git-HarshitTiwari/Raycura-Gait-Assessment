"""Regression tests for the prepared latest-assessment input contract."""
from pathlib import Path
import json
import shutil

import numpy as np
import pandas as pd
import pytest

from raycura.config import CHANNELS, COMPANY_COLUMNS, NAMES, ROOT
from raycura.gait_dataset import load_dataset
from raycura.analysis_utils import sha256

PREPARED = ROOT / "CSV's Folder"
COMBINED = Path("05 - Combined Dataset")
BASELINES = Path("06 - Normative Baselines")
AUDIT = Path("07 - Documentation and Audit")


@pytest.fixture(scope="module")
def prepared_config():
    if not (PREPARED / COMBINED / "Assessment Index.csv").is_file():
        pytest.skip("Organized latest-208 input package unavailable")
    return {
        "dataset_protocol": "prepared_latest208", "prepared_data": str(PREPARED),
        "original_data": str(ROOT / "unused-legacy-input"),
        "additional_data": str(ROOT / "unused-additional-input"),
    }


@pytest.fixture(scope="module")
def prepared(prepared_config):
    return load_dataset(prepared_config, None)


@pytest.fixture
def editable_package(tmp_path, prepared_config):
    package = tmp_path / "prepared-inputs"
    # Category exports are views, not additional tables to concatenate.
    for folder in (COMBINED, BASELINES, AUDIT):
        shutil.copytree(PREPARED / folder, package / folder)
    return package, dict(prepared_config, prepared_data=str(package))


def rewrite_csv(package, relative_path, change, refresh_integrity=True):
    path = package / relative_path
    table = pd.read_csv(path)
    changed = change(table)
    (table if changed is None else changed).to_csv(path, index=False)
    if not refresh_integrity:
        return
    # Update copied checksums so semantic validation is tested independently.
    mapping_path = package / AUDIT / "Filename Map.csv"
    mapping = pd.read_csv(mapping_path)
    match = mapping["Friendly organized path"].eq(relative_path.as_posix())
    assert match.sum() == 1
    technical = mapping.loc[match, "Original prepared ZIP filename"].iloc[0]
    digest = sha256(path)
    mapping.loc[match, "Original SHA256"] = digest
    mapping.to_csv(mapping_path, index=False)
    manifest_path = package / AUDIT / "Original Codex Source Manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    manifest["outputs"][technical] = {"sha256": digest, "bytes": path.stat().st_size}
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")


def test_inventory_and_latest_reference_membership(prepared):
    records = prepared.records
    assert len(records) == 208 and records.participant.nunique() == 104
    assert records.groupby("participant").side.nunique().eq(2).all()
    assert not records.duplicated(["participant", "side"]).any()
    assert records.reference_participant.sum() == 46
    assert records.loc[records.reference_participant, "participant"].nunique() == 23
    assert records.reference_original.sum() == 37
    assert records.flatfoot_observational.sum() == 34
    assert records.loc[records.cohort.eq("challenge"), "participant"].nunique() == 11
    assert records.cohort.eq("challenge").sum() == 22
    assert len(prepared.phases) == 208
    assert prepared.curves.shape == (208, 10, 101)
    assert np.isfinite(prepared.curves).all()


def test_angles_preserved_for_every_channel(prepared):
    source = pd.read_csv(PREPARED / COMBINED / "All Waveforms.csv", float_precision="round_trip")
    columns = {str(column).lower(): column for column in source}
    raw_columns = [columns[definition[1][0]] for definition in CHANNELS.values()]
    for index, record in prepared.records.iterrows():
        raw = source.loc[source.record_id.eq(record.record_id)].sort_values("gait_percentage")
        assert len(raw) == 101
        np.testing.assert_array_equal(raw.gait_percentage.to_numpy(), np.arange(101))
        np.testing.assert_array_equal(prepared.curves[index], raw[raw_columns].to_numpy(float).T)


def test_phase_times_and_anatomy_preserved(prepared):
    assert prepared.phase_rows is not None and prepared.anatomy is not None
    phases = pd.read_csv(PREPARED / COMBINED / "All Phases.csv", float_precision="round_trip")
    stored = prepared.phase_rows.sort_values(["record_id", "phase"])
    original = phases.sort_values(["record_id", "phase"])
    assert len(stored) == 1664
    for column in ["record_id", "phase", "FrameTime", "percentage"]:
        np.testing.assert_array_equal(stored[column].to_numpy(), original[column].to_numpy())
    anatomy = pd.read_csv(PREPARED / AUDIT / "Anatomical Definitions.csv")
    assert len(prepared.anatomy) == 10
    for column in anatomy.columns:
        np.testing.assert_array_equal(prepared.anatomy[column].to_numpy(), anatomy[column].to_numpy())


def test_baselines_match_both_sides_and_latest_reference(prepared):
    assert set(prepared.baseline_by_side) == {"left", "right"}
    baseline = pd.read_csv(PREPARED / BASELINES / "All 10 Normative Baselines.csv", float_precision="round_trip")
    baseline.columns = baseline.columns.str.lower()
    baseline["side"] = baseline.side.str.lower()
    extra = {"pelvic_tilt": "exploratory_pelvic_tilt_mean_deg",
             "hip_rotation": "exploratory_hip_rotation_mean_deg",
             "knee_rotation": "exploratory_knee_rotation_mean_deg"}
    for side in ["left", "right"]:
        stored = prepared.baseline_by_side[side]
        assert stored.shape == (10, 101)
        table = baseline.loc[baseline.side.eq(side)].sort_values("gait_percentage")
        for channel in NAMES:
            column = COMPANY_COLUMNS.get(channel, extra.get(channel))
            np.testing.assert_array_equal(stored[NAMES.index(channel)], table[column].to_numpy())
        mask = prepared.records.reference_participant & prepared.records.side.eq(side)
        assert mask.sum() == 23
        for channel in extra:
            index = NAMES.index(channel)
            expected = prepared.curves[mask.to_numpy(), index].mean(axis=0)
            np.testing.assert_allclose(stored[index], expected, atol=1e-12, rtol=0)


def test_changed_source_rejected_before_semantic_use(editable_package):
    package, config = editable_package
    rewrite_csv(package, COMBINED / "All Waveforms.csv",
                lambda data: data.assign(pelvicTiltArr=data.pelvicTiltArr + 1),
                refresh_integrity=False)
    with pytest.raises(ValueError):
        load_dataset(config, None)


@pytest.mark.parametrize("case", [
    "wrong_native_identity", "wrong_token", "truncated_grid", "duplicate_waveform_row",
    "missing_phase", "phase_identity_mismatch", "category_conflict", "missing_channel",
    "nonfinite_angle", "invalid_side", "reference_corruption", "nonfinite_company_baseline",
])
def test_contract_rejects_inconsistent_content(editable_package, case):
    package, config = editable_package
    relative = COMBINED / "All Waveforms.csv"

    def change(data):
        if case == "wrong_native_identity":
            data.loc[0, "patient_id"] = "incorrect-native-id"
        elif case == "wrong_token":
            data.loc[0, "record_id"] = "R-0000000000000000"
        elif case == "truncated_grid":
            return data.iloc[1:]
        elif case == "duplicate_waveform_row":
            return pd.concat([data, data.iloc[[0]]], ignore_index=True)
        elif case == "missing_phase":
            return data.iloc[1:]
        elif case == "phase_identity_mismatch":
            data.loc[0, "participant"] = "S-0000000000000000"
        elif case == "category_conflict":
            data.loc[0, "category"] = "other_unclassified"
        elif case == "missing_channel":
            return data.drop(columns="pelvicTiltArr")
        elif case == "nonfinite_angle":
            data.loc[0, "pelvicTiltArr"] = np.nan
        elif case == "invalid_side":
            data.loc[0, "side"] = "unknown"
        elif case == "reference_corruption":
            data.loc[0, "main_final_avg_kF"] += 1
        elif case == "nonfinite_company_baseline":
            data.loc[data.gait_percentage.eq(0), "main_final_avg_kF"] = np.inf
        return data

    if case in ["missing_phase", "phase_identity_mismatch"]:
        relative = COMBINED / "All Phases.csv"
    elif case in ["reference_corruption", "nonfinite_company_baseline"]:
        relative = BASELINES / "All 10 Normative Baselines.csv"
    rewrite_csv(package, relative, change)
    with pytest.raises((ValueError, KeyError)):
        load_dataset(config, None)


def test_category_exports_not_concatenated(editable_package, prepared):
    package, config = editable_package
    folder = package / "01 - Healthy People"
    folder.mkdir()
    (folder / "Healthy Waveforms.csv").write_text("unexpected_column\nextra-copy\n")
    result = load_dataset(config, None)
    assert len(result.records) == 208
    np.testing.assert_array_equal(result.curves, prepared.curves)


@pytest.mark.parametrize("table", [
    COMBINED / "All Waveforms.csv", BASELINES / "All 10 Normative Baselines.csv",
    BASELINES / "3 Recalculated Baselines.csv",
])
def test_rejects_fractional_sample_on_prepared_integer_grid(editable_package, table):
    package, config = editable_package

    def move_one_coordinate(data):
        data["gait_percentage"] = data.gait_percentage.astype(float)
        data.loc[0, "gait_percentage"] += 0.000000005

    rewrite_csv(package, table, move_one_coordinate)
    with pytest.raises(ValueError, match="grid"):
        load_dataset(config)
