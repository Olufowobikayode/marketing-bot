from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pymongo import MongoClient
from bson import ObjectId
import os

MONGO_URI = os.getenv("MONGODB_URI")
DB_NAME = os.getenv("MONGODB_DB_NAME", "PulseMailerBot")
client = MongoClient(MONGO_URI)
db = client[DB_NAME]

app = FastAPI(title="PulseMailer Unsubscribe")

@app.get("/unsubscribe/{contact_id}", response_class=HTMLResponse)
async def unsubscribe(contact_id: str):
    try:
        contact = db.contacts.find_one({"_id": ObjectId(contact_id)})
        if not contact:
            return HTMLResponse(content="<h3>Contact not found.</h3>", status_code=404)

        db.contacts.delete_one({"_id": ObjectId(contact_id)})
        return HTMLResponse(content=f"<h3>{contact.get('first_name','')} {contact.get('last_name','')} has been unsubscribed successfully.</h3>")

    except Exception as e:
        return HTMLResponse(content=f"<h3>Error: {e}</h3>", status_code=500)

# Optional health endpoint
@app.get("/health")
async def health():
    return {"status": "ok", "module": "unsubscribe"}