import os
import json
from typing import List, Dict

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from runner import APIRunner, TestPlanError

app = FastAPI(title="API Testplan Runner")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TESTPLAN_DIR = os.path.join(BASE_DIR, "testplans")
REPORT_DIR = os.path.join(BASE_DIR, "reports")

os.makedirs(os.path.join(REPORT_DIR, "json"), exist_ok=True)
os.makedirs(os.path.join(REPORT_DIR, "html"), exist_ok=True)

# Serve UI & reports
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/reports", StaticFiles(directory="reports"), name="reports")


@app.get("/")
def home():
    return {
        "message": "API Testplan Runner is running",
        "ui": "/static/index.html"
    }


@app.get("/testplans", response_model=Dict[str, List[str]])
def list_testplans():
    runner = APIRunner(testplan_dir=TESTPLAN_DIR, report_dir=REPORT_DIR)
    return {"available_testplans": runner.list_testplans()}


@app.get("/testplans/{testplan}/validate")
def validate_testplan(testplan: str):
    runner = APIRunner(testplan_dir=TESTPLAN_DIR, report_dir=REPORT_DIR)

    try:
        result = runner.validate_testplan(testplan)
        return result
    except TestPlanError as e:
        raise HTTPException(status_code=400, detail=e.message)


@app.post("/testplans/{testplan}/run")
def run_testplan(testplan: str):
    runner = APIRunner(testplan_dir=TESTPLAN_DIR, report_dir=REPORT_DIR)

    try:
        report_paths = runner.run_testplan(testplan)
        return {
            "message": "Execution completed",
            "json_report": report_paths["json"],
            "html_report": report_paths["html"],
        }
    except TestPlanError as e:
        raise HTTPException(status_code=400, detail=e.message)

@app.get("/testplans/{testplan}")
def get_testplan(testplan: str):
    path = os.path.join(TESTPLAN_DIR, testplan)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Testplan not found")

    with open(path) as f:
        return json.load(f)

