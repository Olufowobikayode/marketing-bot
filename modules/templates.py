# modules/templates.py
import os
import io
import time
import json
import base64
import uuid
from typing import Optional, Dict, Any

import aiofiles
import httpx
import pandas as pd  # optional; used elsewhere, kept for parity
from aiogram import Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from bson import ObjectId

from db import get_collection

# Collections
templates_col = get_collection("templates")
providers_col = get_collection("providers")
campaigns_col = get_collection("campaigns")
contacts_col = get_collection("contacts")

# Env
TEMPLATE_DIR = os.getenv("TEMPLATE_DIR", "templates")
MJML_APP_ID = os.getenv("MJML_APP_ID")
MJML_SECRET = os.getenv("MJML_SECRET")
TEST_EMAIL = os.getenv("TEST_EMAIL")
DEFAULT_SENDER_EMAIL = os.getenv("DEFAULT_SENDER_EMAIL")
DEFAULT_SENDER_NAME = os.getenv("DEFAULT_SENDER_NAME", "PulseMailer")
REQUESTS_PER_SECOND = float(os.getenv("REQUESTS_PER_SECOND", "2.0"))

os.makedirs(TEMPLATE_DIR, exist_ok=True)

router = Router()

# ---------- Inline keyboards ----------

def templates_list_kb(rows):
    kb = InlineKeyboardBuilder()
    for r in rows:
        kb.button(text=r["name"], callback_data=f"tmpl_view:{r['_id']}")
    kb.button(text="➕ Upload new template", callback_data="tmpl_upload")
    kb.adjust(1)
    return kb.as_markup()

def template_action_kb(tid: str):
    kb = InlineKeyboardBuilder()
    kb.button(text="📄 Preview", callback_data=f"tmpl_preview:{tid}")
    kb.button(text="✏️ Rename", callback_data=f"tmpl_rename:{tid}")
    kb.button(text="🗑 Delete", callback_data=f"tmpl_delete:{tid}")
    kb.button(text="📤 Use in Campaign", callback_data=f"tmpl_use:{tid}")
    kb.button(text="✉️ Send test", callback_data=f"tmpl_test:{tid}")
    kb.button(text="⬅ Back", callback_data="tmpl_back")
    kb.adjust(1)
    return kb.as_markup()

# ---------- Utilities ----------

async def save_uploaded_file(file_bytes: bytes, filename: str) -> str:
    """Save file bytes to TEMPLATE_DIR and return relative path."""
    safe_name = f"{int(time.time())}_{uuid.uuid4().hex}_{filename}"
    path = os.path.join(TEMPLATE_DIR, safe_name)
    async with aiofiles.open(path, "wb") as f:
        await f.write(file_bytes)
    return path

async def convert_mjml_to_html(mjml_source: str) -> str:
    """Convert MJML to HTML using MJML Cloud API."""
    if not MJML_APP_ID or not MJML_SECRET:
        raise RuntimeError("MJML credentials not configured in env.")
    url = "https://api.mjml.io/v1/render"
    auth = (MJML_APP_ID, MJML_SECRET)
    payload = {"mjml": mjml_source}
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(url, json=payload, auth=auth)
    r.raise_for_status()
    data = r.json()
    # The MJML cloud returns {'html': '...'} or similar; adapt if API returns different key
    html = data.get("html") or data.get("mjml2html") or ""
    if not html:
        # If MJML returned an error, raise for visibility
        raise RuntimeError("MJML render returned no HTML.")
    return html

# ---------- Handlers ----------

@router.message(Command("templates"))
async def list_templates(message: types.Message):
    rows = list(templates_col.find({}, {"name": 1, "filename": 1, "created_at": 1}))
    if not rows:
        kb = InlineKeyboardBuilder().button(text="➕ Upload new template", callback_data="tmpl_upload").as_markup()
        await message.reply("No templates found. Upload one to get started.", reply_markup=kb)
        return
    await message.reply("📂 Templates:", reply_markup=templates_list_kb(rows))

# Trigger upload flow
@router.callback_query(lambda c: c.data == "tmpl_upload")
async def tmpl_upload_prompt(cb: types.CallbackQuery, state: FSMContext):
    await cb.message.edit_text("📤 Please upload your template file (.html, .mjml) or an image/attachment.\n\n"
                               "If you upload an MJML file it will be converted to HTML automatically.")
    await state.set_state("awaiting_template_file")
    await cb.answer()

# Receive file upload (html, mjml, images, attachments)
@router.message(lambda m: m.document and m.document.file_name)
async def tmpl_receive_file(message: types.Message, bot, state: FSMContext):
    if state.get_state() != "awaiting_template_file":
        # ignore files outside the upload flow
        return

    doc = message.document
    filename = doc.file_name
    file_info = await bot.get_file(doc.file_id)
    temp_bytes = await bot.download_file(file_info.file_path)
    content = temp_bytes.read()

    # Save file bytes
    saved_path = await save_uploaded_file(content, filename)

    # If MJML convert it
    content_html = None
    mjml_source = None
    lower = filename.lower()
    if lower.endswith(".mjml"):
        try:
            mjml_source = content.decode("utf-8")
            content_html = await convert_mjml_to_html(mjml_source)
        except Exception as e:
            await message.reply(f"❌ MJML conversion failed: {e}")
            await state.clear()
            return
    elif lower.endswith(".html") or lower.endswith(".htm"):
        content_html = content.decode("utf-8")
    else:
        # for images & others, no html content
        content_html = None

    # store in DB
    name = os.path.splitext(filename)[0]
    tmpl_doc = {
        "name": name,
        "filename": os.path.basename(saved_path),
        "path": saved_path,
        "html": content_html,
        "mjml_source": mjml_source,
        "created_by": message.from_user.id,
        "created_at": time.time(),
    }
    res = templates_col.insert_one(tmpl_doc)
    tid = str(res.inserted_id)
    await message.reply(f"✅ Template uploaded and saved as *{name}*.", parse_mode="Markdown",
                        reply_markup=template_action_kb(tid))
    await state.clear()

@router.callback_query(lambda c: c.data == "tmpl_back")
async def tmpl_back(cb: types.CallbackQuery):
    rows = list(templates_col.find({}, {"name": 1}))
    await cb.message.edit_text("📂 Templates:", reply_markup=templates_list_kb(rows))
    await cb.answer()

@router.callback_query(lambda c: c.data.startswith("tmpl_view:"))
async def tmpl_view(cb: types.CallbackQuery):
    tid = cb.data.split(":", 1)[1]
    tmpl = templates_col.find_one({"_id": ObjectId(tid)})
    if not tmpl:
        await cb.answer("Template not found.", show_alert=True)
        return
    txt = f"📄 *{tmpl['name']}*\nfile: `{tmpl['filename']}`\ncreated_by: `{tmpl.get('created_by')}`"
    await cb.message.edit_text(txt, parse_mode="Markdown", reply_markup=template_action_kb(tid))
    await cb.answer()

@router.callback_query(lambda c: c.data.startswith("tmpl_preview:"))
async def tmpl_preview(cb: types.CallbackQuery):
    tid = cb.data.split(":", 1)[1]
    tmpl = templates_col.find_one({"_id": ObjectId(tid)})
    if not tmpl:
        await cb.answer("Template not found.", show_alert=True)
        return

    # If HTML available, send as document + small snippet text
    if tmpl.get("html"):
        snippet = tmpl["html"][:1000] + ("..." if len(tmpl["html"]) > 1000 else "")
        await cb.message.reply(f"🧾 Preview snippet:\n\n{snippet}", parse_mode="HTML")
        # also send full HTML as file
        html_bytes = tmpl["html"].encode("utf-8")
        bio = io.BytesIO(html_bytes)
        bio.name = f"{tmpl['name']}.html"
        await cb.message.reply_document(types.InputFile(bio))
    else:
        # send raw file stored on disk
        path = tmpl.get("path")
        if path and os.path.exists(path):
            await cb.message.reply_document(types.InputFile(path))
        else:
            await cb.answer("No preview available for this template.", show_alert=True)
            return
    await cb.answer()

@router.callback_query(lambda c: c.data.startswith("tmpl_rename:"))
async def tmpl_rename_prompt(cb: types.CallbackQuery, state: FSMContext):
    tid = cb.data.split(":", 1)[1]
    tmpl = templates_col.find_one({"_id": ObjectId(tid)})
    if not tmpl:
        await cb.answer("Not found.", show_alert=True)
        return
    await cb.message.edit_text(f"✏️ Send the new name for *{tmpl['name']}*:", parse_mode="Markdown")
    await state.update_data(rename_tid=tid)
    await state.set_state("awaiting_template_rename")
    await cb.answer()

@router.message(lambda m, state: state.get_state() == "awaiting_template_rename")
async def tmpl_rename_receive(message: types.Message, state: FSMContext):
    data = await state.get_data()
    tid = data.get("rename_tid")
    new_name = message.text.strip()
    templates_col.update_one({"_id": ObjectId(tid)}, {"$set": {"name": new_name}})
    await message.reply(f"✅ Template renamed to *{new_name}*.", parse_mode="Markdown")
    await state.clear()

@router.callback_query(lambda c: c.data.startswith("tmpl_delete:"))
async def tmpl_delete(cb: types.CallbackQuery):
    tid = cb.data.split(":", 1)[1]
    tmpl = templates_col.find_one({"_id": ObjectId(tid)})
    if not tmpl:
        await cb.answer("Not found.", show_alert=True)
        return
    # remove file from disk if exists
    path = tmpl.get("path")
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except Exception:
        pass
    templates_col.delete_one({"_id": ObjectId(tid)})
    await cb.message.edit_text(f"🗑 Template *{tmpl.get('name')}* deleted.", parse_mode="Markdown")
    await cb.answer()

@router.callback_query(lambda c: c.data.startswith("tmpl_use:"))
async def tmpl_use(cb: types.CallbackQuery, state: FSMContext):
    """
    Attach template to a campaign.
    Flow:
      - Ask which campaign to attach to (list campaigns)
      - Save template_id into campaign document
    """
    tid = cb.data.split(":", 1)[1]
    campaigns = list(campaigns_col.find({}, {"subject": 1}))
    if not campaigns:
        await cb.answer("No campaigns available. Create a campaign first.", show_alert=True)
        return
    kb = InlineKeyboardBuilder()
    for c in campaigns:
        kb.button(text=c["subject"], callback_data=f"tmpl_attach:{tid}:{c['_id']}")
    kb.adjust(1)
    await cb.message.edit_text("Select campaign to attach this template to:", reply_markup=kb.as_markup())
    await cb.answer()

@router.callback_query(lambda c: c.data.startswith("tmpl_attach:"))
async def tmpl_attach(cb: types.CallbackQuery):
    _, tid, cid = cb.data.split(":", 2)
    tmpl = templates_col.find_one({"_id": ObjectId(tid)})
    if not tmpl:
        await cb.answer("Template not found.", show_alert=True)
        return
    # attach template to campaign by replacing body/html
    campaigns_col.update_one({"_id": ObjectId(cid)}, {"$set": {"body": tmpl.get("html") or "" , "template_id": ObjectId(tid)}})
    await cb.message.edit_text(f"✅ Template *{tmpl.get('name')}* attached to campaign.", parse_mode="Markdown")
    await cb.answer()

@router.callback_query(lambda c: c.data.startswith("tmpl_test:"))
async def tmpl_send_test(cb: types.CallbackQuery, state: FSMContext):
    tid = cb.data.split(":", 1)[1]
    tmpl = templates_col.find_one({"_id": ObjectId(tid)})
    if not tmpl:
        await cb.answer("Template not found.", show_alert=True)
        return

    # pick provider: prefer a provider with name 'default' or first provider in DB
    prov = providers_col.find_one({})
    if not prov:
        await cb.answer("No providers configured; cannot send test.", show_alert=True)
        return

    # choose test recipient
    recipient = TEST_EMAIL
    if not recipient:
        await cb.answer("TEST_EMAIL not configured in env; cannot send test.", show_alert=True)
        return

    # dynamic simple personalization (no contact record)
    contact = {"first_name": "Test", "last_name": "", "email": recipient, "display_name": "Test Recipient"}
    from modules.providers.send_engine import _send_single  # use internal send helper from send_engine
    html = tmpl.get("html") or ""
    if not html:
        # for non-html templates, send file as attachment not implemented here
        await cb.answer("Template has no HTML body to send as test.", show_alert=True)
        return

    await cb.message.edit_text("✉️ Sending test email... please wait.")
    res = await _send_single(prov, recipient, f"Test: {tmpl.get('name')}", html, contact, attachments=None)
    if res.get("ok"):
        await cb.message.answer("✅ Test email sent successfully.")
    else:
        await cb.message.answer(f"❌ Test send failed: {res.get('error')}")
    await cb.answer()