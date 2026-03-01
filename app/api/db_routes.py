from fastapi import APIRouter, HTTPException, Query
from typing import Optional
from app.service.db_service import db_service

router = APIRouter(prefix="/api/db", tags=["database"])


@router.get("/test")
def test_connection():
    """Test database connection"""
    return db_service.test_connection()


@router.get("/tables")
def list_tables():
    """Get list of all tables in the database"""
    try:
        tables = db_service.get_tables()
        return {"tables": tables}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tables/{table_name}/schema")
def get_table_schema(table_name: str):
    """Get schema information for a specific table"""
    try:
        schema = db_service.get_table_schema(table_name)
        return {"table_name": table_name, "schema": schema}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tables/{table_name}/data")
def get_table_data(
    table_name: str,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0)
):
    """Get data from a specific table with pagination"""
    try:
        data = db_service.get_table_data(table_name, limit, offset)
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/query")
def execute_query(query: dict):
    """Execute a custom SQL query (SELECT only)"""
    sql = query.get("sql", "")
    if not sql:
        raise HTTPException(status_code=400, detail="SQL query is required")
    
    result = db_service.execute_query(sql)
    
    if result.get("status") == "error":
        raise HTTPException(status_code=400, detail=result.get("message"))
    
    return result
