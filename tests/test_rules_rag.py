import copy
import numpy as np
import pytest
from raycura.movement_findings import muscle_rules,interpret_record
from raycura.gait_measurements import metrics
from raycura.config import NAMES
from raycura.evidence_assistant import validate_selection,decode_selection,OllamaClient

def pattern(cfg):
    cfg=copy.deepcopy(cfg)
    signs={"knee_flexion":"flexion","hip_flexion":"flexion","pelvic_tilt":"anterior","ankle_dorsiflexion":"dorsiflexion"}
    cfg["interpretation"]["verified_direction_conventions"]={ch:dict(positive_direction=sign,multiplier=1,evidence="synthetic test only",anatomical_zero_verified=True) for ch,sign in signs.items()}
    curves=np.tile(np.linspace(1,2,101),(10,1));ref=curves.copy()
    for ch,delta in [("knee_flexion",10),("hip_flexion",8),("pelvic_tilt",4)]:curves[NAMES.index(ch)]+=delta
    return cfg,curves,ref,np.full(10,"usable")

def test_complete_pattern_is_examination_hypothesis(cfg):
    cfg,x,r,q=pattern(cfg)
    out=muscle_rules(x,r,q,cfg,"synthetic")
    assert out[0]["status"]=="matched" and out[0]["card"]["clinical_status"]=="undetermined"
    assert out[0]["card"]["kind"]=="muscle_function"

@pytest.mark.parametrize("missing",["direction","pattern","opposite","quality","zero"])
def test_incomplete_or_opposite_pattern_never_suggests_muscle(cfg,missing):
    cfg,x,r,q=pattern(cfg)
    c=NAMES.index("pelvic_tilt")
    if missing=="direction":cfg["interpretation"]["verified_direction_conventions"].pop("pelvic_tilt")
    elif missing=="pattern":x[c]=r[c]
    elif missing=="opposite":x[c]=r[c]-8
    elif missing=="quality":q[c]="suspect"
    elif missing=="zero":cfg["interpretation"]["verified_direction_conventions"]["pelvic_tilt"]["anatomical_zero_verified"]=False
    out=muscle_rules(x,r,q,cfg,"synthetic")
    assert all(x["card"] is None for x in out)

def test_hamstring_rule_needs_verified_support_and_complete_direction(cfg):
    cfg,x,r,q=pattern(cfg);x[NAMES.index("pelvic_tilt")]=r[NAMES.index("pelvic_tilt")]-5
    x[NAMES.index("ankle_dorsiflexion")]=r[NAMES.index("ankle_dorsiflexion")]+8
    assert muscle_rules(x,r,q,cfg,"synthetic")[1]["status"]=="withheld"
    cfg["interpretation"]["verified_phase_protocol"]=True
    cfg["interpretation"]["verified_stance_by_record"]={"synthetic":dict(start_pct=0,end_pct=60,evidence="synthetic test only")}
    assert muscle_rules(x,r,q,cfg,"synthetic")[1]["status"]=="matched"

def test_existing_records_do_not_get_invented_muscle_indications(saved):
    assert all(v["muscle_suggestion_count"]==0 for v in saved["interpretations"].values())
    assert all(c["kind"]!="muscle_function" for v in saved["interpretations"].values() for c in v["cards"])

def test_rag_accepts_only_supported_ids_and_no_generated_prose():
    cards=[dict(id="fact",source_ids=["source"],text="approved")];docs=[dict(id="source")]
    assert validate_selection(dict(selected_card_ids=["fact"],selected_evidence_ids=["source"]),cards,docs)==cards
    for response in [dict(selected_card_ids=["invented_diagnosis"],selected_evidence_ids=["source"]),
                     dict(selected_card_ids=["fact"],selected_evidence_ids=[]),
                     dict(selected_card_ids=["fact"],selected_evidence_ids=["source"],diagnosis="stroke"),
                     dict(selected_card_ids=["fact","fact"],selected_evidence_ids=["source"])]:
        with pytest.raises(ValueError):validate_selection(response,cards,docs)

def test_patient_context_cannot_be_sent_to_remote_endpoint(cfg):
    cfg["ollama"]["url"]="https://example.com"
    with pytest.raises(ValueError,match="local"):OllamaClient(cfg["ollama"])

def test_boolean_generation_schema_preserves_required_limitations():
    cards=[dict(id="measurement",source_ids=["source"]),dict(id="limitations",source_ids=["source"])]
    docs=[dict(id="source")]
    selected=decode_selection('{"selection":{"measurement":true,"limitations":true}}',cards,docs,["limitations"])
    assert selected==cards
    for raw in ['{"selection":{"measurement":true,"limitations":false}}',
                '{"selection":{"measurement":true,"limitations":"true"}}',
                '{"selection":{"measurement":true,"limitations":true,"diagnosis":true}}',
                '{"selection":{"measurement":false,"limitations":false}}',
                '{"selection":{"measurement":true,"limitations":true},"free_text":"invented"}']:
        with pytest.raises(ValueError):decode_selection(raw,cards,docs,["limitations"])
