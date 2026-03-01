# API Chain Runner

A FastAPI-based tool for defining, running, and reporting on chained API test sequences. Write test plans in JSON, run them from a web UI, and export results as HTML or CSV reports.

---

## Getting Started

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000/static/index.html` in your browser.

---

## Testplan Structure

Testplans live in the `testplans/` directory as `.json` files.

```json
{
    "description": "My API Test Plan",
    "globals": {
        "base": "http://127.0.0.1:8000"
    },
    "defaults": {
        "headers": {
            "Accept": "application/json",
            "User-Agent": "API Runner/1.0"
        }
    },
    "requests": [ ... ]
}
```

| Field | Required | Description |
|---|---|---|
| `description` | yes | Human-readable name shown in the UI |
| `globals` | yes | Variables available to all requests |
| `defaults` | no | Default headers merged into every request |
| `requests` | yes | Ordered list of request definitions |

---

## Request Definition

```json
{
    "id": "user_details",
    "description": "Get User Details API",
    "method": "GET",
    "url": "{{base}}/users/me",
    "headers": {
        "Content-Type": "application/json",
        "Authorization": "Bearer {{auth_token}}"
    },
    "validate": {
        "status_code": 200,
    "verify": ["id"]
    },
    "save":{
        "user_id": "id"
    }
}
```

| Field | Required | Description |
|---|---|---|
| `id` | yes | Unique identifier for the step |
| `description` | yes | Label shown in the UI chain view |
| `method` | yes | HTTP method: GET, POST, PUT, PATCH, DELETE |
| `url` | yes | URL with optional `{{variable}}` placeholders |
| `headers` | no | Per-request headers (merged with defaults) |
| `body` | no | JSON request body |
| `validate` | no | Assertions to run on the response |
| `save` | no | Extract values from the response to use in later steps |

### validate

```json
"validate": {
    "status_code": 200,
    "verify": ["id"]
}
```

- `status_code` — expected HTTP status code
- `verify` — list of dot-notation paths that must exist in the response JSON

### save (chaining)

```json
"save": {
    "user_id": "id"
}
```

Extracts values from the response JSON using dot-notation paths and stores them as variables for use in subsequent requests via `{{auth_token}}`.

---

## Variable Expressions

Any `{{...}}` placeholder in URLs, headers, or body values is resolved at runtime.

### Globals / Saved variables

```json
"url": "{{base}}/vehicles/{{vehicle_id}}"
```

### Date & Time expressions

Dynamic dates are evaluated using Python functions — no more hardcoded timestamps.

| Expression | Result |
|---|---|
| `{{now()}}` | Current UTC datetime ISO string |
| `{{today()}}` | Current UTC date string |
| `{{now() + days(30)}}` | 30 days from now |
| `{{now() - days(5)}}` | 5 days ago |
| `{{now() + weeks(2)}}` | 2 weeks from now |
| `{{now() + months(3)}}` | ~3 months from now (30 days each) |
| `{{now() + hours(5)}}` | 5 hours from now |
| `{{now() + minutes(90)}}` | 90 minutes from now |
| `{{format(now() + days(7), '%Y-%m-%d')}}` | Custom formatted date string |

Example:

```json
"body": {
    "start_time": "{{now() + days(1)}}",
    "end_time":   "{{now() + weeks(2)}}",
    "expires_at": "{{format(now() + months(6), '%Y-%m-%dT%H:%M:%S')}}"
}
```

---

## UI Features

- Sidebar lists all testplans with live Valid/Invalid badges
- Chain view shows each request as a card with method, description, URL, and variable usage
- Click a card to preview its full definition
- Click **Run** on a card to execute from the start through that step (dependencies resolved automatically)
- Click **Run chain** to execute all steps and stream live progress
- After a run, the detail panel shows a summary report with pass/fail per step

---

## Reports

After running a chain, two report files are generated under `reports/`:

| Format | Path | Use |
|---|---|---|
| HTML | `reports/html/<testplan>_report.html` | Open in browser, print to PDF |
| CSV | `reports/csv/<testplan>_report.csv` | Import into spreadsheets |
| JSON | `reports/json/<testplan>_report.json` | Raw data for tooling |

The HTML report uses a card-per-request layout with request body, response body, status, and response code — designed to be printed directly to PDF as proof of execution.

---

## Project Structure

```
├── app/
│   ├── api/routes.py        # FastAPI route handlers
│   ├── core/
│   │   ├── runner.py        # Test execution engine
│   │   └── settings.py      # Paths and config
│   └── service/service.py   # Business logic layer
├── static/
│   ├── index.html           # Chain runner UI
│   ├── db-viewer.html       # Database viewer UI
│   ├── css/runner.css
│   └── js/runner.js
├── testplans/               # JSON testplan files
└── reports/                 # Generated reports (html, csv, json)
```
