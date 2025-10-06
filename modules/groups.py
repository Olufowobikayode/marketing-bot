from aiogram import Router, F, types
from aiogram.filters import Command, Text
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from pymongo import MongoClient
from bson import ObjectId
import os

# MongoDB setup
MONGO_URI = os.getenv("MONGODB_URI")
DB_NAME = os.getenv("MONGODB_DB_NAME", "PulseMailerBot")
client = MongoClient(MONGO_URI)
db = client[DB_NAME]

router = Router()

# FSM states for group operations
class GroupStates(StatesGroup):
    waiting_for_group_name = State()
    waiting_for_rename = State()
    waiting_for_replace = State()

# --- List groups ---
@router.message(Command("list_groups"))
async def list_groups(message: types.Message):
    groups = list(db.groups.find({}))
    if not groups:
        await message.answer("No groups found.")
        return
    text = "Groups:\n"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    for g in groups:
        text += f"- {g['name']}\n"
        keyboard.add([
            InlineKeyboardButton("Rename", callback_data=f"rename_{str(g['_id'])}"),
            InlineKeyboardButton("Delete", callback_data=f"delete_{str(g['_id'])}")
        ])
    await message.answer(text, reply_markup=keyboard)

# --- Add group ---
@router.message(Command("add_group"))
async def add_group_start(message: types.Message, state: FSMContext):
    await message.answer("Enter the new group name:")
    await state.set_state(GroupStates.waiting_for_group_name)

@router.message(GroupStates.waiting_for_group_name)
async def add_group_name(message: types.Message, state: FSMContext):
    name = message.text.strip()
    if db.groups.find_one({"name": name}):
        await message.answer("Group already exists. Enter a different name.")
        return
    db.groups.insert_one({"name": name})
    await message.answer(f"Group '{name}' created successfully.")
    await state.clear()

# --- Rename group ---
@router.callback_query(Text(startswith="rename_"))
async def rename_group(callback: types.CallbackQuery, state: FSMContext):
    group_id = callback.data.split("_")[1]
    await state.update_data(rename_group_id=group_id)
    await callback.message.edit_text("Enter the new name for this group:")
    await state.set_state(GroupStates.waiting_for_rename)

@router.message(GroupStates.waiting_for_rename)
async def process_rename(message: types.Message, state: FSMContext):
    data = await state.get_data()
    group_id = data.get("rename_group_id")
    if not group_id:
        await message.answer("No group selected for rename.")
        await state.clear()
        return
    new_name = message.text.strip()
    db.groups.update_one({"_id": ObjectId(group_id)}, {"$set": {"name": new_name}})
    await message.answer(f"Group renamed to '{new_name}'.")
    await state.clear()

# --- Delete group ---
@router.callback_query(Text(startswith="delete_"))
async def delete_group(callback: types.CallbackQuery):
    group_id = callback.data.split("_")[1]
    db.groups.delete_one({"_id": ObjectId(group_id)})
    # Also delete contacts in that group
    db.contacts.delete_many({"group_id": ObjectId(group_id)})
    await callback.message.edit_text("Group and its contacts deleted successfully.")