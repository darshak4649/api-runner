import os
import json
from typing import Dict, List
from app.core.runner import APIRunner, TestPlanError
from app.core.settings import TESTPLAN_DIR, REPORT_DIR
from app.core.logger import get_logger

logger = get_logger(__name__)

runner = APIRunner(testplan_dir=TESTPLAN_DIR, report_dir=REPORT_DIR)


def list_testplans() -> Dict[str, Dict]:

    result = {}
    files = [
        f for f in os.listdir(TESTPLAN_DIR)
        if f.endswith(".json")
    ]
    for filename in files:
        path = os.path.join(TESTPLAN_DIR, filename)

        try:
            with open(path, "r") as f:
                data = json.load(f)

            description = data.get("description")

            # fallback if description missing
            if not description:
                description = filename

            result[filename] = description

        except Exception:
            # corrupted json → still show file
            result[filename] = filename

    return {"testPlans": result}


def validate_testplan(testplan: str):
    return runner.validate_testplan(testplan)


def run_testplan(testplan: str):
    return runner.run_testplan(testplan)


def run_testplan_stream(testplan: str):
    """Generator that yields stream events (step, done) for the given testplan."""
    yield from runner.run_testplan_stream(testplan)


def run_testplan_step(testplan: str, step_index: int):
    """Run the testplan from the start through the given step. Returns that step's result."""
    return runner.run_testplan_step(testplan, step_index)
