import json

import pytest
import numpy as np
import pandas as pd
from raycura.config import ROOT, settings

@pytest.fixture
def cfg():
    """Load settings for numerical tests that can run without private recordings."""
    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8-sig"))
    if (ROOT / config["prepared_data"]).is_dir():
        return settings()
    return config


@pytest.fixture(scope="module")
def approved_config():
    """Require the approved data package for recording-dependent checks."""
    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8-sig"))
    if not (ROOT / config["prepared_data"]).is_dir():
        pytest.skip("Approved assessment dataset is available only in the local workspace.")
    return settings()


@pytest.fixture(scope="module")
def store(approved_config):
    if not (ROOT / approved_config["output"]).is_dir():
        pytest.skip("A local assessment result snapshot is required.")
    from raycura.assessment_api import workspace

    return workspace()

@pytest.fixture(scope="session")
def saved():
    out=ROOT/"results"
    if not out.is_dir():
        pytest.skip("Historical results are available only in the local workspace.")
    with np.load(out/"assessment_curves.npz",allow_pickle=False) as z:arrays={k:z[k] for k in z.files}
    return dict(out=out,arrays=arrays,records=pd.read_csv(out/"records.csv"),
        metrics=pd.read_csv(out/"measurements.csv"),ml=pd.read_csv(out/"ml_predictions.csv"),
        gates=pd.read_csv(out/"ml_gate_results.csv"),
        interpretations=json.loads((out/"interpretations.json").read_text()))
