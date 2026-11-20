"""Integration regression tests; numerical expectations come from source arrays."""
import numpy as np
import pytest
from raycura.config import NAMES, COMPANY_COLUMNS
from raycura.gait_dataset import load_dataset
from raycura.gait_measurements import assess_dataset
from raycura.movement_findings import interpret_record

@pytest.fixture(scope="module")
def assessed208(approved_config):
    data = load_dataset(approved_config, None)
    return approved_config, data, assess_dataset(data, approved_config)

def test_reference_population_uses_latest_membership(assessed208):
    _, data, (rows, _, _, _, _, _) = assessed208
    assert data.records.reference_participant.sum() == 46
    assert data.records.reference_original.sum() == 37
    expected = data.records.set_index("record_id").reference_participant.map({True: 22, False: 23})
    assert rows.cohort_reference_participants.eq(rows.record_id.map(expected)).all()

def test_company_population_inclusion_is_unknown(assessed208):
    _, _, (rows, _, _, _, _, _) = assessed208
    company = rows[rows.channel.isin(COMPANY_COLUMNS)]
    assert len(company) == 1456
    assert company.reference_population_inclusion.eq("unknown").all()
    assert company.reference_excludes_participant.isna().all()
    assert company.reference_participants.isna().all()

def test_all_primary_references_match_side_and_self_exclusion(assessed208):
    _, data, (_, _, references, cohort, _, _) = assessed208
    for i, record in data.records.iterrows():
        mask = (data.records.reference_participant & data.records.side.eq(record.side)
                & data.records.participant.ne(record.participant))
        expected = data.curves[mask.to_numpy()].mean(axis=0)
        np.testing.assert_allclose(cohort[i], expected, atol=1e-12, rtol=0)
        for c, channel in enumerate(NAMES):
            primary = (data.company[c] if channel in COMPANY_COLUMNS else
                       expected[c] if record.reference_participant else data.baseline_by_side[record.side][c])
            np.testing.assert_array_equal(references[i, c], primary)

def test_stored_all23_mean_is_separate_from_held_out_comparator(assessed208):
    _, data, (rows, _, refs, _, _, _) = assessed208
    for side in ("left", "right"):
        mask = data.records.reference_participant & data.records.side.eq(side)
        for channel in ("pelvic_tilt", "hip_rotation", "knee_rotation"):
            c = NAMES.index(channel)
            approved = data.baseline_by_side[side][c]
            np.testing.assert_allclose(approved, data.curves[mask.to_numpy(), c].mean(axis=0), atol=1e-12, rtol=0)
            for i in data.records.index[mask]:
                metric = rows[(rows.record_id == data.records.loc[i, "record_id"]) & (rows.channel == channel)].iloc[0]
                peers = mask & data.records.participant.ne(data.records.loc[i, "participant"])
                held_out = data.curves[peers.to_numpy(), c].mean(axis=0)
                np.testing.assert_array_equal(refs[i, c], held_out)
                expected = np.linalg.norm(data.curves[i, c] - held_out) / np.sqrt(101)
                assert metric.rms_difference_deg == pytest.approx(expected, abs=1e-12)
                assert metric.approved_baseline_population_inclusion == "includes_assessed_participant"
                assert "approved_baseline_rms_deg" not in metric.index

def test_anatomical_direction_loaded_without_calibration_claim_or_sign_flip(assessed208):
    cfg, data, (rows, states, refs, _, _, _) = assessed208
    directions = cfg["interpretation"]["verified_direction_conventions"]
    assert set(directions) == set(NAMES)
    assert all(c["multiplier"] == 1 and not c["anatomical_zero_verified"] for c in directions.values())
    assert rows.anatomical_direction_status.eq("company_documented").all()
    assert rows.anatomical_zero_status.eq("unverified").all()
    assert not cfg["interpretation"]["verified_phase_protocol"]
    for i, r in data.records.iterrows():
        result = interpret_record(r.to_dict(), data.curves[i], refs[i], states[i],
            rows[rows.record_id.eq(r.record_id)].to_dict("records"), cfg)
        assert result["muscle_suggestion_count"] == 0
