"""Bind a prepared limb recording, its manual marks and its selected references."""
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

import numpy as np

from .config import NAMES, settings
from .gait_dataset import load_dataset
from .gait_measurements import assess_dataset
from .prepared_dataset import EXPORTED_CYCLE_PERCENT


# Keys used under angles_normalized in the pinned myogait analysis.py.
MYOGAIT_MOTIONS = MappingProxyType({
    "hip": "hip_flexion",
    "knee": "knee_flexion",
    "ankle": "ankle_dorsiflexion",
})


@dataclass(frozen=True, slots=True)
class ManualPhaseMark:
    """One historical click. FrameTime retains the units of the original export."""
    code: str
    name: str
    percentage: float
    frame_time: float


@dataclass(frozen=True, slots=True, eq=False)
class MotionComparison:
    """Selected reference feeds both the primary measurements and the plot."""
    recorded: np.ndarray
    selected_reference: np.ndarray
    stored_baseline: np.ndarray
    cohort_mean: np.ndarray
    cohort_p05: np.ndarray
    cohort_p95: np.ndarray
    measurements: Mapping
    direction: Mapping


@dataclass(frozen=True, slots=True, eq=False)
class LimbAssessment:
    """Ten motion comparisons and the annotations from this exact limb capture."""
    metadata: Mapping
    motions: Mapping[str, MotionComparison]
    manual_marks: tuple[ManualPhaseMark, ...]
    phase_protocol_verified: bool
    verified_stance: Mapping | None
    source_hashes: Mapping[str, str]
    grid_percent: tuple[int, ...] = EXPORTED_CYCLE_PERCENT

    def myogait_cycles(self) -> dict:
        """Return one exported limb curve set in the upstream normalized-input layout.

        Only usable sagittal fields are available for a later predicate. Consult
        motion quality before interpreting a missing field. Lists are independent
        copies because upstream consumers can mutate them and test list truthiness.
        """
        angles = {
            joint: self.motions[channel].recorded.tolist()
            for joint, channel in MYOGAIT_MOTIONS.items()
            if self.motions[channel].measurements["measurement_status"] == "usable"
        }
        return {"cycles": [{"side": self.metadata["side"], "angles_normalized": angles}]}


def load_assessments(config_path=None) -> dict[str, LimbAssessment]:
    """Load the verified combined package once. Look up an assessment by record ID."""
    cfg = settings(config_path)
    if cfg.get("dataset_protocol") != "prepared_latest208":
        raise ValueError("The myogait adapter requires the prepared_latest208 protocol.")
    data = load_dataset(cfg)
    return bind_assessments(data, cfg, assess_dataset(data, cfg))


def bind_assessments(data, cfg, numerical) -> dict[str, LimbAssessment]:
    """Bind the already loaded data to the references and QC from this same run."""
    if data.dataset_protocol != "prepared_latest208":
        raise ValueError("Binding limb assessments requires the verified prepared dataset.")
    rows, _, references, means, lower, upper = numerical
    # Use the numerical engine's actual comparator. Its stored baseline and
    # descriptive cohort are separate curves, even when their values coincide.
    indexed = rows.set_index(["record_id", "channel"], verify_integrity=True)
    measurements = indexed.astype(object).where(indexed.notna(), None).to_dict("index")
    for array in (data.curves, references, means, lower, upper, *data.baseline_by_side.values()):
        array.setflags(write=False)

    phase_groups = data.phase_rows.sort_values("phase").groupby("record_id")
    interpretation = cfg["interpretation"]
    directions = {
        channel: MappingProxyType(interpretation["verified_direction_conventions"][channel])
        for channel in NAMES
    }
    hashes = MappingProxyType(data.hashes)
    assessments = {}
    for i, record in enumerate(data.records.to_dict("records")):
        rid, side = record["record_id"], record["side"]
        marks = tuple(
            ManualPhaseMark(row.phase, row.phase_name, row.percentage, row.FrameTime)
            for row in phase_groups.get_group(rid).itertuples(index=False)
        )
        motions = {
            channel: MotionComparison(
                recorded=data.curves[i, c], selected_reference=references[i, c],
                stored_baseline=data.baseline_by_side[side][c], cohort_mean=means[i, c],
                cohort_p05=lower[i, c], cohort_p95=upper[i, c],
                measurements=MappingProxyType(measurements[rid, channel]),
                direction=directions[channel],
            )
            for c, channel in enumerate(NAMES)
        }
        stance = interpretation["verified_stance_by_record"].get(rid)
        assessments[rid] = LimbAssessment(
            metadata=MappingProxyType(record), motions=MappingProxyType(motions),
            manual_marks=marks, phase_protocol_verified=interpretation["verified_phase_protocol"],
            verified_stance=None if stance is None else MappingProxyType(stance),
            source_hashes=hashes,
        )
    return assessments
