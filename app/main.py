from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes import router as testplan_router
from app.api.db_routes import router as db_router
from app.core.settings import STATIC_DIR

app = FastAPI(title="API Testplan Runner")

# Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(testplan_router)
app.include_router(db_router)

# Static
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/reports", StaticFiles(directory="reports"), name="reports")


@app.get("/")
def home():
    return {
        "message": "API Testplan Runner is running",
        "ui": "/static/index.html"
    }
