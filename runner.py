import os
import json
import re
import time
import logging
from typing import Any, Dict, List, Set, Optional

import requests

# ---------- Logger ----------
logger = logging.getLogger("api-runner.runner")
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

    def list_testplans(self) -> List[str]:
        files = [
            f for f in os.listdir(self.testplan_dir)
            if f.endswith(".json")
        ]
        logger.info("Available testplans: %s", files)
        return files

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


# ===================== EXECUTION ENGINE (PRIVATE) =====================

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

    def run_with_report(self) -> Dict[str, Any]:
        results: List[Dict[str, Any]] = []
        start_time = time.time()

        for req in self.config.get("requests", []):
            entry = {
                "name": req.get("name"),
                "method": req.get("method"),
                "url": None,
                "status": "PASS",
                "response_code": None,
                "response_sample": None,
                "error": None,
            }

            try:
                url = self.resolve_vars(req["url"])
                entry["url"] = url

                logger.info("Executing %s %s", req["method"], url)

                response = requests.request(
                    method=req["method"].upper(),
                    url=url,
                    headers=self.resolve_vars(req.get("headers", {})),
                    json=self.resolve_vars(req.get("body")),
                )

                entry["response_code"] = response.status_code

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

        return {
            "testplan": self.config.get("name", "unknown"),
            "total_requests": len(results),
            "passed": sum(1 for r in results if r["status"] == "PASS"),
            "failed": sum(1 for r in results if r["status"] == "FAIL"),
            "execution_time_sec": round(time.time() - start_time, 2),
            "results": results,
            "final_variables": self.variables,
        }
