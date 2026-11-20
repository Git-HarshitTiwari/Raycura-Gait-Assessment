"""Serve the local Better. assessment interface and its read-only result API."""
from functools import lru_cache
from pathlib import Path
from typing import Literal

import plotly
from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .assessment_graphs import assessment_export, figure_spec
from .assessment_pdf import create_assessment_pdf, pdf_download_header
from .assessment_workspace import AssessmentWorkspace
from .config import NAMES, ROOT
from .evidence_assistant import corpus

Side = Literal["both","left","right"]
Band = Literal["off","left","right"]
app = FastAPI(docs_url=None,redoc_url=None,openapi_url=None)
app.add_middleware(TrustedHostMiddleware,allowed_hosts=["127.0.0.1","localhost","[::1]"])


@lru_cache(maxsize=1)
def workspace():
    return AssessmentWorkspace()


@app.middleware("http")
async def private_results(request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


def participant(key):
    store = workspace()
    if key not in store.people:
        raise HTTPException(404,"Unknown participant.")
    return store


@app.get("/api/directory")
def directory():
    store = workspace()
    return {"people":store.directory(),"motions":store.motion_names(),"sources":corpus()}


@app.get("/api/participants/{key}")
def assessment(key: str):
    return participant(key).assessment(key)


@app.get("/api/participants/{key}/graph/{motion}")
def graph(key: str, motion: str, side: Side="both", marks: bool=True,
          reference: bool=True, band: Band="off", window: str=""):
    if motion not in NAMES:
        raise HTTPException(404,"Unknown motion.")
    try:
        return figure_spec(participant(key),key,motion,side,marks,reference,band,window)
    except ValueError as exc:
        raise HTTPException(422,str(exc)) from exc


@app.get("/api/participants/{key}/report")
def report(key: str, side: Side="both", marks: bool=True, reference: bool=True,
           band: Band="off", window: str="", motion: str="hip_flexion"):
    if motion not in NAMES:
        raise HTTPException(404,"Unknown motion.")
    try:
        output = assessment_export(participant(key),key,side,marks,reference,band,window,motion)
    except ValueError as exc:
        raise HTTPException(422,str(exc)) from exc
    return Response(output,media_type="text/html",headers={"Content-Disposition":
                    f'attachment; filename="Better-gait-{key}-{side}.html"'})


@app.get("/api/participants/{key}/report.pdf")
def pdf_report(key: str, side: Side="both", marks: bool=True, reference: bool=True,
               band: Band="off", window: str="", motion: str="hip_flexion"):
    store = participant(key)
    if motion not in NAMES:
        raise HTTPException(404,"Unknown motion.")
    try:
        output = create_assessment_pdf(store,key,side,marks,reference,band,window,motion)
    except ValueError as exc:
        raise HTTPException(422,str(exc)) from exc
    return Response(output,media_type="application/pdf",headers={
        "Content-Disposition":pdf_download_header(store.people[key]["name"])})


class Question(BaseModel):
    question: str = Field(min_length=1,max_length=1000)
    motion: str | None = None


@app.post("/api/recordings/{rid}/explanation")
def explanation(rid: str, body: Question):
    store = workspace()
    if rid not in store.positions:
        raise HTTPException(404,"Unknown recording.")
    if not body.question.strip():
        raise HTTPException(422,"Enter a question about this walk.")
    if body.motion is not None and body.motion not in NAMES:
        raise HTTPException(422,"Choose a listed movement.")
    return store.answer(rid,body.question.strip(),body.motion)


@app.get("/assets-local/plotly.min.js")
def local_plotly():
    return FileResponse(Path(plotly.__file__).parent/"package_data"/"plotly.min.js",media_type="application/javascript")


app.mount("/",StaticFiles(directory=ROOT/"frontend"/"dist",html=True,check_dir=False),name="assessment-ui")
