"""Lay out the chosen walking assessment as a framed, printable A4 report."""
import io
import re
import unicodedata
from datetime import datetime
from urllib.parse import quote
from xml.sax.saxutils import escape, quoteattr

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .assessment_graphs import figure_spec
from .assessment_workspace import SIDES
from .config import CHANNELS, ROOT
from .patient_language import CYCLE_GUIDE, DEFINITIONS, METHOD_NOTE, degrees
from .pdf_motion_chart import MotionChart
from .evidence_assistant import corpus

PW, PH = A4
MARGIN = 32
WIDTH = PW - 2*MARGIN - 12
INK, TEAL, BORDER, PALE = "#193E42", "#126D66", "#B6CFC9", "#EDF6F3"
SECTIONS = (
    ("Pelvis", ("pelvic_tilt", "pelvic_obliquity", "pelvic_rotation")),
    ("Hip", ("hip_flexion", "hip_abduction", "hip_rotation")),
    ("Knee", ("knee_flexion", "knee_abduction", "knee_rotation")),
    ("Ankle", ("ankle_dorsiflexion",)),
)
pdfmetrics.registerFont(TTFont("AssessmentSans","Vera.ttf"))
pdfmetrics.registerFont(TTFont("AssessmentBold","VeraBd.ttf"))


def pdf_download_header(name):
    """Use the display name while protecting Windows filenames and HTTP headers."""
    stem = "".join(ch for ch in unicodedata.normalize("NFC",name)
                   if unicodedata.category(ch) not in {"Cc","Cf"})
    stem = re.sub(r'[<>:"/\\|?*]', "_", stem).strip(" .")[:110].rstrip(" .") or "Assessment"
    if re.match(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)",stem,re.I):
        stem = "_" + stem
    fallback = unicodedata.normalize("NFKD",stem).encode("ascii","ignore").decode().strip(" .") or "Assessment"
    return f"""attachment; filename="{fallback}.pdf"; filename*=UTF-8''{quote(stem+".pdf",safe="")}"""


def style(name, size, leading, bold=False, color=INK, **attrs):
    return ParagraphStyle(name,fontName="AssessmentBold" if bold else "AssessmentSans",
                          fontSize=size,leading=leading,textColor=colors.HexColor(color),**attrs)


TITLE = style("Title",24,29,True,spaceAfter=9,keepWithNext=True)
SUBHEAD = style("Section",12.5,16,True,TEAL,spaceBefore=9,spaceAfter=4,keepWithNext=True)
BODY = style("Body",9.5,13.5,spaceAfter=5)
SMALL = style("Note",8.5,12,color="#425D64",spaceAfter=4)
CELL = style("Cell",8.2,10.5)
HEAD = style("Column",8.2,10.5,True,TEAL)


def para(text, fmt=BODY):
    return Paragraph(escape(str(text)),fmt)


def table(headings, rows, widths, vertical_padding=3.5):
    data = [[para(s,HEAD) for s in headings]]
    data.extend([s if isinstance(s,Paragraph) else para(s,CELL) for s in row] for row in rows)
    obj = Table(data, colWidths=[WIDTH*f for f in widths], repeatRows=1, hAlign="LEFT")
    obj.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0),colors.HexColor(PALE)),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,colors.HexColor("#FAFCFB")]),
        ("GRID",(0,0),(-1,-1),.42,colors.HexColor(BORDER)),("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("LEFTPADDING",(0,0),(-1,-1),6),("RIGHTPADDING",(0,0),(-1,-1),6),
        ("TOPPADDING",(0,0),(-1,-1),vertical_padding),("BOTTOMPADDING",(0,0),(-1,-1),vertical_padding),
    ]))
    return obj


class NumberedCanvas(Canvas):
    """Fill the total-page field after the content has been laid out."""
    def save(self):
        self.beginForm("TotalPages",0,-3,24,10)
        self.setFont("Helvetica",8)
        self.setFillColor(colors.HexColor(INK))
        self.drawString(0,0,str(self.getPageNumber()-1))
        self.endForm()
        super().save()


def page_frame(c, doc):
    c.saveState()
    c.setStrokeColor(colors.HexColor(BORDER))
    c.setLineWidth(.8)
    c.roundRect(17,17,PW-34,PH-34,6,stroke=1,fill=0)
    c.drawImage(str(ROOT/"frontend/public/better-logo.png"),37,PH-49,width=72,height=19,
                mask="auto",preserveAspectRatio=True)
    c.setFont("Helvetica",9)
    c.setFillColor(colors.HexColor(TEAL))
    c.drawRightString(PW-38,PH-42,"Walking assessment")
    c.line(37,PH-58,PW-37,PH-58)
    c.line(37,49,PW-37,49)
    c.setFillColor(colors.HexColor(INK))
    c.setFont("Helvetica",8)
    footer = doc.title
    while len(footer)>1 and c.stringWidth(footer,"Helvetica",8)>WIDTH-85:
        footer = footer[:-2]+"…"
    c.drawString(38,32,footer)
    c.drawRightString(PW-48,32,f"Page {doc.page} /")
    c.translate(PW-46,32)
    c.doForm("TotalPages")
    c.restoreState()


def phase_table(walks, sides, motion):
    values = [walks[side]["phaseReadings"][motion] for side in sides]
    emphasis = style("Outside",8.2,10.5,True)
    rows = [[phase[0]["phase"], *[para(p["reading"],emphasis) if p["gap"] else p["reading"] for p in phase], phase[0]["range"]]
            for phase in zip(*values, strict=True)]
    widths = (.17,.235,.235,.36) if len(sides)==2 else (.27,.31,.42)
    return table(["Marked phase",*[s.title()+" walk" for s in sides],"Printed reference range"],rows,widths,vertical_padding=2)


def cover_and_phases(patient, sides, marks, reference, band):
    walks = patient["walks"]
    title = "Bilateral gait assessment" if len(sides)==2 else sides[0].title()+" gait assessment"
    story = [para(title,TITLE),para(patient["name"],style("Patient",19,24,True,spaceAfter=15)),
             para("Recorded walks",SUBHEAD)]
    captures = [[s.title(),datetime.fromisoformat(walks[s]["time"]).strftime("%d %b %Y at %H:%M")] for s in sides]
    story.append(table(["Side","Recorded on"],captures,(.28,.72)))
    if len(sides)==2:
        story.extend([Spacer(1,8),para("The left and right sides were recorded in separate walks. Each curve covers one recorded cycle.")])
    story.append(para("Assessment overview",SUBHEAD))
    for s in sides:
        rules = walks[s]["rules"]
        seen = sum(r["status"]=="matched" for r in rules)
        checked = sum(r["status"]!="not_evaluated" for r in rules)
        story.append(para(f"{s.title()} walk. {seen} of {checked} evaluated movement checks matched."))
        if checked < len(rules):
            story.append(para(f"{len(rules)-checked} checks could not be evaluated."))
    story.append(para("Largest difference at a marked point",SUBHEAD))
    for s in sides:
        available = [(ch,row) for ch,rows in walks[s]["phaseReadings"].items() for row in rows if row["gap"] is not None]
        if available:
            ch,row = max(available,key=lambda item:item[1]["gap"])
            if row["gap"] > 0:
                story.append(para(f"{s.title()} walk. {CHANNELS[ch][0]} at {row['phase']}: {row['reading']}, {row['position'].lower()} the printed range ({row['range']})."))
            else:
                story.append(para(f"{s.title()} walk. All available marked angles were within their printed ranges."))
    story.extend([para("How to read the measurements",SUBHEAD),
                  table(["Measurement","What it tells you"],[
                      ["Range of motion",DEFINITIONS["rom_deg"]],
                      ["Overall curve difference (RMS)",DEFINITIONS["rms_difference_deg"]+" The comparator here is the reference curve."],
                      ["Average offset",DEFINITIONS["mean_offset_deg"]]],(.31,.69)),
                  PageBreak(),para("Gait cycle phase analysis",TITLE),para(CYCLE_GUIDE),
                  para("These positions were marked manually for each recording. They show where to read the angles in the phase tables.")])
    phases = zip(*(walks[s]["marks"] for s in sides),strict=True)
    phase_rows = [[phase[0]["name"],*[f"{mark['pct']:g}%" for mark in phase]] for phase in phases]
    story.append(table(["Marked phase",*[s.title()+" cycle position" for s in sides]],phase_rows,
                       (.44,.28,.28) if len(sides)==2 else (.5,.5)))
    story.append(para("Reading the graphs",SUBHEAD))
    story.append(para("The vertical axis gives the angle in degrees. Read across the graph from the beginning to the end of the recorded cycle."))
    if marks:
        story.append(para("Dots on each curve show the eight manually marked positions."))
    if reference:
        story.append(para("Dotted lines show the reference averages used for the numerical comparisons."))
    if band!="off":
        story.append(para(f"Blue shading shows the middle 90% of the {band}-side comparison group at each point in the cycle."))
    if len(sides)==2 and not patient["comparison"]:
        story.append(para("No same-day numerical comparison is available for these two walks."))
    elif len(sides)==2:
        story.append(para("Comparing the two walks",SUBHEAD))
        story.append(para("A positive range difference means the right side moved through a larger range. The curve gap compares the two walks at matching cycle positions.",SMALL))
        comparisons = [[CHANNELS[ch][0],degrees(pair["rangeDifference"]),degrees(pair["rms"])]
                       for ch,pair in patient["comparison"].items()]
        story.append(table(["Movement","Range difference (right minus left)","Overall curve gap (RMS)"],
                           comparisons,(.43,.32,.25)))
    return story


def metric_line(side, metric):
    labels = (("Range","rom_deg"),("Curve difference","rms_difference_deg"),("Offset","mean_offset_deg"))
    parts = [side.title()+" walk"]
    for label, key in labels:
        value = metric[key]
        parts.append(label+" "+("unavailable" if value is None else degrees(value)))
    return para("   ·   ".join(parts),SMALL)


def add_findings(story, patient, sides):
    story.extend([PageBreak(),para("Assessment findings",TITLE),para(METHOD_NOTE)])
    for s in sides:
        walk = patient["walks"][s]
        story.append(para(s.title()+" walk",SUBHEAD))
        rows = []
        for rule in walk["rules"]:
            decision = {"matched":"Seen","not_matched":"Not seen","not_evaluated":"Could not check"}[rule["status"]]
            rows.append([rule["title"],decision,rule["reading"]+" "+rule["guide"]])
        story.append(table(["Movement check","Result","Recorded evidence"],rows,(.26,.14,.60),
                           vertical_padding=2.5))
        for card in walk["observations"]:
            story.append(para(card["observation"]+" "+card["next_check"],SMALL))
    notes = [para("Interpretation and sources",SUBHEAD),
             para("A movement pattern or an angle outside a printed interval identifies a feature to review. The angles alone cannot establish pain, muscle weakness or its cause.",SMALL),
             para("Phase intervals are from the BeyondGait report tables for pelvis, hip, knee and ankle (pages 4, 6, 8 and 9).",SMALL)]
    for source in corpus():
        title = "myogait movement-check definitions" if source["id"]=="MYOGAIT_RULES" else source["title"]
        notes.append(Paragraph('<link href='+quoteattr(source["url"])+' color="'+TEAL+'">'+escape(title)+'</link>',SMALL))
    story.append(KeepTogether(notes))


def create_assessment_pdf(workspace, person, side, marks, reference, band, window="", motion="hip_flexion"):
    """Render saved measurements, curves and decisions for exactly the chosen patient and sides."""
    patient = workspace.assessment(person)
    sides = SIDES if side=="both" else (side,)
    walks = patient["walks"]
    stream = io.BytesIO()
    doc = SimpleDocTemplate(stream,pagesize=A4,leftMargin=MARGIN,rightMargin=MARGIN,
                            topMargin=68,bottomMargin=58,title=patient["name"],author="Better.")
    story = cover_and_phases(patient,sides,marks,reference,band)
    for region, channels in SECTIONS:
        story.extend([PageBreak(),para(region+" kinematics",TITLE)])
        for ch in channels:
            fig = figure_spec(workspace,person,ch,side,marks,reference,band,window if ch==motion else "")
            block = [para(CHANNELS[ch][0],SUBHEAD),MotionChart(fig)]
            block.extend(metric_line(s,walks[s]["motions"][ch]) for s in sides)
            if ch==motion and window:
                rule = next(r for r in walks[sides[0]]["rules"] if r["id"]==window)
                start,end = rule["windows"][ch]
                block.append(para(f"Highlighted interval {start}–{end}% for the check “{rule['title']}”.",SMALL))
            story.append(KeepTogether(block))
        if len(channels)>1:
            story.extend([PageBreak(),para(region+" phase angles",TITLE)])
        story.append(para("Recorded angles and physiological corridors",SUBHEAD))
        story.append(para("Bold readings fall outside the printed interval for that movement at the marked phase.",SMALL))
        for ch in channels:
            story.extend([para(CHANNELS[ch][0],SUBHEAD),phase_table(walks,sides,ch)])
    add_findings(story,patient,sides)
    doc.build(story,onFirstPage=page_frame,onLaterPages=page_frame,canvasmaker=NumberedCanvas)
    return stream.getvalue()
