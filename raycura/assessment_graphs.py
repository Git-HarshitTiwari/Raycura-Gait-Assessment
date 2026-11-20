"""Compose the same saved-data plot for the browser and standalone reports."""
import html

import numpy as np
import plotly.graph_objects as go

from .assessment_workspace import SIDES
from .config import CHANNELS, NAMES
from .patient_language import CHECK_NAMES, CYCLE_GUIDE, DEFINITIONS, METHOD_NOTE, compare_walks, graph_guide, metric_example
from .evidence_assistant import corpus

GRID = list(range(101))
COLORS = {"left":"#195bc7","right":"#bc4a26"}
MARKS = ["IC","LR","MSt","TSt","PSw","ISw","MSw","TSw"]


def angle_trace(name, values, color, dash, width):
    return dict(type="scatter", mode="lines", name=name, x=GRID, y=values,
                line=dict(color=color,width=width,dash=dash),
                hovertemplate="%{x}% of cycle · %{y:.2f}°<extra>%{fullData.name}</extra>")


def finite_values(values):
    return [float(v) if np.isfinite(v) else None for v in values]


def figure_spec(workspace, person, motion, side="both", marks=True, reference=True, band="off", window=""):
    """Select overlays by recording identity; limb positions use independent walks."""
    channel = NAMES.index(motion)
    selected = SIDES if side == "both" else (side,)
    records = workspace.people[person]["recordings"]
    if band != "off" and band not in selected:
        raise ValueError("The spread must belong to a displayed walk.")
    arrays = workspace.arrays
    traces, shapes = [], []
    if band != "off":
        i = workspace.positions[records[band]]
        low, high = arrays["lower"][i,channel], arrays["upper"][i,channel]
        if not (np.isfinite(low).all() and np.isfinite(high).all()):
            raise ValueError("The selected walk has no complete comparison spread.")
        label = band.title() + " healthy group · 5th–95th percentile"
        traces.append(dict(type="scatter",name=label,x=GRID+GRID[::-1],y=low.tolist()+high[::-1].tolist(),
                           mode="lines",line=dict(width=0),fill="toself",fillcolor="rgba(84,161,214,.19)",hoverinfo="skip"))
    reference_lines = {}
    for limb in selected:
        rid = records[limb]
        i = workspace.positions[rid]
        values = arrays["curves"][i,channel]
        if reference:
            baseline = arrays["reference"][i,channel]
            metric = workspace.measurements[rid].loc[lambda df:df.channel == motion].iloc[0]
            shared = metric.reference_status == "company_mean_numeric_comparison"
            key = "Reference curve" if shared else limb.title()+" reference · "+str(int(metric.reference_participants))+" people"
            if key not in reference_lines:
                reference_lines[key] = baseline
                traces.append(angle_trace(key,finite_values(baseline),"#697c8c" if shared else COLORS[limb],"dot",1.7))
            elif not np.array_equal(reference_lines[key],baseline,equal_nan=True):
                raise ValueError("The saved company references disagree across sides.")
        traces.append(angle_trace(limb.title()+" walk",finite_values(values),COLORS[limb],
                                  "solid" if limb=="left" else "dash",3))
        if marks:
            phases = workspace.phases[rid]
            pcts = [m["pct"] for m in phases]
            for p in pcts:
                shapes.append(dict(type="line", x0=p,x1=p,y0=0,y1=1,yref="paper",layer="below",
                                   line=dict(color=COLORS[limb],dash="dot",width=.55),opacity=.32))
            traces.append(dict(type="scatter",mode="markers+text",name=limb.title()+" manual marks",x=pcts,
                               y=finite_values(np.interp(pcts,GRID,values)),text=MARKS,
                               textposition="top center" if limb=="left" else "bottom center",
                               textfont=dict(color=COLORS[limb],size=11),customdata=[m["name"] for m in phases],
                               marker=dict(color=COLORS[limb],size=7,symbol="circle" if limb=="left" else "diamond"),
                               showlegend=False,hovertemplate=limb.title()+" · %{customdata}<br>%{x}% · %{y:.2f}°<extra></extra>"))
    if window:
        rules = workspace.interpretations[records[selected[0]]]["source_rule_results"]
        match = next((r for r in rules if r["rule_id"] == window and motion in r["input_windows"]), None)
        if match is None:
            raise ValueError("This check has no window on the selected motion.")
        start,end = match["input_windows"][motion]
        shapes.append(dict(type="rect",x0=start,x1=end,y0=0,y1=1,yref="paper",line=dict(width=0),
                           fillcolor="rgba(230,176,63,.13)",layer="below"))
    layout = dict(autosize=True, height=370, paper_bgcolor="white",plot_bgcolor="white",
                  font=dict(family="Inter, Segoe UI, sans-serif",color="#254454",size=13),
                  margin=dict(l=55,r=19,t=16,b=90), hovermode="closest",shapes=shapes,
                  xaxis=dict(title=dict(text="Gait cycle (%)",standoff=6),range=[-1,101],dtick=10,gridcolor="#ebf1f4",fixedrange=True),
                  yaxis=dict(title=dict(text="Angle (°)"),gridcolor="#dfe8ed",zerolinecolor="#9eafb9",fixedrange=True),
                  legend=dict(orientation="h",y=-.36,x=0,font=dict(size=12),itemclick=False,itemdoubleclick=False))
    return {"data":traces,"layout":layout}


def assessment_export(workspace, person, side, marks, reference, band, window="", window_motion=""):
    """Export a patient-readable report with the same readings and controls as the browser."""
    escape = html.escape
    selected = SIDES if side == "both" else (side,)
    patient = workspace.assessment(person)
    walks = patient["walks"]
    content = [f"<h1>{escape(patient['name'])}</h1><h2>Walking assessment</h2>",
               "<p>"+escape(CYCLE_GUIDE)+" The vertical axis shows the recorded angle in degrees.</p>",
               f"<p>Manual phase marks: {'shown' if marks else 'off'}. Reference curve: {'shown' if reference else 'off'}.</p>"]
    if band != "off":
        content.append(f"<p>Shading shows the {band} comparison group's range from the 5th to 95th percentile.</p>")
    for limb in selected:
        content.append(f"<p><b>{limb.title()} walk</b> · {escape(walks[limb]['time'])}</p>")
    if side == "both" and not patient["comparison"]:
        content.append("<p>No same-day numerical comparison is available for these two walks.</p>")
    content.append("<p>"+" ".join(DEFINITIONS.values())+"</p>")
    for index,ch in enumerate(NAMES):
        content.append(f"<section><h2>{escape(CHANNELS[ch][0])}</h2>")
        directions = workspace.cfg["interpretation"]["verified_direction_conventions"][ch]
        content.append("<p>"+escape(graph_guide(ch,directions))+"</p>")
        spec = figure_spec(workspace,person,ch,side,marks,reference,band,window if ch==window_motion else "")
        content.append(go.Figure(spec).to_html(full_html=False,include_plotlyjs=index==0,config={"displaylogo":False}))
        if ch == window_motion and window:
            content.append(f"<p>Highlighted portion of the graph · {escape(CHECK_NAMES[window])}.</p>")
        if side == "both" and ch in patient["comparison"]:
            content.append("<p>"+escape(compare_walks(ch,patient["comparison"][ch]))+"</p>")
        for limb in selected:
            metric = walks[limb]["motions"][ch]
            measurements = " ".join(metric_example(field,metric,ch) for field in DEFINITIONS)
            content.append(f"<p><b>{limb.title()} walk.</b> {escape(measurements)}</p>")
            for obs in walks[limb]["observations"]:
                if ch in obs["channels"]:
                    content.append(f"<p>{escape(obs['observation'])} {escape(obs['next_check'])}</p>")
        rows = walks[selected[0]]["phaseReadings"][ch]
        content.append(f"<h3>Angles at the eight marked points</h3><p>BeyondGait phase reference ranges · page {rows[0]['page']}. "
                       "Each angle comes from the point marked in that walk. Outside gives the distance to the nearest limit.</p>")
        content.append('<div class="scroll"><table><thead><tr><th>Marked phase</th><th>Reference range</th>'+
                       "".join(f"<th>{limb.title()} walk</th>" for limb in selected)+"</tr></thead><tbody>")
        for n,row in enumerate(rows):
            cells=[escape(row["phase"]),escape(row["range"])]
            for limb in selected:
                v=walks[limb]["phaseReadings"][ch][n]
                cells.append(f"{escape(v['reading'])} at {v['pct']:g}% · {escape(v['position'])}")
            content.append("<tr>"+"".join(f"<td>{c}</td>" for c in cells)+"</tr>")
        content.append("</tbody></table></div></section>")
    content.append("<h2>Movement patterns</h2><p>"+escape(METHOD_NOTE)+"</p>")
    for limb in selected:
        content.append(f"<h3>{limb.title()} walk</h3>")
        for rule in walks[limb]["rules"]:
            status={"matched":"Pattern seen","not_matched":"Pattern not seen","not_evaluated":"Could not check"}[rule["status"]]
            content.append(f"<p><b>{escape(rule['title'])} · {status}.</b> {escape(rule['reading'])} {escape(rule['guide'])}</p>")
    content.append("<p>The angles describe movement. They cannot establish muscle weakness or the cause of pain.</p><h2>Sources</h2><ul>")
    for source in corpus():
        title="How the movement checks are defined (software method)" if source["id"]=="MYOGAIT_RULES" else source["title"]
        content.append(f'<li><a href="{escape(source["url"],quote=True)}">{escape(title)}</a></li>')
    content.append("</ul>")
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
            '<title>Better. walking assessment</title><style>body{max-width:1050px;margin:2rem auto;padding:0 1rem;color:#183949;'
            'font:16px/1.5 system-ui}@media(max-width:520px){.scatterlayer .textpoint{display:none}}section{border-top:1px solid #cbdde5;margin-top:2rem}.scroll{overflow:auto}table{border-collapse:collapse;width:100%}'
            'th,td{text-align:left;padding:.5rem;border-bottom:1px solid #dce6ec}th{background:#eef6f7}a{color:#12658b}</style>'
            '</head><body>'+"".join(content)+'</body></html>')
