# templates.py
import os
import re
import json
import uuid
import logging
import tempfile
import time
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime
from urllib.parse import urljoin

import requests
from requests.adapters import HTTPAdapter, Retry

# ========= CONFIG =========
try:
    from config import TEMPLATE_DIR, TEMPLATE_DB, MJML_APP_ID, MJML_SECRET, DATA_DIR
except Exception:
    from dotenv import load_dotenv

    load_dotenv()
    TEMPLATE_DIR = os.getenv("TEMPLATE_DIR", "templates")
    TEMPLATE_DB = os.getenv("TEMPLATE_DB", os.path.join("data", "templates.json"))
    MJML_APP_ID = os.getenv("MJML_APP_ID")
    MJML_SECRET = os.getenv("MJML_SECRET")
    DATA_DIR = os.getenv("DATA_DIR", "data")

# Ensure directories exist
os.makedirs(TEMPLATE_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

# ========= LOGGING =========
logger = logging.getLogger("templates")
if not logger.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logger.addHandler(h)
logger.setLevel(logging.INFO)

# ========= HTTP SESSION =========
def _build_robust_session() -> requests.Session:
    """Create HTTP session with retry strategy for MJML API."""
    session = requests.Session()
    
    retry_strategy = Retry(
        total=3,
        status_forcelist=[500, 502, 503, 504],
        allowed_methods=["POST"],
        backoff_factor=0.5,
        raise_on_status=False
    )
    
    adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=5, pool_maxsize=10)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    
    return session

SESSION = _build_robust_session()

# ========= CACHE CONFIG =========
CACHE_TTL = 300  # 5 minutes cache for rendered HTML

# ========= UTILITY HELPERS =========
def _now_iso() -> str:
    return datetime.utcnow().isoformat()

def _atomic_write_json(path: str, data: Dict):
    """Write JSON atomically to avoid corruption."""
    dirn = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(dir=dirn, prefix=".tmp_templates_", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        logger.debug("Atomically wrote JSON to %s", path)
    except Exception as e:
        try:
            os.remove(tmp)
        except Exception:
            pass
        logger.error("Atomic write failed for %s: %s", path, e)
        raise

def _load_json_safe(path: str) -> Dict:
    """Safely load JSON with comprehensive error handling."""
    max_attempts = 3
    for attempt in range(max_attempts):
        try:
            if not os.path.exists(path):
                logger.warning("JSON file %s does not exist, returning empty dict", path)
                return {}
                
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                
            if not isinstance(data, dict):
                logger.warning("JSON file %s does not contain a dict, returning empty", path)
                return {}
                
            return data
            
        except json.JSONDecodeError as e:
            logger.error("JSON decode error in %s (attempt %d): %s", path, attempt + 1, e)
            if attempt < max_attempts - 1:
                # Try to backup corrupted file and create new one
                backup_path = f"{path}.corrupted.{int(time.time())}"
                try:
                    os.rename(path, backup_path)
                    logger.warning("Backed up corrupted file to %s", backup_path)
                except Exception:
                    pass
                # Create empty DB
                _atomic_write_json(path, {})
                time.sleep(0.5)
            else:
                logger.error("Failed to load JSON after %d attempts, returning empty dict", max_attempts)
                return {}
                
        except Exception as e:
            logger.error("Unexpected error loading JSON %s: %s", path, e)
            if attempt < max_attempts - 1:
                time.sleep(0.5)
            else:
                return {}
    
    return {}

def _sanitize_key(name: str) -> str:
    """Sanitize template key for use in JSON metadata map."""
    if not name or not isinstance(name, str):
        raise ValueError("Template name must be a non-empty string")
        
    sanitized = re.sub(r"[^a-zA-Z0-9\-_ ]+", "", name).strip()
    if not sanitized:
        raise ValueError("Template name contains no valid characters after sanitization")
        
    return sanitized

def _safe_filename(name: str, ext: str) -> str:
    """Generate safe filename with timestamp and UUID."""
    if not name or not isinstance(name, str):
        name = "unnamed"
        
    safe = re.sub(r"[^a-zA-Z0-9\-_]", "_", name.strip().lower())
    if not safe:
        safe = "template"
        
    ts = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    uid = uuid.uuid4().hex[:8]
    return f"{safe}_{ts}_{uid}.{ext.lstrip('.')}"

def _validate_mjml_structure(mjml_code: str) -> Tuple[bool, str]:
    """Validate basic MJML structure."""
    if not mjml_code:
        return False, "Empty MJML code"
        
    required_tags = ["<mjml>", "<mj-body>", "</mjml>"]
    for tag in required_tags:
        if tag not in mjml_code:
            return False, f"Missing required tag: {tag}"
            
    # Check for proper tag nesting (basic check)
    if mjml_code.count("<mjml>") != mjml_code.count("</mjml>"):
        return False, "Unbalanced MJML tags"
        
    return True, "Valid MJML structure"

def _is_cache_valid(cached_time: str, ttl: int = CACHE_TTL) -> bool:
    """Check if cached HTML is still valid."""
    try:
        cached_dt = datetime.fromisoformat(cached_time)
        age = (datetime.utcnow() - cached_dt).total_seconds()
        return age < ttl
    except Exception:
        return False

# ========= MJML RENDERING =========
def render_mjml(mjml_code: str, timeout: int = 30, max_retries: int = 2) -> Optional[str]:
    """
    Use MJML cloud API to convert MJML -> HTML with robust error handling.
    Returns HTML string or None on failure.
    """
    if not MJML_APP_ID or not MJML_SECRET:
        logger.warning("MJML credentials not configured; skipping render")
        return None

    # Validate MJML structure first
    is_valid, validation_msg = _validate_mjml_structure(mjml_code)
    if not is_valid:
        logger.error("MJML validation failed: %s", validation_msg)
        return None

    url = "https://api.mjml.io/v1/render"
    
    for attempt in range(max_retries + 1):
        try:
            logger.debug("MJML render attempt %d/%d", attempt + 1, max_retries + 1)
            
            response = SESSION.post(
                url, 
                auth=(MJML_APP_ID, MJML_SECRET), 
                json={"mjml": mjml_code}, 
                timeout=timeout
            )
            
            if response.status_code == 200:
                data = response.json()
                html = data.get("html")
                if html and html.strip():
                    logger.info("MJML render successful")
                    return html
                else:
                    logger.warning("MJML API returned empty HTML")
                    
            elif response.status_code == 400:
                error_info = response.json().get("message", "Unknown error")
                logger.error("MJML API bad request: %s", error_info)
                break  # Don't retry client errors
                
            elif response.status_code == 403:
                logger.error("MJML API authentication failed")
                break  # Don't retry auth errors
                
            else:
                logger.warning("MJML API returned status %d, attempt %d", response.status_code, attempt + 1)
                if attempt < max_retries:
                    time.sleep(1 * (attempt + 1))  # Linear backoff
                    continue
                    
        except requests.exceptions.Timeout:
            logger.warning("MJML API timeout on attempt %d", attempt + 1)
            if attempt < max_retries:
                time.sleep(2 * (attempt + 1))
                continue
                
        except requests.exceptions.ConnectionError:
            logger.warning("MJML API connection error on attempt %d", attempt + 1)
            if attempt < max_retries:
                time.sleep(1 * (attempt + 1))
                continue
                
        except Exception as e:
            logger.exception("Unexpected MJML render error on attempt %d: %s", attempt + 1, e)
            if attempt < max_retries:
                time.sleep(1 * (attempt + 1))
                continue
    
    logger.error("All MJML render attempts failed")
    return None

# ========= DATABASE OPERATIONS =========
def load_templates() -> Dict[str, Dict]:
    """
    Returns the templates metadata map with caching.
    """
    return _load_json_safe(TEMPLATE_DB)

def save_templates(data: Dict[str, Dict]):
    """Save templates metadata with validation."""
    if not isinstance(data, dict):
        raise ValueError("Templates data must be a dictionary")
        
    for key, value in data.items():
        if not isinstance(value, dict):
            raise ValueError(f"Template metadata for key '{key}' must be a dictionary")
            
    _atomic_write_json(TEMPLATE_DB, data)

# ========= TEMPLATE CRUD OPERATIONS =========
def save_new_template(
    name: str, 
    content: str, 
    is_html: bool = False, 
    tags: Optional[List[str]] = None, 
    description: Optional[str] = None, 
    source: str = "upload"
) -> str:
    """
    Save user-provided MJML or HTML as a template with comprehensive validation.
    
    Args:
        name: User-visible name (will be sanitized for key)
        content: MJML or HTML content string
        is_html: Whether content is HTML (False for MJML)
        tags: Optional list of tags for categorization
        description: Optional description
        source: Source of template ('upload', 'github', 'ai', etc.)
    
    Returns:
        Filename stored (not the DB key)
    
    Raises:
        ValueError: If validation fails
        IOError: If file operations fail
    """
    # Input validation
    if not name or not isinstance(name, str):
        raise ValueError("Template name must be a non-empty string")
        
    if not content or not isinstance(content, str):
        raise ValueError("Template content must be a non-empty string")
        
    if len(content) > 2 * 1024 * 1024:  # 2MB limit
        raise ValueError("Template content too large (max 2MB)")
    
    # Validate MJML structure if not HTML
    if not is_html:
        is_valid, validation_msg = _validate_mjml_structure(content)
        if not is_valid:
            raise ValueError(f"Invalid MJML structure: {validation_msg}")
    
    # Generate safe filename and paths
    key = _sanitize_key(name)
    ext = "html" if is_html else "mjml"
    filename = _safe_filename(key, ext)
    file_path = os.path.join(TEMPLATE_DIR, filename)
    
    # Write template file
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
        logger.debug("Saved template file: %s", file_path)
    except Exception as e:
        logger.error("Failed to write template file %s: %s", file_path, e)
        raise IOError(f"Failed to save template file: {e}")
    
    # Render HTML cache
    html_cached = content if is_html else render_mjml(content)
    
    # Prepare metadata
    template_id = uuid.uuid4().hex
    now = _now_iso()
    
    meta = {
        "id": template_id,
        "name": name,
        "key": key,
        "source_file": filename,
        "is_html": bool(is_html),
        "html_cached": html_cached or "",
        "html_cached_at": now if html_cached else "",
        "tags": tags or [],
        "description": description or "",
        "source": source,
        "size_bytes": len(content),
        "created_at": now,
        "updated_at": now,
    }
    
    # Update database
    db = load_templates()
    
    # Ensure unique key
    final_key = key
    if key in db:
        counter = 1
        while f"{key}_{counter}" in db:
            counter += 1
        final_key = f"{key}_{counter}"
        logger.info("Template key '%s' existed, using '%s' instead", key, final_key)
    
    db[final_key] = meta
    save_templates(db)
    
    logger.info("Saved template '%s' as key='%s' file=%s", name, final_key, filename)
    return filename

def get_template_meta(key_or_name: str) -> Optional[Tuple[str, Dict]]:
    """
    Retrieve template metadata by key or by exact name with fuzzy matching.
    Returns (key, meta) or None.
    """
    if not key_or_name:
        return None
        
    db = load_templates()
    
    # Direct key match
    if key_or_name in db:
        return key_or_name, db[key_or_name]
    
    # Exact name match (case-insensitive)
    for key, meta in db.items():
        if meta.get("name", "").lower() == key_or_name.lower():
            return key, meta
    
    # Fuzzy name match (contains)
    for key, meta in db.items():
        if key_or_name.lower() in meta.get("name", "").lower():
            return key, meta
    
    logger.debug("Template not found: %s", key_or_name)
    return None

def delete_template(key_or_name: str) -> bool:
    """
    Delete template metadata and file. Returns True if deleted.
    """
    found = get_template_meta(key_or_name)
    if not found:
        logger.warning("Template to delete not found: %s", key_or_name)
        return False
        
    key, meta = found
    
    # Remove template file
    file_deleted = False
    try:
        source_file = meta.get("source_file")
        if source_file:
            file_path = os.path.join(TEMPLATE_DIR, source_file)
            if os.path.exists(file_path):
                os.remove(file_path)
                file_deleted = True
                logger.debug("Deleted template file: %s", file_path)
    except Exception as e:
        logger.error("Failed to delete template file for %s: %s", key, e)
    
    # Update database
    db = load_templates()
    if key in db:
        db.pop(key)
        save_templates(db)
        logger.info("Deleted template %s (file deleted: %s)", key, file_deleted)
        return True
    
    return False

def list_templates(
    keyword: Optional[str] = None, 
    tags: Optional[List[str]] = None, 
    limit: int = 100, 
    offset: int = 0,
    source: Optional[str] = None
) -> List[Dict]:
    """
    Return list of template metadata with filtering and pagination.
    """
    db = load_templates()
    items = list(db.values())
    
    # Apply filters
    if keyword:
        keyword_lower = keyword.lower()
        items = [
            m for m in items 
            if (keyword_lower in m.get("name", "").lower() or 
                keyword_lower in m.get("description", "").lower() or
                any(keyword_lower in tag.lower() for tag in m.get("tags", [])))
        ]
    
    if tags:
        tags_lower = {t.lower() for t in tags}
        items = [
            m for m in items 
            if tags_lower.issubset({t.lower() for t in m.get("tags", [])})
        ]
    
    if source:
        items = [m for m in items if m.get("source") == source]
    
    # Sort by created_at descending
    items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    
    # Apply pagination
    start_idx = offset
    end_idx = offset + limit
    result = items[start_idx:end_idx]
    
    logger.debug("List templates: %d results (filtered from %d)", len(result), len(items))
    return result

def get_template_html(key_or_name: str, force_refresh: bool = False) -> Optional[str]:
    """
    Return rendered HTML for a template with caching.
    If html_cached is missing/expired and template is MJML, try rendering now.
    """
    found = get_template_meta(key_or_name)
    if not found:
        return None
        
    key, meta = found
    
    # Check cache first (unless force refresh)
    cached_html = meta.get("html_cached")
    cached_at = meta.get("html_cached_at")
    
    if not force_refresh and cached_html and cached_at and _is_cache_valid(cached_at):
        logger.debug("Using cached HTML for %s", key)
        return cached_html
    
    # Need to generate HTML
    source_file = meta.get("source_file")
    if not source_file:
        logger.warning("No source file for template %s", key)
        return None
        
    file_path = os.path.join(TEMPLATE_DIR, source_file)
    if not os.path.exists(file_path):
        logger.warning("Source file missing for %s: %s", key, file_path)
        return None
        
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
            
        if meta.get("is_html"):
            html = content
        else:
            html = render_mjml(content)
        
        # Update cache in database
        if html:
            meta["html_cached"] = html
            meta["html_cached_at"] = _now_iso()
            meta["updated_at"] = _now_iso()
            
            db = load_templates()
            if key in db:
                db[key] = meta
                save_templates(db)
                logger.debug("Updated HTML cache for %s", key)
        
        return html
        
    except Exception as e:
        logger.exception("Failed to load/convert template %s: %s", key, e)
        return None

def preview_template_to_file(
    key_or_name: str, 
    output_dir: str = ".", 
    filename: Optional[str] = None
) -> Optional[str]:
    """
    Save template's HTML to an output file with robust error handling.
    Returns the full path or None on failure.
    """
    html = get_template_html(key_or_name)
    if not html:
        logger.warning("No HTML available for template %s", key_or_name)
        return None
        
    if not filename:
        safe_name = _sanitize_key(key_or_name)
        filename = f"preview_{safe_name}_{uuid.uuid4().hex[:6]}.html"
    
    # Ensure output directory exists
    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, filename)
    
    try:
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(html)
        logger.debug("Saved preview to %s", out_path)
        return out_path
    except Exception as e:
        logger.exception("Failed to write preview file %s: %s", out_path, e)
        return None

# ========= HEALTH CHECK =========
def health_check() -> Dict[str, Any]:
    """
    Perform health check on templates module.
    Returns status and diagnostics.
    """
    status = {
        "module": "templates",
        "status": "unknown",
        "templates_count": 0,
        "mjml_configured": bool(MJML_APP_ID and MJML_SECRET),
        "storage_accessible": False,
        "timestamp": _now_iso()
    }
    
    try:
        # Check storage
        if os.path.exists(TEMPLATE_DIR) and os.access(TEMPLATE_DIR, os.W_OK):
            status["storage_accessible"] = True
        else:
            status["status"] = "error"
            status["error"] = "Template storage not accessible"
            return status
            
        # Count templates
        db = load_templates()
        status["templates_count"] = len(db)
        
        # Test MJML rendering if configured
        if status["mjml_configured"]:
            test_mjml = "<mjml><mj-body><mj-section><mj-column><mj-text>Test</mj-text></mj-column></mj-section></mj-body></mjml>"
            test_html = render_mjml(test_mjml, timeout=10)
            if test_html and "Test" in test_html:
                status["mjml_api"] = "healthy"
                status["status"] = "healthy"
            else:
                status["mjml_api"] = "unavailable"
                status["status"] = "degraded"
                status["warning"] = "MJML API not responding"
        else:
            status["status"] = "healthy"
            status["warning"] = "MJML not configured (HTML rendering only)"
            
    except Exception as e:
        status["status"] = "error"
        status["error"] = str(e)
    
    return status

# ========= MODULE INITIALIZATION =========
def _initialize_module():
    """Initialize templates module on import."""
    try:
        # Ensure template DB exists
        if not os.path.exists(TEMPLATE_DB):
            save_templates({})
            logger.info("Initialized templates database at %s", TEMPLATE_DB)
        
        # Health check on startup
        health = health_check()
        if health["status"] == "healthy":
            logger.info("Templates module initialized: %d templates", health["templates_count"])
        else:
            logger.warning("Templates module initialized with issues: %s", health.get("error", "Unknown"))
            
    except Exception as e:
        logger.error("Failed to initialize templates module: %s", e)

# Initialize on import
_initialize_module()

# ========= CLI TEST =========
if __name__ == "__main__":
    print("📧 Templates Module Production Test")
    print("=" * 60)
    
    # Health check
    health = health_check()
    print(f"Health Status: {health['status']}")
    print(f"Templates Count: {health['templates_count']}")
    print(f"MJML Configured: {health['mjml_configured']}")
    print(f"Storage Accessible: {health['storage_accessible']}")
    
    if health["status"] in ["healthy", "degraded"]:
        # List existing templates
        templates = list_templates(limit=5)
        print(f"\n📋 Recent Templates ({len(templates)}):")
        for template in templates:
            print(f"  - {template.get('name')} ({template.get('source', 'unknown')})")
        
        # Test MJML rendering if available
        if health["mjml_configured"]:
            print("\n🧪 Testing MJML rendering...")
            test_result = render_mjml("<mjml><mj-body><mj-section><mj-column><mj-text>Hello World</mj-text></mj-column></mj-section></mj-body></mjml>")
            if test_result:
                print("✅ MJML Rendering: SUCCESS")
            else:
                print("❌ MJML Rendering: FAILED")
    
    print("\n" + "=" * 60)
    print("Templates Module Test Complete")