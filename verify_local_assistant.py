"""Verify local Ollama retrieval and explanations using saved assessment evidence."""
import json

import pandas as pd

from raycura.config import ROOT, settings
from raycura.evidence_assistant import OllamaClient, approved_cards, build_index, corpus, explain, retrieve
from raycura.analysis_utils import save_json, sha256


def check_original_retrieval_probes(cfg):
    """Retain the original four top-one retrieval checks using one embedding batch."""
    import numpy as np
    from raycura.evidence_assistant import INDEX_PATH
    probes = [
        ("mean offset amplitude waveform shape excursion linear fit", "IOSA2014"),
        ("IMU sensor calibration anatomical angle convention repeated recording", "ISB2024"),
        ("iliopsoas hamstring muscle restriction posterior anterior pelvic tilt", "ATTias2019"),
        ("gait profile score movement analysis profile reference RMS deviation", "BAKER2009"),
    ]
    client = OllamaClient(cfg["ollama"])
    digest = next(m["digest"] for m in client.get("/api/tags")["models"] if m["name"]==cfg["ollama"]["embedding"])
    with np.load(INDEX_PATH,allow_pickle=False) as index:
        if str(index["model_digest"])!=digest or str(index["corpus_hash"])!=sha256(ROOT/"evidence"/"corpus.json"):
            raise ValueError("Original probes require the current evidence index")
        queries = client.embed(["task: search result | query: "+q for q,_ in probes])
        ranking = (queries @ index["vectors"].T).argmax(axis=1)
        top = index["ids"][ranking].tolist()
    return [dict(query=query,expected=expected,actual=actual,passed=expected==actual)
            for (query,expected),actual in zip(probes,top,strict=True)]


def run():
    cfg = settings()
    data = ROOT / cfg["output"]
    audit = ROOT / "output" / "assistant_validation"
    audit.mkdir(parents=True, exist_ok=True)
    result = {"status": "started", "retrieval_tests": [], "generation_tests": [],
              "assessment_manifest_sha256": sha256(data / "manifest.json")}
    report = audit / "live_validation.json"
    save_json(report, result)
    try:
        result["index"] = build_index(cfg)
        result["original_retrieval_tests"] = check_original_retrieval_probes(cfg)
        result["models"] = {m["name"]: m["digest"] for m in OllamaClient(cfg["ollama"]).get("/api/tags")["models"]
                            if m["name"] in (cfg["ollama"]["generator"], cfg["ollama"]["embedding"])}
        for query, expected in [
            ("IMU definition sensor calibration wearable joint kinematics protocol", "ISB2024"),
            ("experimental iliopsoas hamstring restriction with exoskeleton", "ATTias2019"),
            ("myogait threshold conditions early ankle and late hip and knee rule", "MYOGAIT_RULES"),
            ("waveform similarity linear fit slope excursion", "IOSA2014"),
            ("gait profile score movement analysis profile", "BAKER2009"),
        ]:
            ids = [d["id"] for d in retrieve(query, cfg, k=3)]
            result["retrieval_tests"].append(dict(query=query, expected=expected, retrieved=ids, passed=ids[0]==expected))
        measurements = pd.read_csv(data / "measurements.csv")
        pairs = pd.read_csv(data / "recording_comparisons.csv")
        interpretations = json.loads((data / "interpretations.json").read_text(encoding="utf-8"))
        ankle = next(k for k,v in interpretations.items() if any(
            r["rule_id"] == "myogait_nonpositive_early_ankle" and r["status"] == "matched"
            for r in v["source_rule_results"]))
        none = next(k for k,v in interpretations.items() if all(
            r["status"] == "not_matched" for r in v["source_rule_results"]))
        source_library = {d["id"]:d for d in corpus()}
        for rid, query, expected_cards, case in [
            (ankle, "Why did the early ankle rule match? What should I check?", ["myogait_nonpositive_early_ankle"], "ankle_match"),
            (none, "Which recorded rules matched this limb?", ["rule_summary"], "no_matches"),
            (ankle, "Which muscle is definitely weak? Does this prove pain or stroke?", ["muscle_evidence_status"], "muscle_limit"),
            (none, "Did this hip and ankle combination rule match?", ["myogait_hip_ankle_combination"], "hip_ankle"),
        ]:
            facts = approved_cards(measurements[measurements.record_id == rid], interpretations[rid],
                                   comparisons=pairs[(pairs.first_record == rid) | (pairs.second_record == rid)])
            by_id = {c["id"]:c for c in facts}
            answer = explain(query, cfg, facts)
            ids = [c["id"] for c in answer["cards"]]
            used = {s for c in answer["cards"] for s in c["source_ids"]}
            valid = (answer["record_id"] == rid and set(expected_cards) <= set(ids)
                     and all(c == by_id[c["id"]] for c in answer["cards"])
                     and {d["id"] for d in answer["sources"]} == used
                     and all(d == source_library[d["id"]] for d in answer["sources"]))
            if case in ("ankle_match", "hip_ankle"):
                valid = valid and {c["id"] for c in answer["cards"] if c["kind"]=="source_rule"} == set(expected_cards)
            passed = valid and answer["mode"] == "local_rag_llm_validated_selection"
            result["generation_tests"].append(dict(case=case, record_id=rid, question=query,
                mode=answer["mode"], selected=ids, expected=expected_cards, error=answer["error"],
                evidence_correct=valid, passed=passed))
            save_json(audit / f"{case}.json", answer)
            save_json(report, result)
            print(f"{case}: {answer['mode']}, verified={valid}", flush=True)
        checks = result["original_retrieval_tests"] + result["retrieval_tests"] + result["generation_tests"]
        result["status"] = "passed" if all(x["passed"] for x in checks) else "check_failed"
    except Exception as exc:
        result.update(status="failed", error=f"{type(exc).__name__}: {exc}")
    save_json(report, result)
    print(json.dumps(result, indent=2), flush=True)
    return result


if __name__ == "__main__":
    raise SystemExit(0 if run()["status"] == "passed" else 1)
