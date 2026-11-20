"""Shared numerical, JSON and hash helpers for analysis and reports."""
from pathlib import Path
import hashlib
import json
import numpy as np

def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def clean_json(value):
    if isinstance(value, dict):
        return {str(k): clean_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, np.ndarray)):
        return [clean_json(v) for v in value]
    if isinstance(value, (np.floating, float)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, Path):
        return str(value)
    return value

def save_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(clean_json(value), indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")

def rms(x, axis=None):
    return np.sqrt(np.mean(np.square(x), axis=axis))
