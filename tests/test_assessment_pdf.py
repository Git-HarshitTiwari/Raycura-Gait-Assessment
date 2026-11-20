"""Verify the patient-named PDF download and its recording-specific printed values."""
from io import BytesIO
from urllib.parse import unquote

import pytest
from fastapi import HTTPException
from pypdf import PdfReader

from raycura.assessment_api import pdf_report
from raycura.assessment_pdf import SECTIONS, pdf_download_header
from raycura.config import CHANNELS


@pytest.mark.parametrize(("name","expected"),[
    ("Example Patient","Example Patient.pdf"),("Ana María","Ana María.pdf"),
    ("CON","_CON.pdf"),("An/Na: R.","An_Na_ R.pdf"),("...","Assessment.pdf"),
])
def test_safe_patient_filename(name,expected):
    header = pdf_download_header(name)
    assert unquote(header.split("filename*=UTF-8''")[1]) == expected
    assert header.isascii()


@pytest.mark.parametrize("side",["both","left","right"])
def test_printed_assessment_binds_name_sides_ranges_and_charts(side, store):
    person = store.directory()[0]
    selected = ("left","right") if side=="both" else (side,)
    patient = store.assessment(person["key"])
    response = pdf_report(person["key"],side=side,marks=False,band=selected[0],reference=False,
                          motion="hip_flexion",window="myogait_hip_ankle_combination")
    assert response.media_type=="application/pdf" and response.body.startswith(b"%PDF-")
    assert unquote(response.headers["Content-Disposition"].split("filename*=UTF-8''")[1])==person["name"]+".pdf"
    pdf = PdfReader(BytesIO(response.body))
    assert pdf.metadata.title == person["name"]
    pages = [" ".join(page.extract_text().split()) for page in pdf.pages]
    for i,(page,text) in enumerate(zip(pdf.pages,pages),1):
        assert person["name"] in text and f"Page {i} / {len(pages)} " in text
        assert float(page.mediabox.width)==pytest.approx(595.28,abs=.1)
    text = " ".join(pages)
    assert text.count("Gait cycle (%)")==10
    assert "Interpretation and sources" in pages[-1] and "myogait movement-check definitions" in pages[-1]
    assert "Dots on each curve" not in text and "Dotted lines show" not in text
    assert "Highlighted interval 60" in text and f"{selected[0]}-side comparison group" in text
    assert ("Comparing the two walks" in text)==(side=="both")
    for region, channels in SECTIONS:
        assert region+" kinematics" in text
        for ch in channels:
            assert CHANNELS[ch][0] in text
            reads = [patient["walks"][s]["phaseReadings"][ch] for s in selected]
            for marks in zip(*reads,strict=True):
                row = " ".join([marks[0]["phase"],*[m["reading"] for m in marks],marks[0]["range"]])
                assert row in text
    if side!="both":
        assert ("Right walk" if side=="left" else "Left walk") not in text


def test_pdf_rejects_mismatched_selection(store):
    key=store.directory()[0]["key"]
    with pytest.raises(HTTPException) as exc:
        pdf_report(key,side="right",band="left")
    assert exc.value.status_code==422
    with pytest.raises(HTTPException) as exc:
        pdf_report("missing")
    assert exc.value.status_code==404
