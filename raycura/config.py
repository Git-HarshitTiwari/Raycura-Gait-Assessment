from pathlib import Path
import csv
import json

ROOT = Path(__file__).resolve().parents[1]
CHANNELS = {
    "pelvic_obliquity": ("Pelvic obliquity", ["pelvicobliquityarr"]),
    "pelvic_rotation": ("Pelvic rotation", ["pelvicrotationarr"]),
    "pelvic_tilt": ("Pelvic tilt", ["pelvictiltarr"]),
    "hip_flexion": ("Hip flexion / extension", ["hipflexionarr"]),
    "hip_abduction": ("Hip abduction / adduction", ["hipabductionarr"]),
    "hip_rotation": ("Hip rotation", ["hiprotationarr", "hiprotaionarr"]),
    "knee_flexion": ("Knee flexion / extension", ["kneeflexionarr"]),
    "knee_abduction": ("Knee varus / valgus", ["kneeabductionarr"]),
    "knee_rotation": ("Knee rotation", ["kneerotationarr"]),
    "ankle_dorsiflexion": ("Ankle dorsiflexion / plantarflexion", ["dorsiplanterarr"]),
}
NAMES = list(CHANNELS)
COMPANY_COLUMNS = {
    "knee_flexion": "main_final_avg_kf", "hip_flexion": "main_final_avg_hf",
    "hip_abduction": "main_final_avg_hp_ad", "knee_abduction": "main_final_avg_kn_vv",
    "ankle_dorsiflexion": "main_final_avg_an_dp",
    "pelvic_obliquity": "final_avg_pelvic_obliquity",
    "pelvic_rotation": "final_avg_pelvic_rotation",
}
PHASES = dict(zip("ABCDEFGH", ["Initial Contact", "Loading Response", "Mid-Stance",
    "Terminal Stance", "Pre-Swing", "Initial Swing", "Mid-Swing", "Terminal Swing"]))

def settings(path=None):
    cfg = json.loads(Path(path or ROOT / "config.json").read_text(encoding="utf-8-sig"))
    if cfg.get("dataset_protocol") == "prepared_latest208":
        cfg["prepared_data"] = (ROOT / cfg["prepared_data"]).as_posix()
        cfg["interpretation"]["verified_direction_conventions"] = anatomical_conventions(cfg["prepared_data"])
        cfg["interpretation"]["convention_evidence"] = "Company-approved anatomical directions from the immutable prepared dataset; anatomical zero and clinical phase boundaries remain unverified."
    return cfg

def anatomical_conventions(prepared_data):
    path = Path(prepared_data) / "07 - Documentation and Audit" / "Anatomical Definitions.csv"
    source_map = {alias: ch for ch, (_, aliases) in CHANNELS.items() for alias in aliases}
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    if len(rows) != 10:
        raise ValueError("Expected ten approved anatomical definitions")
    conventions = {}
    for row in rows:
        ch = source_map.get(row["source_channel"].lower())
        if ch is None or ch in conventions:
            raise ValueError("Invalid or duplicate anatomical channel")
        conventions[ch] = dict(positive_direction=row["positive_direction_company"].lower().replace(" ", "_"),
            negative_direction=row["negative_direction_company"].lower().replace(" ", "_"),
            multiplier=1, evidence=f"{path}; company report page {row['report_page']}; {row['sign_basis']}",
            anatomical_zero_verified=False, status="company_documented_direction_only")
    return conventions
