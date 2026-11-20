import numpy as np
import pytest
from raycura.gait_measurements import metrics,quality

def test_offset_amplitude_and_shape_are_distinct():
    ref=15+20*np.sin(np.linspace(0,2*np.pi,101))
    m=metrics(ref+8,ref)
    assert m["rms_difference_deg"]==pytest.approx(8)
    assert m["centered_rms_difference_deg"]==pytest.approx(0,abs=1e-12)
    assert m["linear_slope"]==pytest.approx(1)
    assert m["linear_intercept_deg"]==pytest.approx(8)
    assert m["linear_r2"]==pytest.approx(1)
    m=metrics(.5*ref+4,ref)
    assert m["linear_slope"]==pytest.approx(.5)
    assert m["linear_intercept_deg"]==pytest.approx(4)
    assert m["linear_r2"] == pytest.approx(1)
    assert "linear_residual_rms_deg" not in m
    assert m["rom_deg"]==pytest.approx(20)

def test_missing_and_flat_curves_are_explicit(cfg):
    x=np.ones(101)
    assert quality(x,cfg["technical_quality"])[0]=="suspect"
    x[20]=np.nan
    assert quality(x,cfg["technical_quality"])[0]=="unusable"
    assert metrics(x)=={}
    assert np.isnan(metrics(np.arange(101.),np.ones(101))["linear_slope"])

@pytest.mark.parametrize("first,second,location,signed", [
    (3., 2., 0, 3.), (-3., -3., None, -3.), (3., -3., None, None),
    (0., 0., None, 0.), (3., 3. - 5e-11, None, 3.),
])
def test_largest_gap_distinguishes_unique_location_and_direction(first,second,location,signed):
    x = np.zeros(101)
    x[0], x[100] = first, second
    result = metrics(x, np.zeros(101))
    if location is None:
        assert np.isnan(result["largest_difference_grid_pct"])
    else:
        assert result["largest_difference_grid_pct"] == location
    if signed is None:
        assert np.isnan(result["largest_signed_difference_deg"])
    else:
        assert result["largest_signed_difference_deg"] == signed


def test_comparator_cannot_broadcast_and_missing_reference_retains_motion_span():
    x = np.arange(101.)
    with pytest.raises(ValueError, match="101-point"):
        metrics(x, [1.0])
    m = metrics(x, np.full(101, np.nan))
    assert m["rom_deg"] == 100. and "rms_difference_deg" not in m

def test_mean_curve_rom_is_not_mean_individual_rom():
    a=np.sin(np.linspace(0,2*np.pi,101));b=-a
    assert np.mean(np.ptp([a,b],axis=1))==pytest.approx(2)
    assert np.ptp(np.mean([a,b],axis=0))==pytest.approx(0)

def test_saved_metrics_independently_recalculate_all_finite_curves(saved):
    curves=saved["arrays"]["curves"];refs=saved["arrays"]["reference"]
    from raycura.config import NAMES
    keyed=saved["metrics"].set_index(["record_id","channel"])
    for i,r in saved["records"].iterrows():
        for j,ch in enumerate(NAMES):
            row=keyed.loc[(r.record_id,ch)]
            x,ref=curves[i,j],refs[i,j]
            assert row.rom_deg==pytest.approx(float(max(x)-min(x)),abs=1e-10)
            assert row.rms_difference_deg==pytest.approx(float(np.linalg.norm(x-ref)/np.sqrt(101)),abs=1e-10)
            assert row.mean_offset_deg==pytest.approx(float(sum(x-ref)/101),abs=1e-10)
            assert row.peak_grid_pct==int(np.argmax(x))
