import psycopg2
from psycopg2.extras import RealDictCursor
from typing import List, Dict, Any
from app.core.settings import DATABASE_URL


class DatabaseService:
    """Service for interacting with PostgreSQL database"""
    
    def __init__(self, schema: str = "vehicle_management"):
        self.connection_params = self._parse_database_url(DATABASE_URL)
        self.schema = schema
    
    def _parse_database_url(self, url: str) -> Dict[str, str]:
        """Parse DATABASE_URL into connection parameters"""
        # postgresql://user:password@host:port/dbname
        url = url.replace("postgresql://", "")
        auth, location = url.split("@")
        user, password = auth.split(":")
        host_port, dbname = location.split("/")
        host, port = host_port.split(":")
        
        return {
            "host": host,
            "port": port,
            "dbname": dbname,
            "user": user,
            "password": password
        }
    
    def get_connection(self):
        """Create and return a database connection"""
        conn = psycopg2.connect(**self.connection_params)
        # Set search path to the specified schema
        cursor = conn.cursor()
        cursor.execute(f"SET search_path TO {self.schema}, public;")
        cursor.close()
        return conn
    
    def test_connection(self) -> Dict[str, Any]:
        """Test database connection"""
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT version();")
            version = cursor.fetchone()[0]
            cursor.execute("SELECT current_schema();")
            current_schema = cursor.fetchone()[0]
            cursor.close()
            conn.close()
            return {
                "status": "success",
                "message": "Database connection successful",
                "version": version,
                "schema": current_schema
            }
        except Exception as e:
            return {
                "status": "error",
                "message": str(e)
            }
    
    def get_tables(self) -> List[str]:
        """Get list of all tables in the specified schema"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = %s
            ORDER BY table_name;
        """, (self.schema,))
        
        tables = [row[0] for row in cursor.fetchall()]
        cursor.close()
        conn.close()
        
        return tables
    
    def get_table_schema(self, table_name: str) -> List[Dict[str, Any]]:
        """Get schema information for a specific table"""
        conn = self.get_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        cursor.execute("""
            SELECT 
                column_name,
                data_type,
                character_maximum_length,
                is_nullable,
                column_default
            FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s
            ORDER BY ordinal_position;
        """, (self.schema, table_name))
        
        schema = cursor.fetchall()
        cursor.close()
        conn.close()
        
        return [dict(row) for row in schema]
    
    def get_table_data(self, table_name: str, limit: int = 100, offset: int = 0) -> Dict[str, Any]:
        """Get data from a specific table with pagination"""
        conn = self.get_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        # Get total count
        cursor.execute(f"SELECT COUNT(*) as count FROM {self.schema}.{table_name};")
        total_count = cursor.fetchone()["count"]
        
        # Get data with pagination
        cursor.execute(f"SELECT * FROM {self.schema}.{table_name} LIMIT %s OFFSET %s;", (limit, offset))
        rows = cursor.fetchall()
        
        cursor.close()
        conn.close()
        
        return {
            "table_name": table_name,
            "schema": self.schema,
            "total_count": total_count,
            "limit": limit,
            "offset": offset,
            "rows": [dict(row) for row in rows]
        }
    
    def execute_query(self, query: str) -> Dict[str, Any]:
        """Execute a custom SQL query (SELECT only for safety)"""
        if not query.strip().upper().startswith("SELECT"):
            return {
                "status": "error",
                "message": "Only SELECT queries are allowed"
            }
        
        try:
            conn = self.get_connection()
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            
            cursor.execute(query)
            rows = cursor.fetchall()
            
            cursor.close()
            conn.close()
            
            return {
                "status": "success",
                "rows": [dict(row) for row in rows],
                "count": len(rows)
            }
        except Exception as e:
            return {
                "status": "error",
                "message": str(e)
            }


db_service = DatabaseService()
