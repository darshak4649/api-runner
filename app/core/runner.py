import os
import json
import re
import time
import logging
from typing import Any, Dict, List, Set, Optional

import requests

# ---------- Logger ----------
logger = logging.getLogger("API-Runner.runner")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)


# ---------- Domain Exception ----------
class TestPlanError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class APIRunner:
    def __init__(self, testplan_dir: str, report_dir: str):
        self.testplan_dir = testplan_dir
        self.json_report_dir = os.path.join(report_dir, "json")
        self.html_report_dir = os.path.join(report_dir, "html")

    # ===================== PUBLIC API (USED BY app.py) =====================

    def validate_testplan(self, testplan: str) -> Dict[str, Any]:
        path = self._get_testplan_path(testplan)
        data = self._load_json(path)

        errors: List[str] = []

        if "globals" not in data:
            errors.append("Missing 'globals' section")

        if "requests" not in data or not isinstance(data["requests"], list):
            errors.append("Missing or invalid 'requests' list")

        defined_vars = set(data.get("globals", {}).keys())

        for i, req in enumerate(data.get("requests", [])):
            name = req.get("name", f"<unnamed-{i}>")

            if "method" not in req:
                errors.append(f"Request '{name}' missing 'method'")

            if "url" not in req:
                errors.append(f"Request '{name}' missing 'url'")

            used_vars = self.extract_variables_static(req)

            for v in used_vars:
                if v not in defined_vars:
                    errors.append(f"Undefined variable '{v}' in request '{name}'")

            for var in req.get("save", {}).keys():
                defined_vars.add(var)

        if errors:
            logger.warning("Validation failed for %s: %s", testplan, errors)
            return {"valid": False, "errors": errors}

        logger.info("Testplan validated successfully: %s", testplan)
        return {"valid": True, "message": "Testplan is valid"}

    def run_testplan(self, testplan: str) -> Dict[str, str]:
        path = self._get_testplan_path(testplan)
        runner = _ExecutionEngine(path)

        logger.info("Executing testplan: %s", testplan)

        report = runner.run_with_report()

        json_path = os.path.join(self.json_report_dir, f"{testplan}_report.json")
        html_path = os.path.join(self.html_report_dir, f"{testplan}_report.html")

        with open(json_path, "w") as f:
            json.dump(report, f, indent=2)

        with open(html_path, "w") as f:
            f.write(_ExecutionEngine.generate_html_report(report))

        logger.info("Execution completed for %s", testplan)

        return {
            "json": f"/reports/json/{testplan}_report.json",
            "html": f"/reports/html/{testplan}_report.html",
        }

    def run_testplan_stream(self, testplan: str):
        """Yields events: {"type": "step", "index": i, "result": entry} then {"type": "done", "report": ..., "json_report": ..., "html_report": ...}."""
        path = self._get_testplan_path(testplan)
        engine = _ExecutionEngine(path)
        for event in engine.run_with_stream():
            if event.get("type") == "done":
                report = event["report"]
                json_path = os.path.join(self.json_report_dir, f"{testplan}_report.json")
                html_path = os.path.join(self.html_report_dir, f"{testplan}_report.html")
                with open(json_path, "w") as f:
                    json.dump(report, f, indent=2)
                with open(html_path, "w") as f:
                    f.write(_ExecutionEngine.generate_html_report(report))
                event["json_report"] = f"/reports/json/{testplan}_report.json"
                event["html_report"] = f"/reports/html/{testplan}_report.html"
            yield event

    def run_testplan_step(self, testplan: str, step_index: int) -> Dict[str, Any]:
        """Run the given step. If only globals needed, run standalone; else run only the steps that provide required variables."""
        path = self._get_testplan_path(testplan)
        data = self._load_json(path)
        req_list = data.get("requests", [])
        if step_index < 0 or step_index >= len(req_list):
            raise TestPlanError(f"Invalid step index: {step_index}")
        req = req_list[step_index]
        used_vars = self.extract_variables_static(req)
        used_stripped = {str(v).strip() for v in used_vars}
        globals_only = set(data.get("globals", {}).keys())
        if used_stripped <= globals_only:
            engine = _ExecutionEngine(path)
            return engine.run_single_step(step_index)
        step_indices = self._minimal_steps_for_step(data, step_index)
        engine = _ExecutionEngine(path)
        return engine.run_only_steps(step_indices, step_index)

    # ===================== INTERNAL HELPERS =====================

    def _get_testplan_path(self, testplan: str) -> str:
        path = os.path.join(self.testplan_dir, testplan)
        if not os.path.exists(path):
            logger.error("Testplan not found: %s", testplan)
            raise TestPlanError("Testplan not found")
        return path

    def _load_json(self, path: str) -> Dict[str, Any]:
        try:
            with open(path) as f:
                return json.load(f)
        except Exception as e:
            logger.error("Invalid JSON in %s: %s", path, str(e))
            raise TestPlanError(f"Invalid JSON: {str(e)}")

    @staticmethod
    def extract_variables_static(obj: Any) -> Set[str]:
        text = json.dumps(obj)
        return set(re.findall(r"\{\{(.*?)\}\}", text))

    @staticmethod
    def _minimal_steps_for_step(data: Dict[str, Any], step_index: int) -> List[int]:
        """Return sorted list of step indices that must run so step_index has all variables it needs (only providers, not full sequence)."""
        req_list = data.get("requests", [])
        globals_keys = set(data.get("globals", {}).keys())
        # var -> step index that saves it (first provider)
        var_to_step: Dict[str, int] = {}
        for i, req in enumerate(req_list):
            for var in req.get("save", {}).keys():
                if var not in var_to_step:
                    var_to_step[var] = i
        required: Set[int] = {step_index}
        while True:
            added: Set[int] = set()
            for i in required:
                used = APIRunner.extract_variables_static(req_list[i])
                used_stripped = {str(v).strip() for v in used}
                for v in used_stripped:
                    if v not in globals_keys and v in var_to_step:
                        added.add(var_to_step[v])
            if added <= required:
                break
            required |= added
        return sorted(required)

class _ExecutionEngine:
    def __init__(self, config_path: str):
        with open(config_path) as f:
            self.config: Dict[str, Any] = json.load(f)

        self.variables: Dict[str, Any] = dict(self.config.get("globals", {}))
        logger.info("Loaded globals: %s", self.variables)

    def resolve_vars(self, obj: Any) -> Any:
        if isinstance(obj, str):
            matches = re.findall(r"\{\{(.*?)\}\}", obj)
            for var in matches:
                if var not in self.variables:
                    raise TestPlanError(f"Undefined variable: {var}")
                obj = obj.replace(f"{{{{{var}}}}}", str(self.variables[var]))
            return obj

        if isinstance(obj, dict):
            return {k: self.resolve_vars(v) for k, v in obj.items()}

        if isinstance(obj, list):
            return [self.resolve_vars(v) for v in obj]

        return obj

    @staticmethod
    def extract_json_value(data: Any, path: str) -> Optional[Any]:
        keys = path.split(".")
        for key in keys:
            if isinstance(data, dict) and key in data:
                data = data[key]
            else:
                return None
        return data

    def save_variables(self, response_json: Dict[str, Any], save_config: Dict[str, str]) -> None:
        for var_name, json_path in save_config.items():
            value = self.extract_json_value(response_json, json_path)
            if value is None:
                raise TestPlanError(
                    f"Failed to extract '{json_path}' for variable '{var_name}'"
                )
            self.variables[var_name] = value
            logger.info("Saved variable %s = %s", var_name, value)

    def validate_response(self, response: requests.Response, validation: Dict[str, Any]) -> None:
        expected_status = validation.get("status_code")

        if expected_status and response.status_code != expected_status:
            raise TestPlanError(
                f"Expected status {expected_status}, got {response.status_code}"
            )

        if "fields_present" in validation:
            try:
                response_json = response.json()
            except Exception:
                raise TestPlanError("Response is not valid JSON")

            for field in validation["fields_present"]:
                if self.extract_json_value(response_json, field) is None:
                    raise TestPlanError(f"Missing expected field: {field}")

    @staticmethod
    def generate_html_report(report: Dict[str, Any]) -> str:
        rows = ""

        for r in report["results"]:
            color = "green" if r["status"] == "PASS" else "red"

            rows += f"""
            <tr>
                <td>{r['name']}</td>
                <td>{r['method']}</td>
                <td>{r['url']}</td>
                <td style="color:{color}">{r['status']}</td>
                <td>{r['response_code']}</td>
                <td><pre>{json.dumps(r['response_sample'], indent=2)}</pre></td>
            </tr>
            """

        return f"""
        <html>
        <head>
            <title>API Test Report</title>
        </head>
        <body>
            <h2>API Test Execution Report</h2>
            <table border="1">
                <tr>
                    <th>Name</th>
                    <th>Method</th>
                    <th>URL</th>
                    <th>Status</th>
                    <th>HTTP Code</th>
                    <th>Response</th>
                </tr>
                {rows}
            </table>
        </body>
        </html>
        """

    def run_with_stream(self):
        results: List[Dict[str, Any]] = []
        start_time = time.time()

        for i, req in enumerate(self.config.get("requests", [])):
            entry = {
                "name": req.get("name"),
                "method": req.get("method"),
                "url": None,
                "request_headers": None,
                "request_body": None,
                "status": "PASS",
                "response_code": None,
                "response_headers": None,
                "response_sample": None,
                "error": None,
            }

            try:
                url = self.resolve_vars(req["url"])
                entry["url"] = url
                resolved_headers = self.resolve_vars(req.get("headers", {}))
                resolved_body = self.resolve_vars(req.get("body"))
                entry["request_headers"] = resolved_headers
                entry["request_body"] = resolved_body

                logger.info("Executing %s %s", req["method"], url)

                response = requests.request(
                    method=req["method"].upper(),
                    url=url,
                    headers=resolved_headers,
                    json=resolved_body,
                )

                entry["response_code"] = response.status_code
                entry["response_headers"] = dict(response.headers) if response.headers else None

                try:
                    entry["response_sample"] = response.json()
                except Exception:
                    entry["response_sample"] = response.text[:500]

                if "validate" in req:
                    self.validate_response(response, req["validate"])

                if "save" in req:
                    self.save_variables(response.json(), req["save"])

            except Exception as e:
                entry["status"] = "FAIL"
                entry["error"] = str(e)
                logger.error("Request failed: %s", str(e))

            results.append(entry)
            yield {"type": "step", "index": i, "result": entry}

        report = {
            "testplan": self.config.get("name", "unknown"),
            "total_requests": len(results),
            "passed": sum(1 for r in results if r["status"] == "PASS"),
            "failed": sum(1 for r in results if r["status"] == "FAIL"),
            "execution_time_sec": round(time.time() - start_time, 2),
            "results": results,
            "final_variables": self.variables,
        }
        yield {"type": "done", "report": report}

    def run_up_to_step(self, step_index: int) -> Dict[str, Any]:
        """Run requests from 0 through step_index (inclusive). Returns the result for that step."""
        req_list = self.config.get("requests", [])
        if step_index < 0 or step_index >= len(req_list):
            raise TestPlanError(f"Invalid step index: {step_index}")
        results: List[Dict[str, Any]] = []
        for i, req in enumerate(req_list):
            if i > step_index:
                break
            entry = {
                "name": req.get("name"),
                "method": req.get("method"),
                "url": None,
                "request_headers": None,
                "request_body": None,
                "status": "PASS",
                "response_code": None,
                "response_headers": None,
                "response_sample": None,
                "error": None,
            }
            try:
                url = self.resolve_vars(req["url"])
                entry["url"] = url
                resolved_headers = self.resolve_vars(req.get("headers", {}))
                resolved_body = self.resolve_vars(req.get("body"))
                entry["request_headers"] = resolved_headers
                entry["request_body"] = resolved_body
                logger.info("Executing %s %s", req["method"], url)
                response = requests.request(
                    method=req["method"].upper(),
                    url=url,
                    headers=resolved_headers,
                    json=resolved_body,
                )
                entry["response_code"] = response.status_code
                entry["response_headers"] = dict(response.headers) if response.headers else None
                try:
                    entry["response_sample"] = response.json()
                except Exception:
                    entry["response_sample"] = response.text[:500]
                if "validate" in req:
                    self.validate_response(response, req["validate"])
                if "save" in req:
                    self.save_variables(response.json(), req["save"])
            except Exception as e:
                entry["status"] = "FAIL"
                entry["error"] = str(e)
                logger.error("Request failed: %s", str(e))
            results.append(entry)
        return {"index": step_index, "result": results[step_index], "results_so_far": results}

    def run_single_step(self, step_index: int) -> Dict[str, Any]:
        """Run only the request at step_index (no previous steps). Uses only globals. Use when step has no dependency on earlier steps."""
        req_list = self.config.get("requests", [])
        if step_index < 0 or step_index >= len(req_list):
            raise TestPlanError(f"Invalid step index: {step_index}")
        req = req_list[step_index]
        entry = {
            "name": req.get("name"),
            "method": req.get("method"),
            "url": None,
            "request_headers": None,
            "request_body": None,
            "status": "PASS",
            "response_code": None,
            "response_headers": None,
            "response_sample": None,
            "error": None,
        }
        try:
            url = self.resolve_vars(req["url"])
            entry["url"] = url
            resolved_headers = self.resolve_vars(req.get("headers", {}))
            resolved_body = self.resolve_vars(req.get("body"))
            entry["request_headers"] = resolved_headers
            entry["request_body"] = resolved_body
            logger.info("Executing %s %s (standalone)", req["method"], url)
            response = requests.request(
                method=req["method"].upper(),
                url=url,
                headers=resolved_headers,
                json=resolved_body,
            )
            entry["response_code"] = response.status_code
            entry["response_headers"] = dict(response.headers) if response.headers else None
            try:
                entry["response_sample"] = response.json()
            except Exception:
                entry["response_sample"] = response.text[:500]
            if "validate" in req:
                self.validate_response(response, req["validate"])
            if "save" in req:
                self.save_variables(response.json(), req["save"])
        except Exception as e:
            entry["status"] = "FAIL"
            entry["error"] = str(e)
            logger.error("Request failed: %s", str(e))
        return {"index": step_index, "result": entry, "results_so_far": [entry]}

    def run_only_steps(self, step_indices: List[int], target_step_index: int) -> Dict[str, Any]:
        """Run only the given step indices in order (e.g. minimal deps), then return the result for target_step_index."""
        req_list = self.config.get("requests", [])
        results_by_index: Dict[int, Dict[str, Any]] = {}
        for i in step_indices:
            if i < 0 or i >= len(req_list):
                continue
            req = req_list[i]
            entry = {
                "name": req.get("name"),
                "method": req.get("method"),
                "url": None,
                "request_headers": None,
                "request_body": None,
                "status": "PASS",
                "response_code": None,
                "response_headers": None,
                "response_sample": None,
                "error": None,
            }
            try:
                url = self.resolve_vars(req["url"])
                entry["url"] = url
                resolved_headers = self.resolve_vars(req.get("headers", {}))
                resolved_body = self.resolve_vars(req.get("body"))
                entry["request_headers"] = resolved_headers
                entry["request_body"] = resolved_body
                logger.info("Executing %s %s", req["method"], url)
                response = requests.request(
                    method=req["method"].upper(),
                    url=url,
                    headers=resolved_headers,
                    json=resolved_body,
                )
                entry["response_code"] = response.status_code
                entry["response_headers"] = dict(response.headers) if response.headers else None
                try:
                    entry["response_sample"] = response.json()
                except Exception:
                    entry["response_sample"] = response.text[:500]
                if "validate" in req:
                    self.validate_response(response, req["validate"])
                if "save" in req:
                    self.save_variables(response.json(), req["save"])
            except Exception as e:
                entry["status"] = "FAIL"
                entry["error"] = str(e)
                logger.error("Request failed: %s", str(e))
            results_by_index[i] = entry
        if target_step_index not in results_by_index:
            raise TestPlanError(f"Step {target_step_index} was not run")
        return {
            "index": target_step_index,
            "result": results_by_index[target_step_index],
            "results_so_far": [results_by_index[j] for j in step_indices if j in results_by_index],
        }

    def run_with_report(self) -> Dict[str, Any]:
        report = None
        for event in self.run_with_stream():
            if event.get("type") == "done":
                report = event["report"]
                return report
        return {}
