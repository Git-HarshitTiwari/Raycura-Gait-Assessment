"""Recompute numerical assessments without training or reusing ML models."""
import os
from pathlib import Path
ROOT=Path(__file__).resolve().parent
os.environ.setdefault("TEMP",str(ROOT/"temp"));os.environ.setdefault("TMP",str(ROOT/"temp"))
os.environ.setdefault("OMP_NUM_THREADS","1");os.environ.setdefault("OPENBLAS_NUM_THREADS","1")
import argparse
import importlib.metadata
import numpy as np
from raycura.config import settings,NAMES
from raycura.gait_dataset import load_dataset,Identities
from raycura.gait_measurements import INTERNAL_METRICS, assess_dataset, compare_recordings
from raycura.movement_findings import interpret_record
from raycura.myogait_adapter import bind_assessments
from raycura.myogait_rules import (SOURCE_COMMIT, SOURCE_SHA256, evaluate_myogait_rules,
                                  summarize_rule_results, write_rule_results_csv)
from raycura.assessment_reports import record_markdown,technical_report,summary_figures
from raycura.analysis_utils import save_json,sha256

def run(config=None,output=None):
    cfg=settings(config)
    out=Path(output or ROOT/cfg["output"])
    archives = ("results", "results_latest208", "results_latest208_replay")
    stage3 = (ROOT / "results_pattern_prototype").resolve()
    target = out.resolve()
    if (any(target.is_relative_to((ROOT / name).resolve()) for name in archives)
            or (target.is_relative_to(stage3) and target != stage3 / "stage4")):
        raise ValueError("The earlier results folder is preserved. Choose a separate numerical output folder.")
    mode = cfg["analysis_mode"]
    if mode not in ("numerical_only_no_ml_training", "numerical_and_myogait_rules"):
        raise ValueError(f"Unknown analysis mode: {mode}")
    use_rules = mode == "numerical_and_myogait_rules"
    if use_rules and cfg.get("dataset_protocol") != "prepared_latest208":
        raise ValueError("The four source rules require the prepared_latest208 dataset.")
    if not use_rules and (target == stage3 / "stage4" or (target / "myogait_rule_results.csv").exists()):
        raise ValueError("Choose a separate output folder for a numerical-only run.")
    manifest_mode = mode if use_rules else "numerical_only"
    out.mkdir(parents=True,exist_ok=True)
    print(f"Reading configured source data for {manifest_mode}",flush=True)
    identities=None if cfg.get("dataset_protocol")=="prepared_latest208" else Identities.local()
    data=load_dataset(cfg,identities)
    numerical = assess_dataset(data,cfg)
    measurements,states,refs,cohort,lower,upper = numerical
    rules_by_record = {}
    if use_rules:
        limbs = bind_assessments(data, cfg, numerical)
        rules_by_record = {rid: evaluate_myogait_rules(limb) for rid, limb in limbs.items()}
    data.records.to_csv(out/"records.csv",index=False)
    data.provenance.to_csv(out/"provenance.csv",index=False)
    data.duplicates.to_csv(out/"duplicate_audit.csv",index=False)
    data.exclusions.to_csv(out/"exclusions.csv",index=False)
    data.subgroup.to_csv(out/"flatfoot_subset_audit.csv",index=False)
    save_json(out/"historical_marks.json",data.phases)
    if data.phase_rows is not None:
        data.phase_rows.to_csv(out/"historical_phase_annotations.csv",index=False)
    if data.anatomy is not None:
        data.anatomy.to_csv(out/"anatomy_definitions.csv",index=False)
    measurements.drop(columns=list(INTERNAL_METRICS), errors="ignore").to_csv(out/"measurements.csv",index=False)
    measurements.reindex(columns=["record_id", "channel", *INTERNAL_METRICS]).to_csv(
        out/"measurement_support.csv", index=False)
    pairs=compare_recordings(data,states);pairs.to_csv(out/"recording_comparisons.csv",index=False)
    arrays=dict(curves=data.curves,reference=refs,cohort=cohort,
        lower=lower,upper=upper,quality=states,company=data.company,legacy_exploratory=data.exploratory,
        record_ids=data.records.record_id.to_numpy(dtype="U32"),channels=np.asarray(NAMES))
    by_side=getattr(data,"baseline_by_side",None)
    if by_side:
        arrays["baseline_sides"]=np.asarray(["left","right"])
        arrays["approved_baseline_by_side"]=np.asarray([by_side[s] for s in ("left","right")])
    np.savez_compressed(out/"assessment_curves.npz",**arrays)
    interpretations={}
    for i,r in data.records.iterrows():
        interpretations[r.record_id]=interpret_record(r.to_dict(),data.curves[i],refs[i],states[i],
            measurements[measurements.record_id==r.record_id].to_dict("records"),cfg)
        if use_rules:
            interpretations[r.record_id]["source_rule_results"] = rules_by_record[r.record_id]
    if use_rules:
        write_rule_results_csv(out/"myogait_rule_results.csv", rules_by_record)
        save_json(out/"myogait_rule_summary.json", summarize_rule_results(rules_by_record))
    save_json(out/"interpretations.json",interpretations)
    save_json(out/"configuration.json",cfg)
    ml_status=dict(status="not_run",analysis_mode=manifest_mode,
        reason="The current assessment uses deterministic calculations. Archived predictions are excluded.",
        training_executed=False,legacy_predictions_reused=False)
    save_json(out/"ml_status.json",ml_status)
    print(f"Numerical assessment complete: {len(data.records)} records; ML not run",flush=True)
    reports=out/"assessments";reports.mkdir(exist_ok=True)
    for _,r in data.records.iterrows():
        text=record_markdown(r.to_dict(),measurements[measurements.record_id==r.record_id],interpretations[r.record_id],
            pairs[(pairs.first_record==r.record_id)|(pairs.second_record==r.record_id)])
        (reports/(r.record_id+".md")).write_text(text,encoding="utf-8")
    technical_report(out,data,measurements,interpretations,None,cfg)
    summary_figures(out,None,measurements)
    preservation={p:sha256(p)==h for p,h in data.hashes.items()}
    code={str(p.relative_to(ROOT)):sha256(p) for pattern in ("*.py","*.json","*.md") for p in ROOT.glob(pattern)}
    for folder in ("raycura","evidence","tests","validation_208"):
        code.update({str(p.relative_to(ROOT)):sha256(p) for p in (ROOT/folder).glob("*") if p.is_file()})
    save_json(out/"manifest.json",dict(version="1.3.0" if use_rules else "1.2.0",analysis_mode=manifest_mode,ml_status=ml_status,
        measurement_schema="stage3", measurement_support_file="measurement_support.csv",
        myogait_rules_executed=use_rules,
        myogait_source=dict(commit=SOURCE_COMMIT, sha256=SOURCE_SHA256) if use_rules else None,
        dataset_protocol=getattr(data,"dataset_protocol",cfg.get("dataset_protocol","original_csv_reconciliation")),
        input_hashes=data.hashes,original_sources_unchanged=preservation,
        code_hashes=code,protocol_file=cfg.get("protocol_file","PROTOCOL.md"),
        protocol_sha256=sha256(ROOT/cfg.get("protocol_file","PROTOCOL.md")),
        inventory=dict(participants=int(data.records.participant.nunique()),assessments=len(data.records),channels=len(NAMES)),
        versions={p:importlib.metadata.version(p) for p in ["numpy","pandas","scipy","scikit-learn","streamlit","plotly"]}))
    if not all(preservation.values()):raise RuntimeError("Source preservation verification failed")
    print(f"Complete. Results: {out}",flush=True)
    return out

if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--config");parser.add_argument("--output")
    args=parser.parse_args();run(args.config,args.output)
