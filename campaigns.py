# campaigns.py
import json
import os
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any

# ========= CONFIG =========
try:
    from config import DATA_DIR
except ImportError:
    from dotenv import load_dotenv
    load_dotenv()
    DATA_DIR = os.getenv("DATA_DIR", "data")

os.makedirs(DATA_DIR, exist_ok=True)
CAMPAIGNS_DB = os.path.join(DATA_DIR, "campaigns.json")

# ========= LOGGING =========
logger = logging.getLogger("campaigns")
if not logger.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(h)
logger.setLevel(logging.INFO)

# ========= CORE FUNCTIONS =========
def _load_campaigns() -> Dict[str, Any]:
    """Load campaigns from JSON file."""
    try:
        if os.path.exists(CAMPAIGNS_DB):
            with open(CAMPAIGNS_DB, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}
    except Exception as e:
        logger.error("Failed to load campaigns: %s", e)
        return {}

def _save_campaigns(data: Dict[str, Any]):
    """Save campaigns to JSON file atomically."""
    import tempfile
    dir_name = os.path.dirname(CAMPAIGNS_DB) or "."
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, prefix=".tmp_campaigns_", suffix=".json")
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, CAMPAIGNS_DB)
    except Exception:
        try:
            os.remove(tmp_path)
        except Exception:
            pass
        raise

def list_campaigns() -> List[str]:
    """List all campaign names."""
    campaigns = _load_campaigns()
    return list(campaigns.keys())

def create_campaign(name: str, template_key: str, contacts_group: str, 
                   subject: str = "", status: str = "draft") -> bool:
    """Create a new campaign."""
    campaigns = _load_campaigns()
    
    if name in campaigns:
        logger.warning("Campaign %s already exists", name)
        return False
    
    campaigns[name] = {
        'id': f"camp_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
        'template_key': template_key,
        'contacts_group': contacts_group,
        'subject': subject,
        'status': status,
        'sent_count': 0,
        'total_recipients': 0,
        'created_at': datetime.utcnow().isoformat(),
        'updated_at': datetime.utcnow().isoformat()
    }
    
    try:
        _save_campaigns(campaigns)
        logger.info("Created campaign: %s", name)
        return True
    except Exception as e:
        logger.error("Failed to save campaign %s: %s", name, e)
        return False

def get_campaign(name: str) -> Optional[Dict[str, Any]]:
    """Get campaign details."""
    campaigns = _load_campaigns()
    return campaigns.get(name)

def update_campaign_status(name: str, status: str, sent_count: int = 0) -> bool:
    """Update campaign status and statistics."""
    campaigns = _load_campaigns()
    
    if name not in campaigns:
        logger.warning("Campaign %s not found", name)
        return False
    
    campaigns[name]['status'] = status
    campaigns[name]['sent_count'] = sent_count
    campaigns[name]['updated_at'] = datetime.utcnow().isoformat()
    
    try:
        _save_campaigns(campaigns)
        return True
    except Exception as e:
        logger.error("Failed to update campaign %s: %s", name, e)
        return False

def delete_campaign(name: str) -> bool:
    """Delete a campaign."""
    campaigns = _load_campaigns()
    
    if name not in campaigns:
        return False
    
    del campaigns[name]
    
    try:
        _save_campaigns(campaigns)
        logger.info("Deleted campaign: %s", name)
        return True
    except Exception as e:
        logger.error("Failed to delete campaign %s: %s", name, e)
        return False

# ========= STATISTICS =========
def get_campaign_stats() -> Dict[str, Any]:
    """Get overall campaign statistics."""
    campaigns = _load_campaigns()
    total = len(campaigns)
    status_count = {}
    total_sent = 0
    
    for campaign in campaigns.values():
        status = campaign.get('status', 'draft')
        status_count[status] = status_count.get(status, 0) + 1
        total_sent += campaign.get('sent_count', 0)
    
    return {
        'total_campaigns': total,
        'by_status': status_count,
        'total_emails_sent': total_sent
    }

# ========= MODULE INIT =========
def _initialize_campaigns_db():
    """Initialize campaigns database if empty."""
    campaigns = _load_campaigns()
    if not campaigns:
        # Create sample campaign structure
        sample_campaign = {
            'welcome_campaign': {
                'id': 'camp_sample_001',
                'template_key': 'welcome_email',
                'contacts_group': 'subscribers',
                'subject': 'Welcome to Our Service!',
                'status': 'draft',
                'sent_count': 0,
                'total_recipients': 0,
                'created_at': datetime.utcnow().isoformat(),
                'updated_at': datetime.utcnow().isoformat()
            }
        }
        _save_campaigns(sample_campaign)
        logger.info("Initialized campaigns database with sample data")

# Initialize on import
_initialize_campaigns_db()

# ========= CLI TEST =========
if __name__ == "__main__":
    print("Campaigns Module Test")
    print("Existing campaigns:", list_campaigns())
    stats = get_campaign_stats()
    print("Stats:", stats)