"""Read the verified result snapshot for the local assessment browser."""
import json

import numpy as np
import pandas as pd

from .assessment_evidence import approved_cards, rule_evidence
from .config import CHANNELS, NAMES, PHASES, ROOT, settings
from .evidence_assistant import explain
from .assessment_reports import record_markdown
from .patient_language import (CYCLE_GUIDE, describe_observation, display_name, graph_guide, phase_comparison, rule_description, CHECK_GUIDES,
                               CHECK_NAMES, metric_example, DEFINITIONS)
from .walk_questions import explain_walk

QUESTIONS = {
    "myogait_late_knee_flexion": "Did the knee angle stay below 40° during the last 40% of the cycle?",
    "myogait_hip_ankle_combination": "Did the hip angle exceed 45° late in the cycle while ankle movement stayed under 15° across the whole cycle?",
    "myogait_elevated_knee_position": "Did the knee angle stay above 15° throughout the cycle?",
    "myogait_nonpositive_early_ankle": "Did the ankle angle stay at or below 0° during the first 60% of the cycle?",
}
SIDES = ("left", "right")


class AssessmentWorkspace:
    """Resolve recordings by saved identity, including array axes and manual marks."""

    def __init__(self, cfg=None):
        self.cfg = settings() if cfg is None else cfg
        folder = ROOT / self.cfg["output"]
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        if (manifest["dataset_protocol"] != "prepared_latest208"
                or manifest["analysis_mode"] != "numerical_and_myogait_rules"
                or not manifest["myogait_rules_executed"]):
            raise ValueError("The workspace requires the verified latest-208 movement-rule run.")
        self.records = pd.read_csv(folder / "records.csv", keep_default_na=False).set_index("record_id")
        if not self.records.index.is_unique:
            raise ValueError("Duplicate recording identity in the saved result set.")
        self.people = {}
        for person, group in self.records.groupby("participant"):
            by_side = dict(zip(group.side, group.index))
            if len(group) != 2 or set(by_side) != set(SIDES) or group.name.nunique() != 1 or not group.name.iloc[0].strip():
                raise ValueError("Incomplete or ambiguous participant name/side binding.")
            self.people[person] = {"key": person, "name": display_name(group.name.iloc[0]), "recordings": by_side}
        if len(self.people) != 104 or len(self.records) != 208:
            raise ValueError("Unexpected primary population.")
        with np.load(folder / "assessment_curves.npz", allow_pickle=False) as archive:
            ids = archive["record_ids"].tolist()
            if set(ids) != set(self.records.index) or len(ids) != len(self.records) or archive["channels"].tolist() != NAMES:
                raise ValueError("Curve identities disagree with the saved index.")
            self.arrays = {k: archive[k] for k in ("curves","reference","lower","upper")}
        if any(a.shape != (208, 10, 101) for a in self.arrays.values()):
            raise ValueError("Unexpected curve dimensions.")
        self.positions = {rid: i for i, rid in enumerate(ids)}
        measurements = pd.read_csv(folder / "measurements.csv")
        self.measurements = dict(tuple(measurements.groupby("record_id")))
        phases = pd.read_csv(folder / "historical_phase_annotations.csv", keep_default_na=False, dtype={"FrameTime": str})
        self.phases = {}
        for rid, group in phases.groupby("record_id"):
            g = group.sort_values("phase")
            record = self.records.loc[rid]
            if (g.phase.tolist() != list(PHASES) or g.phase_name.tolist() != list(PHASES.values())
                    or set(g.side.str.lower()) != {record.side} or set(g.participant) != {record.participant}
                    or not g.percentage.between(0,100).all()):
                raise ValueError("Invalid recording-to-phase association.")
            self.phases[rid] = [{"name":r.phase_name,"pct":float(r.percentage),"frameTime":r.FrameTime} for r in g.itertuples()]
        self.interpretations = json.loads((folder / "interpretations.json").read_text(encoding="utf-8"))
        if any(set(d) != set(ids) for d in (self.measurements, self.phases, self.interpretations)):
            raise ValueError("Incomplete saved results for this recording set.")
        self.comparisons = pd.read_csv(folder / "recording_comparisons.csv")
        for rid in ids:
            row = self.records.loc[rid]
            ms = self.measurements[rid]
            interp = self.interpretations[rid]
            rules = interp["source_rule_results"]
            if (len(ms) != 10 or set(ms.channel) != set(NAMES) or set(ms.side) != {row.side}
                    or set(ms.participant) != {row.participant} or interp["record_id"] != rid
                    or len(rules) != len(QUESTIONS) or {q["rule_id"] for q in rules} != set(QUESTIONS)
                    or any((q["record_id"],q["side"]) != (rid,row.side) for q in rules)):
                raise ValueError("Mixed, duplicate or missing saved assessment evidence.")
        group_rom = pd.read_csv(folder / "measurement_support.csv",
                                usecols=["record_id", "channel", "cohort_median_individual_rom_deg"])
        group_rom = group_rom.set_index(["record_id", "channel"])["cohort_median_individual_rom_deg"]
        expected = measurements.set_index(["record_id", "channel"]).index
        if not group_rom.index.is_unique or len(expected) != len(group_rom) or not expected.isin(group_rom.index).all():
            raise ValueError("Saved comparison ranges do not match the assessment measurements.")
        self.observations = {}
        for rid, interp in self.interpretations.items():
            by_motion = self.measurements[rid].set_index("channel")
            cards = {}
            for card in interp["cards"]:
                motion = card["channels"][0]
                median = group_rom.at[(rid, motion)]
                if card.get("family") == "reduced_excursion" and not np.isfinite(median):
                    raise ValueError("A saved range finding is missing its comparison value.")
                cards[card["id"]] = describe_observation(card, by_motion.loc[motion], median)
            self.observations[rid] = cards

    def pairs(self, rid):
        table = self.comparisons
        return table[(table.first_record == rid) | (table.second_record == rid)]

    def directory(self):
        return sorted(({"key":p["key"], "name":p["name"], "date":min(self.records.at[r,"assessment_time"] for r in p["recordings"].values())[:10]}
                       for p in self.people.values()), key=lambda p:(p["name"].casefold(),p["date"],p["key"]))

    def corridor(self, rid, motion):
        pos = self.positions[rid]
        directions = self.cfg["interpretation"]["verified_direction_conventions"][motion]
        return phase_comparison(self.arrays["curves"][pos,NAMES.index(motion)], self.phases[rid], motion, directions)

    def assessment(self, person):
        patient = self.people[person]
        walks = {}
        for side, rid in patient["recordings"].items():
            interp = self.interpretations[rid]
            metrics = self.measurements[rid].set_index("channel")
            # Pandas JSON conversion rounds angles; keep native float values and nulls.
            motions = {ch:{key:None if pd.isna(value) else value for key,value in row.items()}
                       for ch,row in metrics.to_dict("index").items()}
            rules = [{"id":r["rule_id"], "question":QUESTIONS[r["rule_id"]], "status":r["status"],
                      "channels":r["required_channels"], "windows":r["input_windows"], "evidence":rule_evidence(r),
                      "title":CHECK_NAMES[r["rule_id"]], "guide":CHECK_GUIDES[r["rule_id"]],
                      "reading":rule_description(r), "source":r["source_reference"]["url"]} for r in interp["source_rule_results"]]
            walks[side] = dict(id=rid, time=self.records.at[rid,"assessment_time"], marks=self.phases[rid],
                               motions=motions, rules=rules, observations=list(self.observations[rid].values()),
                               phaseReadings={ch:self.corridor(rid,ch) for ch in NAMES},
                               muscleCount=interp["muscle_suggestion_count"])
        pair = self.comparisons
        linked = pair[(pair.participant == person) & (pair.first_record == patient["recordings"]["left"])
                      & (pair.second_record == patient["recordings"]["right"])]
        if linked.channel.duplicated().any():
            raise ValueError("Duplicate saved side comparison for this motion.")
        comparison = {row.channel:{"rangeDifference":row.rom_difference_deg,"rms":row.rms_between_recordings_deg}
                      for row in linked.itertuples() if row.comparable_numeric
                      and np.isfinite([row.rom_difference_deg,row.rms_between_recordings_deg]).all()}
        return {"key":person, "name":patient["name"], "walks":walks, "comparison":comparison}

    def answer(self, rid, question, motion=None):
        if motion is not None:
            direct = explain_walk(self, rid, question, motion)
            if direct is not None:
                return direct
        cards = approved_cards(self.measurements[rid], self.interpretations[rid], comparisons=self.pairs(rid))
        result = explain(question, self.cfg, cards)
        if (result["record_id"],result["side"]) != (rid,self.records.at[rid,"side"]):
            raise ValueError("Assistant response belongs to a different recording.")
        if motion is not None:
            metrics = self.measurements[rid].set_index("channel")
            rules = {r["rule_id"]:r for r in self.interpretations[rid]["source_rule_results"]}
            for card in result["cards"]:
                if card["kind"] == "measurement":
                    ch = card["channels"][0]
                    card["text"] = " ".join(metric_example(k,metrics.loc[ch],ch) for k in DEFINITIONS)
                elif card["id"] in self.observations[rid]:
                    observation = self.observations[rid][card["id"]]
                    card["title"] = observation["title"]
                    card["text"] = " ".join(observation[k] for k in ("observation", "interpretation", "next_check"))
                elif card["id"] in rules:
                    rule = rules[card["id"]]
                    card["title"] = CHECK_NAMES[card["id"]]
                    status = {"matched":"This pattern was seen.", "not_matched":"This pattern was not seen.",
                              "not_evaluated":"This pattern could not be checked."}
                    card["text"] = " ".join([CHECK_GUIDES[card["id"]],rule_description(rule),status[rule["status"]]])
                elif card["id"] == "rule_summary":
                    seen = [CHECK_NAMES[k] for k,r in rules.items() if r["status"] == "matched"]
                    checked = sum(r["status"] != "not_evaluated" for r in rules.values())
                    card["text"] = (f"{checked} patterns could be checked. " +
                                    ("Seen in this walk: "+", ".join(seen)+"." if seen else "None of the checked patterns was seen."))
        return result

    def markdown(self, rid):
        record = self.records.loc[rid].to_dict() | {"record_id":rid}
        return record_markdown(record, self.measurements[rid], self.interpretations[rid], self.pairs(rid))

    def motion_names(self):
        directions = self.cfg["interpretation"]["verified_direction_conventions"]
        return [{"key":ch,"name":CHANNELS[ch][0],"guide":graph_guide(ch,directions[ch]),"cycleGuide":CYCLE_GUIDE,
                 "positive":directions[ch]["positive_direction"].replace("_"," "),
                 "negative":directions[ch]["negative_direction"].replace("_"," ")} for ch in NAMES]
