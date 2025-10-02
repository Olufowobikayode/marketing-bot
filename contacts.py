# contacts.py
import os
import re
import csv
import json
import sqlite3
import logging
import pandas as pd
from typing import List, Dict, Tuple, Optional, Any
from email_validator import validate_email, EmailNotValidError
from contextlib import contextmanager

# ========= CONFIG =========
try:
    from config import CONTACTS_DB, DATA_DIR
except ImportError:
    from dotenv import load_dotenv
    load_dotenv()
    DATA_DIR = os.getenv("DATA_DIR", "data")
    CONTACTS_DB = os.getenv("CONTACTS_DB", os.path.join(DATA_DIR, "contacts.db"))

os.makedirs(DATA_DIR, exist_ok=True)

# ========= LOGGING =========
logger = logging.getLogger("contacts")
if not logger.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logger.addHandler(h)
logger.setLevel(logging.INFO)

# ========= DATABASE CONNECTION MANAGEMENT =========
@contextmanager
def get_db_connection():
    """Context manager for database connections with connection pooling."""
    conn = None
    try:
        conn = sqlite3.connect(
            CONTACTS_DB,
            timeout=30,
            check_same_thread=False  # Allow multiple threads
        )
        conn.row_factory = sqlite3.Row  # Return dict-like rows
        # Enable foreign keys and WAL mode for better performance
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        yield conn
    except Exception as e:
        logger.error("Database connection error: %s", e)
        raise
    finally:
        if conn:
            conn.close()

def init_db():
    """Initialize SQLite DB for contacts with robust error handling."""
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            
            # Create contacts table
            cur.execute("""
            CREATE TABLE IF NOT EXISTS contacts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_name TEXT NOT NULL,
                name TEXT,
                email TEXT NOT NULL,
                valid INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(email, group_name)
            )
            """)
            
            # Create indexes for performance
            cur.execute("CREATE INDEX IF NOT EXISTS idx_contacts_group ON contacts(group_name)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_contacts_email ON contacts(email)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_contacts_valid ON contacts(valid)")
            
            # Create trigger for updated_at
            cur.execute("""
            CREATE TRIGGER IF NOT EXISTS update_contacts_timestamp 
            AFTER UPDATE ON contacts
            FOR EACH ROW
            BEGIN
                UPDATE contacts SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
            END
            """)
            
            conn.commit()
            logger.info("Database initialized successfully")
            
    except Exception as e:
        logger.error("Failed to initialize database: %s", e)
        raise

# ========= VALIDATION =========
def validate_email_address(email: str) -> bool:
    """Check if an email address is valid using RFC checks with timeout."""
    if not email or not isinstance(email, str):
        return False
        
    # Basic format check first
    if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email):
        return False
        
    try:
        # Use timeout to prevent hanging on problematic emails
        import signal
        
        class TimeoutError(Exception):
            pass
            
        def timeout_handler(signum, frame):
            raise TimeoutError("Email validation timeout")
        
        # Set timeout for email validation (5 seconds)
        signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(5)
        
        try:
            validate_email(email, check_deliverability=False)
            signal.alarm(0)  # Cancel timeout
            return True
        except TimeoutError:
            logger.warning("Email validation timed out for: %s", email)
            return False
        except EmailNotValidError:
            return False
            
    except Exception as e:
        logger.warning("Email validation error for %s: %s", email, e)
        # Fallback to basic regex validation
        return bool(re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email))

def validate_group_name(group_name: str) -> bool:
    """Validate group name format."""
    if not group_name or not isinstance(group_name, str):
        return False
    if len(group_name) > 100:
        return False
    if not re.match(r'^[a-zA-Z0-9_\- ]+$', group_name):
        return False
    return True

# ========= CONTACTS MANAGEMENT =========
def save_contacts_from_file(file_path: str, group_name: str) -> Tuple[int, int, List[str]]:
    """
    Save contacts from a CSV/Excel file into a specific group with robust error handling.
    
    Returns:
        Tuple of (saved_count, invalid_count, error_messages)
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")
        
    if not validate_group_name(group_name):
        raise ValueError(f"Invalid group name: {group_name}")

    file_size = os.path.getsize(file_path)
    if file_size > 50 * 1024 * 1024:  # 50MB limit
        raise ValueError("File too large (max 50MB)")
    
    if file_size == 0:
        raise ValueError("File is empty")

    ext = os.path.splitext(file_path)[1].lower()
    rows = []
    error_messages = []

    try:
        if ext in [".csv", ".txt"]:
            # Try different encodings
            encodings = ['utf-8', 'latin-1', 'iso-8859-1', 'windows-1252']
            for encoding in encodings:
                try:
                    df = pd.read_csv(file_path, encoding=encoding)
                    rows = df.values.tolist()
                    break
                except UnicodeDecodeError:
                    continue
            else:
                raise ValueError("Could not decode CSV file with any common encoding")
                
        elif ext in [".xls", ".xlsx"]:
            df = pd.read_excel(file_path)
            rows = df.values.tolist()
        else:
            raise ValueError(f"Unsupported file type: {ext}. Use CSV or Excel.")
            
    except Exception as e:
        logger.error("File parsing error: %s", e)
        raise ValueError(f"Failed to parse file: {str(e)}")

    saved, invalid = 0, 0
    
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            
            for row_num, row in enumerate(rows, 1):
                try:
                    email, name = None, None

                    # Extract email and name from row cells
                    for cell in row:
                        if pd.isna(cell):
                            continue
                        cell_str = str(cell).strip()
                        if not cell_str:
                            continue
                            
                        if "@" in cell_str and not email:
                            # Basic email format check
                            if re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', cell_str):
                                email = cell_str
                        elif not name and cell_str:
                            name = cell_str[:100]  # Limit name length

                    if not email:
                        invalid += 1
                        error_messages.append(f"Row {row_num}: No valid email found")
                        continue

                    # Validate email
                    is_valid = validate_email_address(email)
                    
                    try:
                        cur.execute(
                            """INSERT OR IGNORE INTO contacts 
                               (group_name, name, email, valid) 
                               VALUES (?, ?, ?, ?)""",
                            (group_name, name, email, 1 if is_valid else 0),
                        )
                        
                        if cur.rowcount > 0:  # Row was inserted
                            saved += 1 if is_valid else 0
                            invalid += 0 if is_valid else 1
                        # else: duplicate email in same group (ignored)
                        
                    except sqlite3.Error as e:
                        error_messages.append(f"Row {row_num}: Database error - {str(e)}")
                        invalid += 1
                        
                except Exception as e:
                    error_messages.append(f"Row {row_num}: Processing error - {str(e)}")
                    invalid += 1
                    continue

            conn.commit()
            
    except Exception as e:
        logger.error("Database error during contact import: %s", e)
        raise
        
    logger.info(
        "Imported %d contacts from %s: %d saved, %d invalid",
        len(rows), file_path, saved, invalid
    )
    
    return saved, invalid, error_messages[:10]  # Return first 10 errors

def list_contacts(
    group_name: str, 
    limit: int = 50, 
    offset: int = 0,
    only_valid: bool = False
) -> List[Dict]:
    """Fetch contacts by group with pagination and filtering."""
    if not validate_group_name(group_name):
        raise ValueError(f"Invalid group name: {group_name}")
        
    limit = max(1, min(limit, 1000))  # Enforce reasonable limits
    offset = max(0, offset)
    
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            
            query = """
                SELECT id, name, email, valid, created_at 
                FROM contacts 
                WHERE group_name = ?
            """
            params = [group_name]
            
            if only_valid:
                query += " AND valid = 1"
                
            query += " ORDER BY id LIMIT ? OFFSET ?"
            params.extend([limit, offset])
            
            cur.execute(query, params)
            rows = cur.fetchall()
            
            return [{
                "id": r[0],
                "name": r[1],
                "email": r[2],
                "valid": bool(r[3]),
                "created_at": r[4]
            } for r in rows]
            
    except Exception as e:
        logger.error("Error listing contacts for group %s: %s", group_name, e)
        raise

# ========= GROUP MANAGEMENT =========
def list_groups() -> List[str]:
    """List all contact groups with error handling."""
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT DISTINCT group_name FROM contacts ORDER BY group_name")
            rows = cur.fetchall()
            return [r[0] for r in rows]
    except Exception as e:
        logger.error("Error listing groups: %s", e)
        return []

def count_group_contacts(group_name: str) -> int:
    """Count contacts in a group with validation."""
    if not validate_group_name(group_name):
        return 0
        
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM contacts WHERE group_name = ?", (group_name,))
            return cur.fetchone()[0] or 0
    except Exception as e:
        logger.error("Error counting contacts for group %s: %s", group_name, e)
        return 0

def group_stats(group_name: str) -> Dict[str, Any]:
    """Return comprehensive stats about a group."""
    if not validate_group_name(group_name):
        return {"error": "Invalid group name"}
        
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT 
                    COUNT(*) as total,
                    SUM(valid) as valid_count,
                    COUNT(*) - SUM(valid) as invalid_count,
                    MIN(created_at) as oldest_contact,
                    MAX(created_at) as newest_contact
                FROM contacts 
                WHERE group_name = ?
            """, (group_name,))
            
            result = cur.fetchone()
            if not result:
                return {"error": "Group not found"}
                
            total, valid, invalid, oldest, newest = result
            
            return {
                "group_name": group_name,
                "total": total or 0,
                "valid": valid or 0,
                "invalid": invalid or 0,
                "oldest_contact": oldest,
                "newest_contact": newest,
                "valid_percentage": (valid / total * 100) if total > 0 else 0
            }
            
    except Exception as e:
        logger.error("Error getting stats for group %s: %s", group_name, e)
        return {"error": str(e)}

# ========= FILTERING AND SEARCH =========
def filter_contacts(
    new_group: str, 
    source_group: Optional[str] = None,
    domain: Optional[str] = None, 
    regex: Optional[str] = None, 
    only_valid: bool = True
) -> Tuple[int, List[str]]:
    """
    Filter contacts by domain, regex, or validity with comprehensive error handling.
    
    Returns:
        Tuple of (contacts_created_count, error_messages)
    """
    if not validate_group_name(new_group):
        raise ValueError(f"Invalid new group name: {new_group}")
        
    if regex:
        try:
            re.compile(regex)  # Test regex validity
        except re.error as e:
            raise ValueError(f"Invalid regex pattern: {str(e)}")

    error_messages = []
    created_count = 0
    
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            
            # Add REGEXP support
            def regexp(expr, item):
                if item is None:
                    return False
                try:
                    return bool(re.search(expr, item))
                except Exception:
                    return False
                    
            conn.create_function("REGEXP", 2, regexp)
            
            # Build query dynamically
            query = "SELECT name, email, valid FROM contacts WHERE 1=1"
            params = []
            
            if source_group:
                query += " AND group_name = ?"
                params.append(source_group)
                
            if domain:
                query += " AND email LIKE ?"
                params.append(f"%{domain}")
                
            if regex:
                query += " AND email REGEXP ?"
                params.append(regex)
                
            if only_valid:
                query += " AND valid = 1"
            
            cur.execute(query, params)
            rows = cur.fetchall()
            
            # Insert filtered contacts
            for name, email, valid in rows:
                try:
                    cur.execute(
                        """INSERT OR IGNORE INTO contacts 
                           (group_name, name, email, valid) 
                           VALUES (?, ?, ?, ?)""",
                        (new_group, name, email, valid),
                    )
                    if cur.rowcount > 0:
                        created_count += 1
                except sqlite3.Error as e:
                    error_messages.append(f"Failed to insert {email}: {str(e)}")
            
            conn.commit()
            
    except Exception as e:
        logger.error("Error filtering contacts: %s", e)
        error_messages.append(f"Filtering error: {str(e)}")
    
    logger.info(
        "Filtered %d contacts into group %s (%d errors)",
        created_count, new_group, len(error_messages)
    )
    
    return created_count, error_messages

# ========= EXPORT FUNCTIONALITY =========
def export_group_to_csv(group_name: str, output_file: str) -> str:
    """Export group contacts to CSV with error handling."""
    if not validate_group_name(group_name):
        raise ValueError(f"Invalid group name: {group_name}")
        
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT name, email, valid FROM contacts WHERE group_name = ? ORDER BY email",
                (group_name,)
            )
            rows = cur.fetchall()
            
        if not rows:
            raise ValueError(f"No contacts found in group: {group_name}")
        
        # Ensure output directory exists
        os.makedirs(os.path.dirname(output_file) or ".", exist_ok=True)
        
        with open(output_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["Name", "Email", "Valid"])
            writer.writerows(rows)
            
        logger.info("Exported %d contacts from %s to %s", len(rows), group_name, output_file)
        return output_file
        
    except Exception as e:
        logger.error("Error exporting group %s: %s", group_name, e)
        raise

# ========= HEALTH CHECK =========
def health_check() -> Dict[str, Any]:
    """Perform health check on contacts module."""
    health = {
        "module": "contacts",
        "status": "unknown",
        "database_accessible": False,
        "total_contacts": 0,
        "total_groups": 0,
        "timestamp": pd.Timestamp.now().isoformat()
    }
    
    try:
        # Test database connection and basic operations
        with get_db_connection() as conn:
            health["database_accessible"] = True
            
            # Count total contacts
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM contacts")
            health["total_contacts"] = cur.fetchone()[0] or 0
            
            # Count groups
            cur.execute("SELECT COUNT(DISTINCT group_name) FROM contacts")
            health["total_groups"] = cur.fetchone()[0] or 0
            
            # Check database integrity
            cur.execute("PRAGMA integrity_check")
            integrity_result = cur.fetchone()[0]
            health["database_integrity"] = integrity_result == "ok"
            
            if health["database_accessible"] and health["database_integrity"]:
                health["status"] = "healthy"
            else:
                health["status"] = "degraded"
                health["warning"] = "Database integrity check failed"
                
    except Exception as e:
        health["status"] = "error"
        health["error"] = str(e)
    
    return health

# ========= MODULE INITIALIZATION =========
def _initialize_module():
    """Initialize contacts module on import."""
    try:
        init_db()
        health = health_check()
        if health["status"] == "healthy":
            logger.info(
                "Contacts module initialized: %d contacts in %d groups",
                health["total_contacts"], health["total_groups"]
            )
        else:
            logger.warning("Contacts module initialized with issues: %s", health.get("error", "Unknown"))
    except Exception as e:
        logger.error("Failed to initialize contacts module: %s", e)

# Initialize on import
_initialize_module()

# ========= CLI TEST =========
if __name__ == "__main__":
    print("📇 Contacts Module Production Test")
    print("=" * 50)
    
    # Health check
    health = health_check()
    print(f"Health Status: {health['status']}")
    print(f"Database Accessible: {health['database_accessible']}")
    print(f"Total Contacts: {health['total_contacts']}")
    print(f"Total Groups: {health['total_groups']}")
    
    if health["status"] == "healthy":
        # List groups
        groups = list_groups()
        print(f"\n📁 Contact Groups ({len(groups)}):")
        for group in groups[:5]:  # Show first 5 groups
            stats = group_stats(group)
            print(f"  - {group}: {stats['total']} contacts ({stats['valid_percentage']:.1f}% valid)")
        
        if len(groups) > 5:
            print(f"  ... and {len(groups) - 5} more groups")
    
    print("\n" + "=" * 50)
    print("Contacts Module Test Complete")