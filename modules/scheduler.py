# modules/scheduler.py
import os
import uuid
import time
from typing import Optional
from astral import LocationInfo   # optional if timezone based scheduling needed (not required)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
from aiogram import Router, types
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from db import get_collection
from modules.providers.send_engine import send_campaign_to_group

router = Router()
jobs_col = get_collection("scheduled_jobs")
campaigns_col = get_collection("campaigns")
groups_col = get_collection("groups")

scheduler = AsyncIOScheduler()
scheduler.start()

# ---------- Helpers ----------

def schedule_job_record(job_id: str, campaign_id: str, group_id: str, run_at_ts: float, created_by: int):
    jobs_col.insert_one({
        "job_id": job_id,
        "campaign_id": campaign_id,
        "group_id": group_id,
        "run_at": run_at_ts,
        "created_by": created_by,
        "created_at": time.time(),
    })

def remove_job_record(job_id: str):
    jobs_col.delete_one({"job_id": job_id})

# ---------- Telegram handlers ----------

@router.message(Command("schedule"))
async def schedule_prompt(message: types.Message):
    """
    Entry: /schedule
    Bot will ask: choose campaign -> choose group -> send time (ISO or "now").
    We use FSM to keep simple.
    """
    camps = list(campaigns_col.find({}, {"subject": 1}))
    if not camps:
        await message.reply("No campaigns found. Create one first.")
        return
    kb = InlineKeyboardBuilder()
    for c in camps:
        kb.button(text=c["subject"], callback_data=f"schedule_campaign:{c['_id']}")
    kb.adjust(1)
    await message.reply("Select a campaign to schedule:", reply_markup=kb.as_markup())

@router.callback_query(lambda c: c.data.startswith("schedule_campaign:"))
async def schedule_campaign_selected(cb: types.CallbackQuery, state: FSMContext):
    campaign_id = cb.data.split(":", 1)[1]
    groups = list(groups_col.find({}, {"name": 1}))
    kb = InlineKeyboardBuilder()
    for g in groups:
        kb.button(text=g["name"], callback_data=f"schedule_target:{campaign_id}:{g['_id']}")
    kb.adjust(1)
    await cb.message.edit_text("Select target group:", reply_markup=kb.as_markup())
    await cb.answer()

@router.callback_query(lambda c: c.data.startswith("schedule_target:"))
async def schedule_target_selected(cb: types.CallbackQuery, state: FSMContext):
    parts = cb.data.split(":", 2)
    _, campaign_id, group_id = parts
    # ask for send time
    await cb.message.edit_text("Send time? Reply with an ISO datetime (YYYY-MM-DD HH:MM) in UTC, or type `now` to send immediately.")
    await state.set_state("awaiting_schedule_time")
    await state.update_data(campaign_id=campaign_id, group_id=group_id)
    await cb.answer()

@router.message(lambda m, state: state.get_state() == "awaiting_schedule_time")
async def schedule_time_received(message: types.Message, state: FSMContext):
    data = await state.get_data()
    campaign_id = data.get("campaign_id")
    group_id = data.get("group_id")
    text = message.text.strip()
    if text.lower() == "now":
        # create a job that runs almost immediately
        run_at = time.time() + 2
    else:
        # parse YYYY-MM-DD HH:MM (UTC)
        try:
            from datetime import datetime, timezone
            dt = datetime.strptime(text, "%Y-%m-%d %H:%M")
            dt = dt.replace(tzinfo=timezone.utc)
            run_at = dt.timestamp()
        except Exception as e:
            await message.reply("Invalid datetime format. Use `YYYY-MM-DD HH:MM` in UTC or `now`.", parse_mode="Markdown")
            return

    job_id = str(uuid.uuid4())

    # schedule with APScheduler
    def _job_wrapper(campaign_id=campaign_id, group_id=group_id, job_id=job_id):
        # Use send_campaign_to_group synchronous coroutine execution
        import asyncio
        loop = asyncio.get_event_loop()
        # choose default provider: first provider in DB or you might store preferred provider
        from db import get_collection as _getc
        provs = _getc("providers").find_one({}, sort=[("_id", 1)])
        if not provs:
            # nothing to do
            return
        provider_id = str(provs["_id"])
        coro = send_campaign_to_group(campaign_id, group_id, provider_id)
        try:
            loop.run_until_complete(coro)
        except Exception as e:
            # log error into jobs_col
            _getc("scheduled_jobs").update_one({"job_id": job_id}, {"$set": {"last_error": str(e), "last_run": time.time()}})
            return
        _getc("scheduled_jobs").update_one({"job_id": job_id}, {"$set": {"last_run": time.time()}})

    scheduler.add_job(_job_wrapper, trigger=DateTrigger(run_date=time.utcfromtimestamp(run_at)), id=job_id)
    # persist
    schedule_job_record(job_id, campaign_id, group_id, run_at, message.from_user.id)
    await message.reply(f"✅ Scheduled campaign. Job ID: `{job_id}` (will run at {run_at} UTC).", parse_mode="Markdown")
    await state.clear()

@router.message(Command("scheduled"))
async def list_scheduled(message: types.Message):
    rows = list(get_collection("scheduled_jobs").find({"created_by": message.from_user.id}))
    if not rows:
        await message.reply("You have no scheduled jobs.")
        return
    text = "📅 Your scheduled jobs:\n\n"
    for r in rows:
        text += f"- Job `{r['job_id']}` campaign `{r['campaign_id']}` group `{r['group_id']}` run_at: {r['run_at']}\n"
    await message.reply(text, parse_mode="Markdown")

@router.message(Command("canceljob"))
async def cancel_job_cmd(message: types.Message):
    # expects: /canceljob <job_id>
    parts = message.text.strip().split()
    if len(parts) != 2:
        await message.reply("Usage: /canceljob <job_id>")
        return
    job_id = parts[1]
    try:
        scheduler.remove_job(job_id)
    except Exception:
        pass
    get_collection("scheduled_jobs").delete_one({"job_id": job_id})
    await message.reply(f"✅ Job {job_id} cancelled (if it existed).")