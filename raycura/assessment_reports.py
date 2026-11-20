"""Render traceable assessment summaries, numerical reports and curve figures."""
from pathlib import Path
import html
import json
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from .config import ROOT, NAMES, CHANNELS
from .analysis_utils import save_json
from .assessment_evidence import rule_evidence

def curve_figure(values, reference, channel, cohort=None, lower=None, upper=None, predicted=None, status="usable", segment=None):
    fig=go.Figure()
    grid=np.arange(101)
    if lower is not None and upper is not None and np.isfinite(lower).all():
        fig.add_trace(go.Scatter(x=grid,y=lower,mode="lines",line=dict(width=0),showlegend=False,hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=grid,y=upper,mode="lines",line=dict(width=0),fill="tonexty",fillcolor="rgba(26,140,163,0.10)",
                                name="Cohort pointwise 5th–95th (descriptive)",hoverinfo="skip"))
    if np.isfinite(reference).all():
        fig.add_trace(go.Scatter(x=grid,y=reference,name="Selected reference mean",line=dict(color="#718096",dash="dash")))
    if cohort is not None and np.isfinite(cohort).all() and not np.allclose(cohort,reference):
        fig.add_trace(go.Scatter(x=grid,y=cohort,name="Same-side cohort mean",line=dict(color="#b7791f",dash="dot")))
    fig.add_trace(go.Scatter(x=grid,y=values,name="Recorded angle"+(" — quality review" if status!="usable" else ""),line=dict(color="#0676a8",width=3),connectgaps=False))
    if predicted is not None and np.isfinite(predicted).all():
        fig.add_trace(go.Scatter(x=grid,y=predicted,name="Ridge expected curve (experimental)",line=dict(color="#805ad5",dash="dot")))
    if segment:
        fig.add_vrect(x0=segment[0],x1=segment[1],fillcolor="#f6ad55",opacity=.12,line_width=0)
    fig.update_layout(title=CHANNELS[channel][0],template="plotly_white",height=400,
        margin=dict(l=45,r=20,t=50,b=55),xaxis_title="Exported cycle position (%)",yaxis_title="Recorded angle (degrees)",
        legend=dict(orientation="h",y=-.22),font=dict(color="#243747"),hovermode="x unified")
    return fig

def record_markdown(record, measurements, interpretation, comparisons, ml=None):
    rid=record["record_id"]
    lines=[f"# Raycura assessment {rid}",f"Side: {record['side']}. Research assessment; clinical status undetermined.",
        "", "## Recorded measurements", "", "| Motion | Quality | Movement span (°) | Overall curve difference (° RMS) | Average angular shift (°) | Reference |",
        "|---|---|---:|---:|---:|---|"]
    def number(v): return f"{v:.2f}" if pd.notna(v) else "unavailable"
    for _,r in measurements.iterrows():
        lines.append(f"| {CHANNELS[r.channel][0]} | {r.measurement_status} | {number(r.get('rom_deg'))} | {number(r.get('rms_difference_deg'))} | {number(r.get('mean_offset_deg'))} | {r.reference_status} |")
    lines += ["", "## Movement and evidence findings", ""]
    source_results = interpretation.get("source_rule_results")
    if not interpretation["cards"] and source_results is not None:
        lines.append("No shift or reduced-excursion observation met its criteria.")
    elif not interpretation["cards"]:
        lines.append("No complete descriptive or biomechanical pattern met the registered rules. This does not establish normal gait.")
    for c in interpretation["cards"]:
        lines += [f"### {c['title']}",c["observation"],c["interpretation"],f"Next check: {c['next_check']}",
                  f"Evidence IDs: {', '.join(c['source_ids'])}.",""]
    if source_results is not None:
        lines += ["", rule_results_markdown(source_results), ""]
    lines += ["## Muscle-function indications", ""]
    if interpretation["muscle_suggestion_count"]==0:
        lines.append("None supported. Missing or incomplete prerequisites are not evidence of normal muscle function.")
    for rule in interpretation["muscle_rules"]:
        lines.append(f"- {rule['rule']}: {rule['status']}. {'; '.join(rule['reasons'])}")
    lines += ["", "## Repeat and side comparisons", ""]
    if comparisons.empty:
        lines.append("No eligible paired comparison is available. Repeatability is not established.")
    else:
        for pair,g in comparisons.groupby(["comparison","first_record","second_record"]):
            usable=g[g.comparable_numeric]
            lines.append(f"- {pair[0]}: {pair[1]} versus {pair[2]}, {len(usable)} numerically usable channels. Acquisition conditions are not verified as matched.")
    if ml is not None and not ml.empty:
        lines += ["", "## Cross-channel ML", "", "| Motion | Eligibility | Ridge RMS (deg) | Mean RMS (deg) | Learned flag enabled |", "|---|---|---:|---:|---|"]
        for _,r in ml.iterrows():
            lines.append(f"| {CHANNELS[r.channel][0]} | {r.eligibility} | {number(r.ridge_rmse_deg)} | {number(r.mean_predictor_rmse_deg)} | {bool(r.learned_flag_enabled)} |")
    elif source_results is not None:
        lines += ["", "## ML status", "", "The four recorded movement rules use fixed numerical thresholds. ML training and inference were inactive."]
    else:
        lines += ["", "## ML status", "", "Not run for this numerical refresh. Earlier trained predictions, screening gates and accuracy results have not been applied to this selected dataset."]
    lines += ["", "## Limits", "", "References are means and exploratory cohort envelopes, not validated normal limits. Technical usability does not establish physical measurement accuracy. Left and right legs were recorded during separate walks. Peak positions are exported-grid features, not verified clinical events. Clinical diagnosis, symptoms, muscle impairment and individual predictive uncertainty are not established."]
    lines += ["", "## Evidence sources", ""]
    library=json.loads((ROOT/"evidence"/"corpus.json").read_text(encoding="utf-8"))
    used={s for c in interpretation["cards"] for s in c["source_ids"]}
    for d in library:
        if d["id"] in used:lines.append(f"- {d['id']}: [{d['title']}]({d['url']}). Applicability: {d['section']}.")
    return "\n".join(lines)


def rule_results_markdown(results):
    """Render evidence from the saved decisions without recomputing an angle or match."""
    lines = ["### Experimental recorded movement rules", "",
             "| Condition | Outcome | Recorded evidence and required threshold |",
             "|---|---|---|"]
    for result in results:
        evidence = rule_evidence(result)
        status = result["status"].replace("_", " ")
        lines.append(f"| {result['display_name']} | {status} | {' · '.join(evidence)} |")
    lines += ["", "Windows include both endpoints on the exported cycle. The angle origin and physical "
              "gait phases are unverified. A match describes this recording. "
              f"[Adapted myogait source]({results[0]['source_reference']['url']})."]
    return "\n".join(lines)

def export_html(markdown,figures):
    # Escape all report text; no raw source or model HTML is executable.
    body='<pre class="report">'+html.escape(markdown)+'</pre>'
    for i,fig in enumerate(figures):
        body+=fig.to_html(full_html=False,include_plotlyjs=True if i==0 else False)
    return '<!doctype html><html><head><meta charset="utf-8"><title>Raycura assessment</title><style>body{max-width:1100px;margin:35px auto;color:#223748;font-family:Arial,sans-serif}.report{white-space:pre-wrap;font-family:inherit;line-height:1.55}</style></head><body>'+body+'</body></html>'

def technical_report(out, data, measurements, interpretations, gates, cfg):
    if gates is None or gates.empty:
        return numerical_technical_report(out,data,measurements,interpretations,cfg)
    out=Path(out)
    cards=[c for p in interpretations.values() for c in p["cards"]]
    lines=["# Raycura project — executed technical report", "",
        "The project measures recorded kinematics and generates bounded review findings. It does not establish clinical abnormality or muscle impairment.", "",
        "## Dataset reconciliation", "",
        f"- {data.records.participant.nunique()} participants; {len(data.records)} assessments; {len(NAMES)} channels per assessment.",
        f"- {int(data.records.reference_original.sum())} original reference assessments from {data.records[data.records.reference_original].participant.nunique()} people.",
        f"- {len(data.duplicates)} agreeing duplicate exports reconciled. {int(data.duplicates.restored_samples.sum())} missing samples restored from agreeing re-exports.",
        f"- Flat-foot observational subset: {int(data.records.in_flatfoot_subset.sum())} existing assessments; {data.records[data.records.flatfoot_observational].participant.nunique()} people. Participant-level reporting includes {int(data.records.flatfoot_observational.sum())} assessments.",
        f"- Channel quality: {measurements.measurement_status.value_counts().to_dict()}. Technical review thresholds are not clinical cutoffs.",
        "", "## Reference meaning", "",
        "Seven original company mean waveforms are unchanged. Three legacy exploratory means are retained for comparison; same-side reference-person-excluded cohort means are used for their primary numeric comparisons. None supplies validated population normal limits. Pointwise envelopes are descriptive, exclude the assessed person, and do not provide simultaneous 95% coverage. Company-source participant overlap is unknown, so company differences are not used to calibrate ML performance.",
        "", "## Actual interpretation coverage", "",
        f"{len(cards)} rule cards across {sum(bool(x['cards']) for x in interpretations.values())} assessments.",
        f"Muscle-specific cards: {sum(c['kind']=='muscle_function' for c in cards)}.",
        "The supplied data do not document anatomical sign/zero conventions or verified support boundaries. Anatomy-specific muscle rules are therefore withheld. This is a material limitation: the delivered application must not be presented as having identified actual problem muscles. Complete, incomplete and contradictory rules are separately exercised with synthetic tests, which validate software logic only.",
        "", "## Fixed Ridge evaluation", "",
        "The fixed cross-channel candidate uses only other compatible motion curves, not manual phase marks. Each reference person and all their repeats are excluded from their evaluation model. Inner reference folds calibrate residual scaling and maximum-across-channels review thresholds. Other participants are evaluated with frozen reference-only candidates. Historical challenge data are not used to choose models.",
        "", "| Channel | Held-out Ridge RMS deg | Mean RMS deg | Relative improvement | ML flag enabled | Failed gates |", "|---|---:|---:|---:|---|---|"]
    for _,r in gates.iterrows():
        lines.append(f"| {r.channel} | {r.ridge_rmse_deg:.3f} | {r.mean_predictor_rmse_deg:.3f} | {r.relative_rmse_gain:.1%} | {bool(r.learned_flag_enabled)} | {r.failed_gates} |")
    lines += ["", "Prediction improvement is not abnormality detection accuracy. Controlled offset, excursion and time-warp changes are sensitivity tests, not patient diagnoses. Channel flags are disabled if any registered gate fails. Experimental predicted curves remain inspectable. Low residuals never override measured differences.",
        "", "## Uncertainty and failures", "",
        "ml_gate_results.csv gives paired participant-bootstrap confidence intervals for mean error differences. These are not individual prediction intervals. Individual uncertainty and clinical sensitivity/specificity are unestimated. The reference group is small and not independently clinically verified. Unknown preprocessing may encode historical annotation decisions. Two limbs and repeats are correlated. Different reference choices can change the apparent size of a finding. No clinical reviewer evaluation has been completed.",
        "", "## Local RAG and reporting", "",
        "EmbeddingGemma retrieves a small, versioned primary-source evidence corpus. Gemma selects approved fact/explanation IDs; exact report prose, measurements and citations are rendered from those approved objects. Unsupported prose, invalid IDs or source mismatches are rejected, with an explicit deterministic fallback. No external API or patient-upload service is used. See rag_validation.json for the actual local inference/retrieval results; a successful Ollama request does not validate medicine.",
        "", "## Reproduction and artifacts", "",
        "Run `python run_gait_analysis.py` using the project virtual environment, then `python -m pytest`. `config.json` and `PROTOCOL.md` freeze operational settings. Source and code SHA-256 hashes are captured in manifest.json. Numeric model files contain no pickle code. Predictions, controlled-change results, exclusions, provenance, pairs and all assessment reports are saved alongside this report.",
        "", "## Recommended next step", "",
        "Use the assessment explorer to inspect numerical and evidence findings on existing recordings. Obtain documented angle conventions and qualified review before enabling any anatomy-specific rule in real use. Collect verified outcomes before claiming diagnostic utility. Do not enlarge the model search to hide failed gates."]
    (out/"TECHNICAL_REPORT.md").write_text("\n".join(lines),encoding="utf-8")


def numerical_technical_report(out,data,measurements,interpretations,cfg):
    """Report this dataset's measurements without borrowing archived ML results."""
    out=Path(out)
    records=data.records
    cards=[c for p in interpretations.values() for c in p["cards"]]
    reference=records.reference_participant.astype(bool)
    flatfoot=records.flatfoot_observational.astype(bool)
    protocol=getattr(data,"dataset_protocol",cfg.get("dataset_protocol","configured_sources"))
    lines=["# Raycura — numerical assessment refresh", "",
        "This run recomputes recorded kinematic measurements and the existing descriptive rule outputs. It does not train, select or reuse an ML detector, and it does not establish clinical abnormality or muscle impairment.", "",
        "## Selected dataset", "",
        f"- Protocol: {protocol}.",
        f"- {records.participant.nunique()} participants; {len(records)} selected limb assessments; {len(NAMES)} motion channels.",
        f"- Designated-reference participants: {records.loc[reference,'participant'].nunique()}; selected recordings: {int(reference.sum())}.",
        f"- Flat-foot observational subgroup: {records.loc[flatfoot,'participant'].nunique()} existing participants; {int(flatfoot.sum())} selected recordings. Membership is not an independently verified diagnosis.",
        f"- Historical duplicate-export audit: {len(data.duplicates)} entries. Duplicate exports are not additional recordings or physical repeatability evidence.",
        f"- Channel quality: {measurements.measurement_status.value_counts().to_dict()}. The original technical review thresholds are unchanged; usability is not proof of physical measurement accuracy.", "",
        "## Reference use", "",
        "The seven company mean waveforms are preserved. The three recalculated side-specific reference means are loaded separately and retained in the saved arrays. Reference-participant comparisons use person-excluded cohort references where indicated in the measurement metadata; other comparisons use the approved side-specific means. The metadata identify the selected reference and the actual comparison-population count. Means and pointwise descriptive envelopes are not validated population normal-limit bands. Company construction-population membership remains unknown.", "",
        "## Fresh numerical outputs", "",
        f"{len(measurements)} recording-motion rows report movement span, overall RMS difference and average signed shift in degrees. Details include recorded extrema, selected reference span and the largest signed gap. Technical fit, quality and individual-ROM support are available in measurement_support.csv.",
        "Recorded sides were measured in separate walks. Paired differences describe those recordings; matched capture conditions, synchronized bilateral gait and clinical progression are not established. Historical phase annotations remain optional context and are not treated as verified support intervals.", "",
        "## Existing interpretation rules", "",
        f"{len(cards)} descriptive/conditional cards across {sum(bool(p['cards']) for p in interpretations.values())} selected assessments; {sum(c['kind']=='muscle_function' for c in cards)} muscle-specific cards.",
        "Stage 3 retains the original offset and reduced-excursion thresholds and retires the generic concurrent-difference card. These observations describe the recorded curves. Anatomical zero, support timing and individual muscle impairment remain unverified.", "",
        "## ML status — not run", "",
        "No Ridge evaluation, alternative-model training, model selection, controlled-change experiment or model inference was executed. No archived predictions were reused. The earlier 231-assessment ML findings do not describe this newly selected dataset and are not presented as current results. See ml_status.json and manifest.json.", "",
        "## Local RAG status", "",
        "No Ollama, embedding or generation request is made by run_gait_analysis.py. The existing optional assistant remains a separate interactive feature; its behavior and evidence corpus are unchanged. Prior inference smoke checks are not a validation of this refreshed assessment output.", "",
        "## Reproduction and limits", "",
        "Run python run_gait_analysis.py in the project environment. Source and code hashes, the dataset protocol and analysis mode are saved in manifest.json. This refresh does not establish diagnostic sensitivity/specificity, individual prediction intervals, symptom causes or reviewer-validated utility."]
    if cfg.get("analysis_mode") == "numerical_and_myogait_rules":
        from .myogait_rules import RULES, summarize_rule_results
        summary = summarize_rule_results({rid: item["source_rule_results"] for rid,item in interpretations.items()})
        lines += ["", "## Experimental recorded movement rules", "",
                  f"{summary['evaluations']} decisions across {summary['assessments']} recordings. "
                  f"{summary['matched_assessments']} recordings matched at least one condition.", "",
                  "| Recorded condition | Matched | Did not match | Unevaluated |", "|---|---:|---:|---:|"]
        for rule in RULES:
            counts = summary["by_rule"][rule.id]
            lines.append(f"| {rule.title} | {counts['matched']} | {counts['not_matched']} | {counts['not_evaluated']} |")
        lines += ["", "myogait_rule_results.csv contains the exact inputs, per-channel windows, thresholds "
                  "and evidence for every decision. The four rules use recorded hip, knee and ankle sagittal angles. "
                  "Their counts describe these recordings. Underlying diagnoses and clinical accuracy are unknown."]
    (out/"TECHNICAL_REPORT.md").write_text("\n".join(lines),encoding="utf-8")

def summary_figures(out, gates, measurements):
    out=Path(out)/"figures";out.mkdir(exist_ok=True)
    if gates is not None and not gates.empty:
        fig=go.Figure()
        for col,label,color in [("mean_predictor_rmse_deg","Training-only mean","#9caeb8"),("ridge_rmse_deg","Cross-channel Ridge","#1a98bd")]:
            fig.add_bar(x=[CHANNELS[c][0] for c in gates.channel],y=gates[col],name=label,marker_color=color)
        fig.update_layout(template="plotly_white",title="Participant-held-out waveform prediction error",yaxis_title="RMS degrees",barmode="group",height=550)
        fig.write_html(out/"ml_comparison.html",include_plotlyjs=True)
    mat=measurements.pivot(index="record_id",columns="channel",values="rms_difference_deg").reindex(columns=NAMES)
    fig=go.Figure(go.Heatmap(z=mat.to_numpy(),x=[CHANNELS[c][0] for c in mat.columns],y=mat.index,colorscale="Blues",colorbar_title="RMS deg"))
    fig.update_layout(template="plotly_white",title="Recorded differences from selected means (not clinical severity)",height=750,yaxis=dict(showticklabels=False))
    fig.write_html(out/"recording_overview.html",include_plotlyjs=True)
