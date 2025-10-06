# modules/analytics.py
import time
from typing import Optional, Dict
from db import get_collection
from bson import ObjectId

analytics_col = get_collection("analytics")
sends_col = get_collection("sends")
contacts_col = get_collection("contacts")
campaigns_col = get_collection("campaigns")

def log_send_attempt(provider_id, provider_name, to_email, campaign_id, status, error=None):
    doc = {
        "type": "send_attempt",
        "provider_id": provider_id,
        "provider_name": provider_name,
        "to": to_email,
        "campaign_id": campaign_id,
        "status": status,
        "error": error,
        "ts": time.time(),
    }
    analytics_col.insert_one(doc)
    # also store in sends_col for history (optional duplicate)
    sends_col.insert_one({
        "provider_id": provider_id,
        "provider_name": provider_name,
        "to": to_email,
        "campaign_id": campaign_id,
        "status": status,
        "error": error,
        "timestamp": time.time(),
    })

def log_event(event_type: str, email: str, campaign_id: Optional[str] = None, meta: Optional[Dict] = None):
    """Generic event logger: opened, clicked, delivered, bounce, unsub."""
    doc = {
        "type": event_type,
        "email": email,
        "campaign_id": campaign_id,
        "meta": meta or {},
        "ts": time.time(),
    }
    analytics_col.insert_one(doc)

    # react to some events automatically:
    if event_type == "unsubscribed":
        contacts_col.update_one({"email": email}, {"$set": {"unsubscribed": True}})
    if event_type == "bounce":
        contacts_col.update_one({"email": email}, {"$set": {"bounced": True}})

def campaign_summary(campaign_id: str) -> dict:
    """Return a summary counts per event for a campaign."""
    q = {"campaign_id": campaign_id}
    sent = analytics_col.count_documents({"type": "send_attempt", "campaign_id": campaign_id, "status": "sent"})
    delivered = analytics_col.count_documents({"type": "delivered", "campaign_id": campaign_id})
    opened = analytics_col.count_documents({"type": "opened", "campaign_id": campaign_id})
    clicked = analytics_col.count_documents({"type": "clicked", "campaign_id": campaign_id})
    unsub = analytics_col.count_documents({"type": "unsubscribed", "campaign_id": campaign_id})
    bounce = analytics_col.count_documents({"type": "bounce", "campaign_id": campaign_id})
    return {
        "sent": int(sent),
        "delivered": int(delivered),
        "opened": int(opened),
        "clicked": int(clicked),
        "unsubscribed": int(unsub),
        "bounce": int(bounce),
    }

# Telegram-friendly pretty formatting (used by the bot)
def campaign_summary_text(campaign_id: str) -> str:
    camp = campaigns_col.find_one({"_id": ObjectId(campaign_id)})
    title = camp.get("subject", "(unknown)") if camp else "Campaign"
    s = campaign_summary(campaign_id)
    return (
        f"📊 Stats for *{title}*\n\n"
        f"📤 Sent: {s['sent']}\n"
        f"📬 Delivered: {s['delivered']}\n"
        f"👁️ Opened: {s['opened']}\n"
        f"🔗 Clicks: {s['clicked']}\n"
        f"⚠️ Bounced: {s['bounce']}\n"
        f"⛔ Unsubscribed: {s['unsubscribed']}\n"
    )