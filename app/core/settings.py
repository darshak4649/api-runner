import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TESTPLAN_DIR = os.path.join(BASE_DIR, "testplans")
REPORT_DIR = os.path.join(BASE_DIR, "reports")
STATIC_DIR = os.path.join(BASE_DIR, "static")

JSON_REPORT_DIR = os.path.join(REPORT_DIR, "json")
HTML_REPORT_DIR = os.path.join(REPORT_DIR, "html")

os.makedirs(JSON_REPORT_DIR, exist_ok=True)
os.makedirs(HTML_REPORT_DIR, exist_ok=True)

CSV_REPORT_DIR = os.path.join(REPORT_DIR, "csv")
os.makedirs(CSV_REPORT_DIR, exist_ok=True)

# Database settings
DATABASE_URL = "postgresql://darshakv:kpitImDk4649@localhost:5432/hmp_vmp"