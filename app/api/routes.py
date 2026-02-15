import asyncio
import json
import os
import queue
from typing import Dict

from fastapi import HTTPException
from fastapi.responses import StreamingResponse

from app.service import service as testplan_service
from app.core.runner import TestPlanError
from app.core.settings import TESTPLAN_DIR, REPORT_DIR
from app.routes import router

@router.get("", response_model=Dict[str, Dict])
def list_testplans():
    """
    Retrieve all available test plans.

    Returns a mapping of testplan filenames to their human-readable description.
    The description is extracted from the `description` field inside each
    testplan JSON file. If missing or invalid, the filename is used as fallback.

    Response:
        {
            "testPlans": {
                "login.json": "User Login Flow",
                "order.json": "Create Order API"
            }
        }
    """
    return testplan_service.list_testplans()

@router.get("/{testplan}")
def get_testplan(testplan: str):
    """
    Fetch raw contents of a testplan.

    Returns the full JSON definition of the specified testplan exactly as stored
    on disk. Useful for previewing or debugging test configuration.

    Path Parameters:
        testplan: Name of the testplan file (e.g. `login.json`)

    Returns:
        JSON object representing the testplan contents

    Raises:
        404 - Testplan file not found
    """
    path = os.path.join(TESTPLAN_DIR, testplan)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Testplan not found")

    with open(path) as f:
        return json.load(f)

@router.get("/{testplan}/validate")
def validate_testplan(testplan: str):
    """
    Validate the structure and configuration of a testplan.

    Path Parameters:
        testplan: Name of the testplan file (e.g. `login.json`)

    Returns:
        Validation result including detected errors, missing fields,
        or dependency issues.

    Raises:
        400 - Invalid testplan format or validation failure
        404 - Testplan not found
    """
    try:
        return testplan_service.validate_testplan(testplan)
    except TestPlanError as e:
        raise HTTPException(status_code=400, detail=e.message)

@router.post("/{testplan}/run")
def run_testplan(testplan: str):
    """
    Execute a testplan.

    Runs all requests defined in the testplan sequentially and generates
    execution reports.

    Path Parameters:
        testplan: Name of the testplan file (e.g. `login.json`)

    Returns:
        {
            "message": "Execution completed",
            "json_report": "<path-to-json-report>",
            "html_report": "<path-to-html-report>"
        }

    Raises:
        400 - Testplan execution failure or runtime validation error
        404 - Testplan not found
    """
    try:
        report_paths = testplan_service.run_testplan(testplan)
        return {
            "message": "Execution completed",
            "json_report": report_paths["json"],
            "html_report": report_paths["html"],
        }
    except TestPlanError as e:
        raise HTTPException(status_code=400, detail=e.message)


@router.post("/{testplan}/run/stream")
def run_testplan_stream(testplan: str):
    """
    Execute a testplan and stream progress as Server-Sent Events.
    Each step yields a "step" event; final "done" event includes report and report paths.
    """
    def run_in_thread(q: queue.Queue):
        try:
            for event in testplan_service.run_testplan_stream(testplan):
                q.put(event)
        except Exception as e:
            q.put({"type": "error", "detail": str(e)})
        finally:
            q.put(None)

    async def event_generator():
        q = queue.Queue()
        loop = asyncio.get_event_loop()
        loop.run_in_executor(None, lambda: run_in_thread(q))
        while True:
            event = await loop.run_in_executor(None, q.get)
            if event is None:
                break
            if event.get("type") == "error":
                yield f"data: {json.dumps(event)}\n\n"
                break
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/{testplan}/run/step/{step_index}")
def run_testplan_step(testplan: str, step_index: int):
    """
    Run the testplan from the start through the given step (0-based index).
    Runs all previous steps first so variables are available, then returns the result of the requested step.
    """
    try:
        return testplan_service.run_testplan_step(testplan, step_index)
    except TestPlanError as e:
        raise HTTPException(status_code=400, detail=e.message)