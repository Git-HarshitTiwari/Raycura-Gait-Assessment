"""Independently verify the local interface against prepared source rows and saved results."""
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi import HTTPException

from raycura import assessment_api as api
from raycura.assessment_graphs import figure_spec
from raycura.config import CHANNELS, NAMES, ROOT

def test_every_named_walk_metrics_and_plots(store):
    combined = Path(store.cfg["prepared_data"])/"05 - Combined Dataset"
    source = pd.read_csv(combined/"All Waveforms.csv")
    phase_rows = pd.read_csv(combined/"All Phases.csv",dtype={"FrameTime":str},keep_default_na=False)
    index = pd.read_csv(combined/"Assessment Index.csv").set_index("record_id")
    assert len(store.directory()) == 104
    matched = recordings = checked = paired_motions = unpaired_motions = 0
    for p in store.directory():
        assessment = store.assessment(p["key"])
        for side, walk in assessment["walks"].items():
            rid = walk["id"]
            original = index.loc[rid]
            assert (assessment["name"],side,p["key"]) == (p["name"],original.side.lower(),original.participant)
            assert p["name"].casefold() == original["name"].strip().casefold()
            phases = phase_rows[phase_rows.record_id==rid].sort_values("phase")
            assert [(v["name"],v["pct"],v["frameTime"]) for v in walk["marks"]] == list(zip(phases.phase_name,phases.percentage,phases.FrameTime))
            assert len(walk["rules"]) == 4
            matched += sum(r["status"]=="matched" for r in walk["rules"])
            recordings += 1
        for motion in NAMES:
            both = figure_spec(store,p["key"],motion)
            lines = {t["name"]:t for t in both["data"]}
            left = np.array(lines["Left walk"]["y"])
            right = np.array(lines["Right walk"]["y"])
            dates = {str(index.at[walk["id"],"assessment_time_iso"])[:10] for walk in assessment["walks"].values()}
            if len(dates) == 1:
                pair = assessment["comparison"][motion]
                np.testing.assert_allclose([pair["rangeDifference"],pair["rms"]],
                    [np.ptp(right)-np.ptp(left),np.sqrt(np.mean((right-left)**2))],atol=1e-9,rtol=0)
                paired_motions += 1
            else:
                assert motion not in assessment["comparison"]
                unpaired_motions += 1
            for side,walk in assessment["walks"].items():
                rid = walk["id"]
                rows = source[source.record_id==rid].sort_values("gait_percentage")
                col = next(c for c in rows if c.lower() in CHANNELS[motion][1])
                raw = rows[col].to_numpy()
                observed = lines[side.title()+" walk"]
                assert observed["x"] == rows.gait_percentage.tolist()
                np.testing.assert_allclose(observed["y"],raw,atol=1e-12,rtol=0)
                marks = lines[side.title()+" manual marks"]
                np.testing.assert_allclose(marks["y"],raw[np.array(marks["x"],dtype=int)],atol=1e-12,rtol=0)
                assert marks["customdata"] == [m["name"] for m in walk["marks"]]
                metric = walk["motions"][motion]
                ref = next(t for name,t in lines.items() if name=="Reference curve" or name.startswith(side.title()+" reference"))
                gap = raw - np.asarray(ref["y"])
                np.testing.assert_allclose([np.ptp(raw),np.sqrt(np.mean(gap**2)),np.mean(gap)],
                    [metric["rom_deg"],metric["rms_difference_deg"],metric["mean_offset_deg"]],atol=1e-9,rtol=0)
                checked += 1
    assert (recordings,matched,checked)==(208,13,2080)
    assert (paired_motions,unpaired_motions)==(1020,20)


def test_overlays_and_export_follow_selection(store):
    p=next(iter(store.people))
    spec=figure_spec(store,p,"hip_flexion","right",False,False,"right","myogait_hip_ankle_combination")
    assert [t["name"] for t in spec["data"]]==["Right healthy group · 5th–95th percentile","Right walk"]
    rid=store.people[p]["recordings"]["right"]
    np.testing.assert_array_equal(spec["data"][0]["y"][:101],store.arrays["lower"][store.positions[rid],NAMES.index("hip_flexion")])
    assert [(s["x0"],s["x1"]) for s in spec["layout"]["shapes"]]==[(60,100)]
    out=api.report(p,"right",False,False,"right","myogait_hip_ankle_combination","hip_flexion")
    assert out.body.count(b'class="plotly-graph-div"')==10 and b"Right healthy group" in out.body
    assert b"Manual phase marks: off" in out.body and 'attachment;' in out.headers["content-disposition"]


@pytest.mark.parametrize("call",[lambda:api.assessment("missing"),lambda:api.graph("missing","hip_flexion"),
    lambda:api.graph("missing","made-up")])
def test_unknown_selection_refused(call, store):
    with pytest.raises(HTTPException) as e: call()
    assert e.value.status_code==404


def test_unrelated_overlay_refused(store):
    p=next(iter(store.people))
    with pytest.raises(HTTPException) as e: api.graph(p,"pelvic_tilt",window="myogait_late_knee_flexion")
    assert e.value.status_code==422
    with pytest.raises(HTTPException): api.graph(p,"pelvic_tilt",side="left",band="right")


def test_offline_answer_bound_to_current_recording(store,monkeypatch):
    import raycura.evidence_assistant as rag
    def offline(*args,**kwargs): raise OSError("offline test")
    monkeypatch.setattr(rag,"retrieve",offline)
    rule_id = "myogait_nonpositive_early_ankle"
    matching_rule = next(
        rule for item in store.interpretations.values() for rule in item["source_rule_results"]
        if rule["rule_id"] == rule_id and rule["side"] == "left" and rule["status"] == "matched"
    )
    rid = matching_rule["record_id"]
    expected_angle = f'{matching_rule["observed_values"]["ankle_dorsiflexion"]:.2f}'
    reply=api.explanation(rid,api.Question(question="Why did the early ankle rule match?"))
    assert (reply["record_id"],reply["side"],reply["mode"])==(rid,"left","deterministic_fallback")
    assert all(c["record_id"]==rid for c in reply["cards"])
    assert reply["sources"] and any(expected_angle in c["text"] for c in reply["cards"])


def test_local_snapshot_and_inputs_preserved(store):
    ledger = ROOT / "implementation_stage5" / "starting_hashes.json"
    if not ledger.is_file():
        pytest.skip("The original preservation ledger is available only in the local workspace.")
    hashes=json.loads(ledger.read_text(encoding="utf-8"))
    manifest=json.loads((ROOT/store.cfg["output"]/"manifest.json").read_text(encoding="utf-8"))
    outputs={Path(k):v for k,v in hashes.items() if Path(k).is_relative_to(ROOT/store.cfg["output"])}
    assert len(outputs)==228 and len(manifest["input_hashes"])==10
    expected = outputs | {Path(k):v for k,v in manifest["input_hashes"].items()}
    for path,digest in expected.items():
        assert hashlib.sha256(path.read_bytes()).hexdigest()==digest
