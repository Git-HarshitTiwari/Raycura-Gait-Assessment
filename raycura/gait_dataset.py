"""Read-only source ingestion. Identity and agreeing re-export reconciliation only."""
from dataclasses import dataclass
from pathlib import Path
import hashlib
import hmac
import secrets
import unicodedata
import numpy as np
import pandas as pd
from .config import NAMES, CHANNELS, COMPANY_COLUMNS, ROOT
from .analysis_utils import sha256

KEY = ["_id", "_name", "_side", "_time"]

def norm(v):
    return "" if pd.isna(v) else " ".join(unicodedata.normalize("NFKC", str(v)).casefold().split())

def identifier(v):
    s = norm(v)
    return s[:-2] if s.endswith(".0") and s[:-2].isdigit() else s

def timestamp(v):
    if pd.isna(v) or not str(v).strip():
        return ""
    try:
        return pd.Timestamp(v).isoformat()
    except (TypeError, ValueError):
        return ""

def canonicalize(d):
    d = d.copy()
    d.columns = [str(c).strip().lower() for c in d]
    if d.columns.duplicated().any():
        raise ValueError("Duplicate normalized column names")
    for key, candidates, fn in [("_id", ["patient_id", "patientcode"], identifier),
            ("_name", ["name"], norm), ("_side", ["side"], norm),
            ("_time", ["assessment_time", "timestamp"], timestamp)]:
        col = next((c for c in candidates if c in d), None)
        d[key] = d[col].map(fn) if col else ""
    for name, (_, aliases) in CHANNELS.items():
        available = [a for a in [name] + aliases if a in d]
        if available:
            values = [pd.to_numeric(d[a], errors="coerce") for a in available]
            if any(not np.allclose(values[0], v, equal_nan=True, atol=1e-8, rtol=0) for v in values[1:]):
                raise ValueError(f"Conflicting channel aliases: {name}")
            d[name] = values[0]
    return d

class Identities:
    def __init__(self, secret):
        if len(secret) < 16:
            raise ValueError("Identity secret must contain at least 16 bytes")
        self.secret = secret

    def token(self, prefix, key):
        return prefix + "-" + hmac.new(self.secret, key.encode(), hashlib.sha256).hexdigest()[:16]

    @classmethod
    def local(cls, root=ROOT):
        path = Path(root) / "private" / "identity.key"
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(secrets.token_bytes(32))
        return cls(path.read_bytes())

def valid_grid(grid):
    return (grid.shape == (101,) and np.isfinite(grid).all()
            and np.allclose(grid, np.arange(101), atol=1e-8, rtol=0))

def read_waveforms(path, identities):
    d = canonicalize(pd.read_csv(path))
    if "gait_percentage" not in d:
        raise ValueError(f"{Path(path).name}: missing gait_percentage")
    rows = []
    for key, g in d.groupby(KEY, sort=False, dropna=False):
        pid = identities.token("S", "|".join(key[:2]))
        rid = identities.token("R", "|".join(key))
        g = g.assign(_pct=pd.to_numeric(g.gait_percentage, errors="coerce")).sort_values("_pct", kind="stable")
        grid = g._pct.to_numpy(float)
        problems = []
        if not all(key):
            problems.append("missing_identity_side_or_assessment_time")
        if key[2] not in ("left", "right"):
            problems.append("invalid_side")
        if not valid_grid(grid):
            problems.append("invalid_101_point_grid")
        values = np.full((10, 101), np.nan)
        if valid_grid(grid):
            for i, ch in enumerate(NAMES):
                if ch in g:
                    values[i] = g[ch].to_numpy(float)
        rows.append(dict(key=key, participant=pid, record_id=rid, side=key[2],
                         time=key[3], values=values, problems=problems))
    return rows

def merge_values(a, b):
    common = np.isfinite(a) & np.isfinite(b)
    conflict = np.any(common & (np.abs(a-b) > 1e-8), axis=1)
    restored = (~np.isfinite(a)) & np.isfinite(b)
    result = np.where(np.isfinite(a), a, b)
    # Conflicting channels remain visible as unavailable. Never choose a source arbitrarily.
    result[conflict] = np.nan
    return result, conflict, restored.sum(axis=1)

@dataclass
class Dataset:
    records: pd.DataFrame
    curves: np.ndarray
    phases: dict
    provenance: pd.DataFrame
    duplicates: pd.DataFrame
    exclusions: pd.DataFrame
    subgroup: pd.DataFrame
    hashes: dict
    company: np.ndarray
    exploratory: np.ndarray
    baseline_by_side: dict | None = None
    anatomy: pd.DataFrame | None = None
    phase_rows: pd.DataFrame | None = None
    dataset_protocol: str = "legacy_exports_231"
    input_manifest: dict | None = None

def load_dataset(cfg, identities=None):
    """Use the explicitly selected protocol; never silently fall back to old data."""
    protocol = cfg.get("dataset_protocol", "legacy_exports_231")
    if protocol == "prepared_latest208":
        return load_prepared_dataset(cfg, identities)
    if protocol != "legacy_exports_231":
        raise ValueError(f"Unknown dataset protocol: {protocol}")
    return load_legacy_dataset(cfg, identities or Identities.local())

def load_prepared_dataset(cfg, identities=None):
    from .prepared_dataset import load_prepared_dataset as load
    return load(cfg, identities)

def load_legacy_dataset(cfg, identities):
    old, new = Path(cfg["original_data"]), Path(cfg["additional_data"])
    sources = [("reference_original", old / "gait_waveform_data_normal.csv", old / "gait_phase_data_normal.csv"),
               ("earlier_patient", old / "kinematic_curves_patients.csv", old / "gait_phases_patients.csv"),
               ("new_main", new / "gait_waveform_data.csv", new / "gait_phase_data.csv"),
               ("new_second", new / "gait_waveform_data_2.csv", new / "gait_phase_data_2.csv")]
    merged, hashes, phase_data = {}, {}, {}
    provenance, duplicates, excluded = [], [], []
    id_names, name_ids = {}, {}
    phase_conflicts = set()
    for label, wave, phase in sources:
        hashes[str(wave)] = sha256(wave)
        for row in read_waveforms(wave, identities):
            key, rid = row["key"], row["record_id"]
            id_names.setdefault(key[0], set()).add(key[1])
            name_ids.setdefault(key[1], set()).add(key[0])
            if row["problems"]:
                excluded.append(dict(record_id=rid, source=wave.name, reason=";".join(row["problems"])))
                continue
            for i, ch in enumerate(NAMES):
                provenance.append(dict(record_id=rid, source=str(wave), channel=ch,
                                       finite_samples=int(np.isfinite(row["values"][i]).sum())))
            if key in merged:
                prior = merged[key]
                values, conflict, restored = merge_values(prior["values"], row["values"])
                prior["values"] = values
                prior["conflict"] |= conflict
                prior["sources"].append(label)
                duplicates.append(dict(record_id=rid, source=wave.name,
                    restored_samples=int(restored.sum()), conflicting_channels=";".join(np.array(NAMES)[conflict])))
            else:
                row["sources"] = [label]
                row["conflict"] = np.zeros(10, dtype=bool)
                merged[key] = row
        if phase.exists():
            hashes[str(phase)] = sha256(phase)
            d = canonicalize(pd.read_csv(phase))
            pc = next((c for c in ("phase", "phaselabel") if c in d), None)
            if pc and "percentage" in d:
                for key, g in d.groupby(KEY, sort=False, dropna=False):
                    rid = identities.token("R", "|".join(key))
                    labs = g[pc].astype(str).str.upper().str.strip()
                    p = pd.Series(pd.to_numeric(g.percentage, errors="coerce").to_numpy(), index=labs)
                    valid = len(p) == 8 and set(p.index) == set("ABCDEFGH")
                    vals = p.reindex(list("ABCDEFGH")).to_numpy(float) if valid else np.full(8, np.nan)
                    valid = valid and np.isfinite(vals).all() and np.all(np.diff(vals)>0) and abs(vals[0])<1e-8 and abs(vals[-1]-100)<1e-8
                    if valid:
                        if rid in phase_data and not np.allclose(phase_data[rid], vals, atol=1e-8, rtol=0):
                            phase_conflicts.add(rid)
                        phase_data[rid] = vals.tolist()
    if any(len(v)>1 for k,v in id_names.items() if k) or any(len(v)>1 for k,v in name_ids.items() if k):
        raise ValueError("Ambiguous participant ID/name crosswalk; group validation cannot proceed safely")
    for rid in phase_conflicts:
        phase_data.pop(rid, None)
    ref_people = {r["participant"] for r in merged.values() if "reference_original" in r["sources"]}
    flat_people, subset_ids, sub_audit = set(), set(), []
    subset = new / "gait_waveform_data_flatfoot.csv"
    if subset.exists():
        hashes[str(subset)] = sha256(subset)
        for r in read_waveforms(subset, identities):
            existing = merged.get(r["key"])
            ok = existing is not None and not r["problems"] and np.allclose(r["values"], existing["values"], atol=1e-8, rtol=0, equal_nan=True)
            sub_audit.append(dict(record_id=r["record_id"], matched_existing=ok))
            if not ok:
                raise ValueError("Flat-foot subset contains unmatched or conflicting curves; no extra assessments added")
            flat_people.add(r["participant"])
            subset_ids.add(r["record_id"])
    records, curves = [], []
    for row in sorted(merged.values(), key=lambda r:r["record_id"]):
        row["values"][row["conflict"]] = np.nan
        cohort = "development" if any(s in row["sources"] for s in ("new_main", "new_second")) else "challenge"
        records.append(dict(record_id=row["record_id"], participant=row["participant"], side=row["side"],
            assessment_time=row["time"], source_exports=";".join(row["sources"]), cohort=cohort,
            reference_original="reference_original" in row["sources"], reference_participant=row["participant"] in ref_people,
            flatfoot_observational=row["participant"] in flat_people, in_flatfoot_subset=row["record_id"] in subset_ids,
            historical_marks_available=row["record_id"] in phase_data,
            conflicting_channels=";".join(np.array(NAMES)[row["conflict"]])))
        curves.append(row["values"])
    frame = pd.DataFrame(records)
    if (frame.groupby("participant").cohort.nunique()>1).any():
        raise ValueError("Development/challenge participant overlap")
    refpath = old / "df_normative_PPFAADP.csv"
    hashes[str(refpath)] = sha256(refpath)
    ref = pd.read_csv(refpath)
    ref.columns = [c.lower() for c in ref]
    company = np.full((10,101), np.nan)
    for ch, col in COMPANY_COLUMNS.items():
        if len(ref)!=101 or col not in ref:
            raise ValueError("Company reference schema mismatch")
        company[NAMES.index(ch)] = pd.to_numeric(ref[col],errors="coerce").to_numpy(float)
    exploratory = np.full((10,101),np.nan)
    extra = new / "completed_baseline_original7_plus_exploratory3.csv"
    if extra.exists():
        hashes[str(extra)] = sha256(extra)
        e = pd.read_csv(extra)
        e.columns = [c.lower() for c in e]
        for ch,col in COMPANY_COLUMNS.items():
            if not np.array_equal(e[col].to_numpy(float),company[NAMES.index(ch)]):
                raise ValueError("Completed reference altered a company mean")
        for ch in ("pelvic_tilt","hip_rotation","knee_rotation"):
            exploratory[NAMES.index(ch)] = e[f"exploratory_{ch}_mean_deg"].to_numpy(float)
    return Dataset(frame,np.asarray(curves),phase_data,pd.DataFrame(provenance),
        pd.DataFrame(duplicates),pd.DataFrame(excluded,columns=["record_id","source","reason"]),
        pd.DataFrame(sub_audit),hashes,company,exploratory)
