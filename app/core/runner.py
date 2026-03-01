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
        self.report_dir = report_dir
        self.json_report_dir = os.path.join(report_dir, "json")
        self.html_report_dir = os.path.join(report_dir, "html")
        self.csv_report_dir = os.path.join(report_dir, "csv")

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
                if _ExecutionEngine._resolve_expression(v.strip()) is not None:
                    continue  # it's a valid date expression, not a variable
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
        csv_path = os.path.join(self.csv_report_dir, f"{testplan}_report.csv")

        with open(json_path, "w") as f:
            json.dump(report, f, indent=2)

        with open(html_path, "w") as f:
            f.write(_ExecutionEngine.generate_html_report(report))
        
        with open(csv_path, "w") as f:
            f.write(_ExecutionEngine.generate_csv_report(report))

        logger.info("Execution completed for %s", testplan)

        return {
            "json": f"/reports/json/{testplan}_report.json",
            "html": f"/reports/html/{testplan}_report.html",
            "csv": f"/reports/csv/{testplan}_report.csv",
        }

    def run_testplan_stream(self, testplan: str):
        """Yields events: {"type": "step", "index": i, "result": entry} then {"type": "done", "report": ..., "json_report": ..., "html_report": ..., "csv_report": ...}."""
        path = self._get_testplan_path(testplan)
        engine = _ExecutionEngine(path)
        for event in engine.run_with_stream():
            if event.get("type") == "done":
                report = event["report"]
                json_path = os.path.join(self.json_report_dir, f"{testplan}_report.json")
                html_path = os.path.join(self.html_report_dir, f"{testplan}_report.html")
                csv_path = os.path.join(self.csv_report_dir, f"{testplan}_report.csv")
                with open(json_path, "w") as f:
                    json.dump(report, f, indent=2)
                with open(html_path, "w") as f:
                    f.write(_ExecutionEngine.generate_html_report(report))
                with open(csv_path, "w") as f:
                    f.write(_ExecutionEngine.generate_csv_report(report))
                event["json_report"] = f"/reports/json/{testplan}_report.json"
                event["html_report"] = f"/reports/html/{testplan}_report.html"
                event["csv_report"] = f"/reports/csv/{testplan}_report.csv"
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
                    if _ExecutionEngine._resolve_expression(v) is not None:
                        continue  # date expression, not a variable
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
                expr_result = self._resolve_expression(var.strip())
                if expr_result is not None:
                    obj = obj.replace(f"{{{{{var}}}}}", str(expr_result))
                elif var.strip() in self.variables:
                    obj = obj.replace(f"{{{{{var}}}}}", str(self.variables[var.strip()]))
                else:
                    raise TestPlanError(f"Undefined variable: {var.strip()}")
            return obj

        if isinstance(obj, dict):
            return {k: self.resolve_vars(v) for k, v in obj.items()}

        if isinstance(obj, list):
            return [self.resolve_vars(v) for v in obj]

        return obj

    @staticmethod
    def _resolve_expression(expr: str) -> Any:
        """
        Evaluate date/time expressions inside {{ }}.
        Supported syntax examples:
            now()                          -> current UTC datetime ISO string
            today()                        -> current UTC date ISO string
            now() + days(30)               -> datetime 30 days from now
            now() - weeks(2)               -> datetime 2 weeks ago
            now() + months(3)              -> datetime 3 months from now
            now() + hours(5)               -> datetime 5 hours from now
            now() + minutes(90)            -> datetime 90 minutes from now
            format(now() + days(7), '%Y-%m-%d')  -> formatted date string
        Falls back to variable lookup if expression is not a date expression.
        """
        from datetime import datetime, timezone, timedelta

        def _now():
            return datetime.now(timezone.utc).replace(tzinfo=None)

        def _today():
            return datetime.now(timezone.utc).date()

        def _days(n):    return timedelta(days=int(n))
        def _weeks(n):   return timedelta(weeks=int(n))
        def _hours(n):   return timedelta(hours=int(n))
        def _minutes(n): return timedelta(minutes=int(n))

        def _months(n):
            # approximate months as 30 days
            return timedelta(days=int(n) * 30)

        def _format(dt, fmt):
            if hasattr(dt, 'strftime'):
                return dt.strftime(fmt)
            return str(dt)

        # Only evaluate if the expression contains a known date function
        date_funcs = ("now(", "today(", "days(", "weeks(", "hours(", "minutes(", "months(", "format(")
        if not any(f in expr for f in date_funcs):
            return None  # signal: not a date expression, fall through to variable lookup

        safe_globals = {
            "__builtins__": {},
            "now":     _now,
            "today":   _today,
            "days":    _days,
            "weeks":   _weeks,
            "hours":   _hours,
            "minutes": _minutes,
            "months":  _months,
            "format":  _format,
        }
        try:
            result = eval(expr, safe_globals)  # noqa: S307
            if hasattr(result, 'isoformat'):
                return result.isoformat()
            return result
        except Exception as e:
            raise TestPlanError(f"Invalid date expression '{{{{expr}}}}': {e}")

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
        import html
        from datetime import datetime

        results = report.get("results", [])
        passed = report.get("passed", sum(1 for r in results if r.get("status") == "PASS"))
        failed = report.get("failed", sum(1 for r in results if r.get("status") == "FAIL"))
        total = len(results)
        exec_time = report.get("execution_time_sec", 0)
        testplan = report.get("testplan", "Unknown")
        timestamp = report.get("timestamp", datetime.now().isoformat())
        success_rate = (passed / total * 100) if total > 0 else 0

        def escape(text):
            if text is None:
                return ""
            return html.escape(str(text))

        def fmt_json(data):
            if data is None:
                return ""
            if isinstance(data, (dict, list)):
                return escape(json.dumps(data, indent=2))
            return escape(str(data))

        METHOD_COLORS = {
            "GET":    ("#1b5e20", "#e8f5e9"),
            "POST":   ("#0d47a1", "#e3f2fd"),
            "PUT":    ("#e65100", "#fff3e0"),
            "PATCH":  ("#4a148c", "#f3e5f5"),
            "DELETE": ("#b71c1c", "#ffebee"),
        }

        cards = ""
        for idx, r in enumerate(results, 1):
            status = r.get("status", "UNKNOWN")
            is_pass = status == "PASS"
            method = (r.get("method") or "GET").upper()
            mc, mbg = METHOD_COLORS.get(method, ("#333", "#eee"))
            code = r.get("response_code", "")
            name = escape(r.get("name") or f"Step {idx}")
            url  = escape(r.get("url") or "")
            error = escape(r.get("error") or "")
            req_body  = fmt_json(r.get("request_body"))
            resp_body = fmt_json(r.get("response_sample"))

            status_bg  = "#e8f5e9" if is_pass else "#ffebee"
            status_col = "#2e7d32" if is_pass else "#c62828"
            status_icon = "✓" if is_pass else "✗"

            req_section = f'<pre class="code-block">{req_body}</pre>' if req_body else '<span class="none">—</span>'
            resp_section = f'<pre class="code-block">{resp_body}</pre>' if resp_body else '<span class="none">—</span>'
            error_section = f'<div class="error-msg">⚠ {error}</div>' if error else ""

            cards += f'''
        <div class="req-card">
            <div class="req-header">
                <span class="idx">#{idx}</span>
                <span class="method-badge" style="color:{mc};background:{mbg}">{escape(method)}</span>
                <span class="req-name">{name}</span>
                <span class="status-badge" style="color:{status_col};background:{status_bg}">{status_icon} {escape(status)}</span>
                <span class="code-badge" style="color:{status_col}">{escape(str(code))}</span>
            </div>
            <div class="req-url">{url}</div>
            {error_section}
            <div class="req-body-grid">
                <div class="body-col">
                    <div class="col-label">Request Body</div>
                    {req_section}
                </div>
                <div class="body-col">
                    <div class="col-label">Response Body</div>
                    {resp_section}
                </div>
            </div>
        </div>
'''
        
        return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>API Test Report — {escape(testplan)}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: 'Segoe UI', Arial, sans-serif;
    font-size: 12px;
    background: #fff;
    color: #212121;
    padding: 24px;
  }}

  /* ── Summary header ── */
  .report-title {{
    font-size: 20px;
    font-weight: 700;
    margin-bottom: 4px;
  }}
  .report-meta {{
    font-size: 11px;
    color: #757575;
    margin-bottom: 16px;
  }}
  .summary {{
    display: flex;
    gap: 12px;
    margin-bottom: 24px;
    flex-wrap: wrap;
  }}
  .stat {{
    border: 1px solid #e0e0e0;
    border-radius: 6px;
    padding: 10px 20px;
    text-align: center;
    min-width: 90px;
  }}
  .stat .val {{
    font-size: 22px;
    font-weight: 700;
    display: block;
  }}
  .stat .lbl {{
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: .5px;
    color: #757575;
  }}
  .stat.pass .val {{ color: #2e7d32; }}
  .stat.fail .val {{ color: #c62828; }}

  /* ── Request cards ── */
  .req-card {{
    border: 1px solid #e0e0e0;
    border-radius: 6px;
    margin-bottom: 14px;
    page-break-inside: avoid;
    break-inside: avoid;
    overflow: hidden;
  }}
  .req-header {{
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 12px;
    background: #fafafa;
    border-bottom: 1px solid #e0e0e0;
    flex-wrap: wrap;
  }}
  .idx {{
    font-size: 11px;
    color: #9e9e9e;
    min-width: 24px;
  }}
  .method-badge {{
    font-size: 10px;
    font-weight: 700;
    font-family: monospace;
    padding: 2px 8px;
    border-radius: 4px;
    text-transform: uppercase;
  }}
  .req-name {{
    font-weight: 600;
    font-size: 12px;
    flex: 1;
  }}
  .status-badge {{
    font-size: 11px;
    font-weight: 700;
    padding: 2px 10px;
    border-radius: 4px;
  }}
  .code-badge {{
    font-family: monospace;
    font-size: 12px;
    font-weight: 700;
    min-width: 36px;
    text-align: right;
  }}
  .req-url {{
    font-family: monospace;
    font-size: 11px;
    color: #455a64;
    padding: 5px 12px;
    background: #f5f5f5;
    border-bottom: 1px solid #e0e0e0;
    word-break: break-all;
  }}
  .error-msg {{
    background: #fff3e0;
    color: #e65100;
    font-size: 11px;
    padding: 5px 12px;
    border-bottom: 1px solid #ffe0b2;
  }}
  .req-body-grid {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 0;
  }}
  .body-col {{
    padding: 8px 12px;
    border-right: 1px solid #e0e0e0;
  }}
  .body-col:last-child {{ border-right: none; }}
  .col-label {{
    font-size: 10px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: .5px;
    color: #9e9e9e;
    margin-bottom: 4px;
  }}
  pre.code-block {{
    font-family: monospace;
    font-size: 10px;
    line-height: 1.5;
    white-space: pre-wrap;
    word-break: break-all;
    background: #f8f8f8;
    border: 1px solid #e0e0e0;
    border-radius: 4px;
    padding: 6px 8px;
    margin: 0;
  }}
  .none {{ color: #bdbdbd; font-style: italic; }}

  .footer {{
    margin-top: 24px;
    text-align: center;
    font-size: 10px;
    color: #bdbdbd;
  }}

  @media print {{
    body {{ padding: 12px; }}
    .req-card {{ page-break-inside: avoid; break-inside: avoid; }}
  }}
</style>
</head>
<body>

<div class="report-title">API Test Execution Report</div>
<div class="report-meta">Test Plan: {escape(testplan)} &nbsp;|&nbsp; Generated: {escape(timestamp)}</div>

<div class="summary">
  <div class="stat"><span class="val">{total}</span><span class="lbl">Total</span></div>
  <div class="stat pass"><span class="val">{passed}</span><span class="lbl">Passed</span></div>
  <div class="stat fail"><span class="val">{failed}</span><span class="lbl">Failed</span></div>
  <div class="stat"><span class="val">{success_rate:.1f}%</span><span class="lbl">Success</span></div>
  <div class="stat"><span class="val">{exec_time:.2f}s</span><span class="lbl">Duration</span></div>
</div>

{cards}

<div class="footer">Generated by API Chain Runner</div>
</body>
</html>'''
    
    @staticmethod
    def generate_csv_report(report: Dict[str, Any]) -> str:
        import csv
        from io import StringIO
        
        results = report.get("results", [])
        
        output = StringIO()
        writer = csv.writer(output)
        
        # Write header
        writer.writerow([
            "Test #",
            "Test Name",
            "Method",
            "Endpoint",
            "Request Body",
            "Response Status Code",
            "Status (Pass/Fail)",
            "Error Message",
            "Response Body"
        ])
        
        # Write data rows
        for idx, r in enumerate(results, 1):
            # Format request body
            req_body = r.get("request_body")
            if req_body is None:
                req_body_str = ""
            elif isinstance(req_body, (dict, list)):
                req_body_str = json.dumps(req_body)
            else:
                req_body_str = str(req_body)
            
            # Format response body
            resp_body = r.get("response_sample")
            if resp_body is None:
                resp_body_str = ""
            elif isinstance(resp_body, (dict, list)):
                resp_body_str = json.dumps(resp_body)
            else:
                resp_body_str = str(resp_body)
            
            writer.writerow([
                idx,
                r.get("name", f"Test {idx}"),
                r.get("method", "GET"),
                r.get("url", ""),
                req_body_str,
                r.get("response_code", "N/A"),
                r.get("status", "UNKNOWN"),
                r.get("error", ""),
                resp_body_str
            ])
        
        return output.getvalue()

    def run_with_stream(self):
        from datetime import datetime
        results: List[Dict[str, Any]] = []
        start_time = time.time()

        for i, req in enumerate(self.config.get("requests", [])):
            entry = {
                "step_index": i,
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
            "timestamp": datetime.now().isoformat(),
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
            "step_index": step_index,
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
        return {
            "index": step_index,
            "result": entry,
            "results_so_far": [entry],
            "executed_step_indices": [step_index],
        }

    def run_only_steps(self, step_indices: List[int], target_step_index: int) -> Dict[str, Any]:
        """Run only the given step indices in order (e.g. minimal deps), then return the result for target_step_index."""
        req_list = self.config.get("requests", [])
        results_by_index: Dict[int, Dict[str, Any]] = {}
        for i in step_indices:
            if i < 0 or i >= len(req_list):
                continue
            req = req_list[i]
            entry = {
                "step_index": i,
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
            "executed_step_indices": step_indices,
        }

    def run_with_report(self) -> Dict[str, Any]:
        report = None
        for event in self.run_with_stream():
            if event.get("type") == "done":
                report = event["report"]
                return report
        return {}
