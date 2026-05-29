import os
import json
import time
import pytz
import logging
import threading
import asyncio
from datetime import datetime, timedelta

import telebot
from telebot.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove
)

from flask import Flask
from apscheduler.schedulers.background import BackgroundScheduler
from telethon import TelegramClient

TOKEN = os.environ.get("BOT_TOKEN")
API_ID = int(os.environ.get("API_ID", 0))  
API_HASH = os.environ.get("API_HASH")

REVIEW_CHANNEL_ID = -1003289844580
MAIN_CHANNEL_ID = -1002807922369
MAIN_CHANNEL_USERNAME = "FraudsWatchlist"
BOT_USERNAME = "FraudsWatchlistBOT"
REPORT_PNG_URL = "https://t.me/ScamsWatchlist/9"

DATA_FILE = "reports.json"
GROUPS_FILE = "groups.json"

app = Flask(__name__)
bot = telebot.TeleBot(TOKEN, parse_mode="HTML")

# Telethon Setup (Dedicated Event Loop)
telethon_loop = asyncio.new_event_loop()
asyncio.set_event_loop(telethon_loop)
telethon_client = TelegramClient("session", API_ID, API_HASH, loop=telethon_loop)

# Load Data
if os.path.exists(DATA_FILE):
    try:
        with open(DATA_FILE, "r") as f:
            reports = json.load(f)
    except:
        reports = {}
else:
    reports = {}

if os.path.exists(GROUPS_FILE):
    try:
        with open(GROUPS_FILE, "r") as f:
            group_ids = set(json.load(f))
    except:
        group_ids = set()
else:
    group_ids = set()

user_state = {}
user_lock = {}

def save():
    with open(DATA_FILE, "w") as f:
        json.dump(reports, f, indent=2)

def save_groups():
    with open(GROUPS_FILE, "w") as f:
        json.dump(list(group_ids), f)

def format_username(uname):
    if not uname or "ID:" in str(uname).upper() or not str(uname).startswith("@"):
        return "@N/A"
    return uname

@app.route('/')
def home():
    return "Bot is Running on Render!"

def run_web():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

def get_user_id_by_username(username):
    try:
        if not username:
            return None
        username = str(username).strip().replace("@", "").replace(" ", "")
        if not username:
            return None
        if username.isdigit():
            return {"id": int(username), "username": None}
        if len(username) < 4 or len(username) > 32 or not username.replace("_", "").isalnum():
            return None

        clean_username = f"@{username}"

        try:
            future = asyncio.run_coroutine_threadsafe(
                telethon_client.get_entity(clean_username),
                telethon_loop
            )
            entity = future.result(timeout=10) 
            if entity:
                return {"id": entity.id, "username": clean_username}
        except Exception as e:
            print(f"⚠️ Telethon Fetch Failed for {clean_username}: {e}")

        return {"id": "Unknown", "username": clean_username}
    except Exception as e:
        print("LOOKUP CRASH:", e)
        return None

def auto_ban_in_groups(target_id, target_username):
    if not str(target_id).isdigit():
        return
        
    t_id = int(target_id)
    uname = format_username(target_username)
    
    ban_msg = f"{uname} [{t_id}] banned.\nDue to: Scammer"
    
    for gid in list(group_ids):
        try:
            bot.ban_chat_member(gid, t_id)
            bot.send_message(gid, ban_msg)
            print(f"✅ Auto-banned {t_id} in {gid}")
        except Exception as e:
            pass

def show_main_menu(chat_id):
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row(KeyboardButton("Create Report"))
    bot.send_message(chat_id, "Main Menu:", reply_markup=markup)

def get_monthly_stats():
    now = datetime.now()
    first_day_this_month = now.replace(day=1)
    last_day_prev_month = first_day_this_month - timedelta(days=1)
    month_name = last_day_prev_month.strftime("%B")
    year = last_day_prev_month.year

    total_lost = 0
    scams_count = 0

    for rid, data in reports.items():
        if data.get("approved") and data.get("type") == "User Report":
            scams_count += 1
            total_lost += int(data.get("amount", 0))

    return month_name, year, total_lost, scams_count

def send_monthly_report_review():
    try:
        month, year, lost, disputes = get_monthly_stats()
        report_msg = (
            f"📊 <b>Frauds Watchlist Monthly Dispute Report — {month} {year}</b>\n\n"
            f"<b>{month} {year}</b>\n"
            f"• ${lost:,} reported lost\n"
            f"• {disputes} disputes filed\n\n"
            "Activity declined following previous month’s spike.\n\n"
            "✅ Use trusted middleman\n"
            "❌ Avoid rushed deals"
        )
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("✅ Approve & Post", callback_data="approve_monthly"))
        markup.add(InlineKeyboardButton("❌ Reject", callback_data="reject_monthly"))

        bot.send_message(REVIEW_CHANNEL_ID, f"<b>ADMIN REVIEW: Monthly Report</b>\n\n{report_msg}", reply_markup=markup)
    except Exception as e:
        print("MONTHLY ERROR:", e)

def auto_promo():
    try:
        print("PROMO LOOP STARTED")
        for gid in list(group_ids):
            try:
                markup = InlineKeyboardMarkup()
                markup.add(InlineKeyboardButton("@fraudswatchlist", url="https://t.me/FraudsWatchlist"))
                bot.send_message(
                    gid,
                    "🌟 Keep your community safe with @fraudswatchlist\n\n"
                    "Report scammers and verify profiles.",
                    reply_markup=markup
                )
                time.sleep(2)
            except Exception as e:
                pass
        print("PROMO COMPLETE")
    except Exception as e:
        pass

try:
    indian_tz = pytz.timezone("Asia/Kolkata")
    scheduler = BackgroundScheduler(timezone=indian_tz)
except:
    scheduler = BackgroundScheduler()

scheduler.add_job(send_monthly_report_review, 'cron', day=1, hour=9, minute=0)
scheduler.add_job(auto_promo, 'interval', hours=1) 
scheduler.start()

@bot.message_handler(commands=['start'])
def start(msg):
    cid = msg.chat.id
    user_state.pop(cid, None)
    user_lock.pop(cid, None)

    if msg.chat.type == "private":
        markup = ReplyKeyboardMarkup(resize_keyboard=True)
        markup.row(KeyboardButton("Create Report"))
        bot.send_message(
            cid, 
            "Hello, click the button below to create a report. If you want to lookup a user you can use the command /lookup", 
            reply_markup=markup
        )

@bot.message_handler(commands=['lookup'])
def lookup(msg):
    try:
        args = msg.text.split()
        if len(args) < 2:
            bot.send_message(msg.chat.id, "Usage:\n/lookup @username\n/lookup userid")
            return

        raw_query = args[1]
        query = raw_query.replace("@", "").replace("ID:", "").strip().lower()

        search_id = query if query.isdigit() else None
        if not search_id:
            bot.send_chat_action(msg.chat.id, 'typing') 
            res = get_user_id_by_username(query)
            if res and str(res.get("id")).isdigit():
                search_id = str(res["id"])

        total = 0
        links = []
        report_lines = []

        for rid, data in reports.items():
            usernames = [
                str(data.get("target", "")).replace("@", "").lower(),
                str(data.get("fake", "")).replace("@", "").lower()
            ]
            ids = [
                str(data.get("target_chat_id", "")),
                str(data.get("fake_id", ""))
            ]

            if query in usernames or query in ids or (search_id and search_id in ids):
                total += 1
                
                display_status = "Pending"
                if data.get("status") == "appeal_accepted":
                    display_status = "Overturned"
                elif data.get("approved") is True or data.get("status") == "approved":
                    display_status = "Approved"
                    if data.get("msg_link"):
                        links.append(data.get("msg_link"))
                elif data.get("status") == "rejected":
                    display_status = "Declined"
                else:
                    display_status = "Pending"

                if data.get("type") == "Imp Report":
                    disp_uname = data.get("fake", "@N/A")
                    disp_id = str(data.get("fake_id", "Unknown"))
                else:
                    disp_uname = data.get("target", "@N/A")
                    disp_id = str(data.get("target_chat_id", "Unknown"))
                
                if not str(disp_uname).startswith("@") and "ID:" not in str(disp_uname):
                    disp_uname = f"@{disp_uname}"

                if disp_id == "Unknown" or not disp_id.isdigit():
                    if search_id and (query in str(disp_uname).lower()):
                        disp_id = search_id
                    else:
                        live_fetch = get_user_id_by_username(disp_uname)
                        if live_fetch and str(live_fetch.get("id")).isdigit():
                            disp_id = str(live_fetch["id"])

                report_lines.append(f"{disp_uname} | {disp_id} | {display_status}")

        if total == 0:
            bot.send_message(msg.chat.id, f"No reports found for {raw_query}")
            return

        text = "\n".join(report_lines[:50])
        
        if len(report_lines) > 50:
            text += "\n...<i>and more</i>"

        markup = InlineKeyboardMarkup()
        for idx, link in enumerate(links[:5]): 
            markup.add(InlineKeyboardButton(f"View Approved Report #{idx+1}", url=link))
            
        bot.send_message(msg.chat.id, text, reply_markup=markup, parse_mode="HTML")

    except Exception as e:
        print("LOOKUP ERROR:", e)

@bot.message_handler(commands=['appeal'])
def appeal(msg):
    args = msg.text.split(maxsplit=1)
    if len(args) < 2:
        bot.send_message(msg.chat.id, "Usage:\n/appeal your reason")
        return

    reason = args[1]
    uid = msg.from_user.id
    username = f"@{msg.from_user.username}" if msg.from_user.username else "No Username"

    text = (
        f"⚠️ <b>NEW APPEAL REQUEST</b>\n\n"
        f"👤 User: {username}\n"
        f"🆔 ID: <code>{uid}</code>\n\n"
        f"📝 Reason:\n{reason}"
    )
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("Approve Appeal ✅", callback_data=f"appealapprove_{uid}"))
    markup.add(InlineKeyboardButton("Reject Appeal ❌", callback_data=f"appealreject_{uid}"))

    bot.send_message(REVIEW_CHANNEL_ID, text, reply_markup=markup)
    bot.send_message(msg.chat.id, "✅ Your appeal was sent to moderators.")

@bot.message_handler(func=lambda m: m.text == "Create Report")
def create_report_menu(msg):
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row(KeyboardButton("User Report"), KeyboardButton("Imp Report"))
    bot.send_message(msg.chat.id, "Choose a report type:", reply_markup=markup)

@bot.message_handler(func=lambda m: m.text == "User Report")
def user_report_start(msg):
    cid = msg.chat.id
    user_state[cid] = {
        "step": "target",
        "type": "User Report",
        "reporter": f"@{msg.from_user.username}" if msg.from_user.username else "N/A",
        "reporter_chat_id": msg.from_user.id
    }
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row(KeyboardButton("Cancel Report"))
    bot.send_message(cid, "Enter the username or user ID of the user you would like to report:", reply_markup=markup)

@bot.message_handler(func=lambda m: m.text == "Imp Report")
def imp_report_start(msg):
    cid = msg.chat.id
    user_state[cid] = {
        "step": "imp_fake",
        "type": "Imp Report",
        "reporter": f"@{msg.from_user.username}" if msg.from_user.username else "N/A",
        "reporter_chat_id": msg.from_user.id
    }
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row(KeyboardButton("Cancel Report"))
    bot.send_message(cid, "Send the ❌ impersonator's @username:", reply_markup=markup)

@bot.message_handler(func=lambda msg: msg.chat.type == "private")
def handle_steps(msg):
    cid = msg.chat.id
    text = (msg.text or "").strip()

    if text.startswith("/"):
        return

    current_time = time.time()
    if cid in user_lock:
        if current_time - user_lock[cid] < 2:
            return
    user_lock[cid] = current_time

    try:
        if text == "Cancel Report":
            user_state.pop(cid, None)
            bot.send_message(cid, "Your report has been cancelled.", reply_markup=ReplyKeyboardRemove())
            show_main_menu(cid)
            return

        if cid not in user_state:
            return

        data = user_state[cid]
        step = data.get("step")

        if step == "target":
            if msg.forward_from:
                user = msg.forward_from
                data["target_chat_id"] = user.id
                data["target"] = f"@{user.username}" if user.username else f"ID: {user.id}"
            elif text.isdigit():
                data["target_chat_id"] = int(text)
                data["target"] = f"ID: {text}"
            else:
                result = get_user_id_by_username(text)
                if result is None:
                    bot.send_message(cid, "❌ Invalid username.")
                    return
                data["target"] = result["username"] or text
                data["target_chat_id"] = result["id"]

            data["step"] = "amount"
            bot.send_message(cid, "Enter the deal value (amount in USD):")
            return

        elif step == "amount":
            try:
                amount = int(text.replace("$", "").replace(",", ""))
            except:
                bot.send_message(cid, "Please enter a valid positive number for the amount (e.g. 50 or 150):")
                return
            data["amount"] = amount
            data["step"] = "proof"
            bot.send_message(cid, "Please create a telegram channel and send all the proof to the channel.\nOnce done, send me the channel url")
            return

        elif step == "proof":
            if not text.startswith(("http://", "https://", "tg://")):
                text = "https://" + text
            data["proof"] = text
            data["step"] = "review"
            data["status"] = "pending"

            markup = ReplyKeyboardMarkup(resize_keyboard=True)
            markup.row(KeyboardButton("Submit Report"))
            markup.row(KeyboardButton("Cancel Report"))
            bot.send_message(cid, "Review your report and choose an action:", reply_markup=markup)
            return

        elif step == "imp_fake":
            result = get_user_id_by_username(text)
            if result is None:
                bot.send_message(cid, "❌ Invalid username.")
                return
            data["fake"] = result["username"]
            data["fake_id"] = result["id"]
            data["step"] = "imp_real"
            bot.send_message(cid, "Now send the ✅ real user's @username:")
            return

        elif step == "imp_real":
            result = get_user_id_by_username(text)
            if result is None:
                bot.send_message(cid, "❌ Invalid username.")
                return
            data["real"] = result["username"]
            data["real_id"] = result["id"]
            data["step"] = "review"
            data["status"] = "pending"

            markup = ReplyKeyboardMarkup(resize_keyboard=True)
            markup.row(KeyboardButton("Submit Report"))
            markup.row(KeyboardButton("Cancel Report"))
            bot.send_message(cid, "Review your report and choose an action:", reply_markup=markup)
            return

        elif text == "Submit Report":
            rid = str(len(reports) + 1)
            reports[rid] = data.copy()
            save()

            if data["type"] == "Imp Report":
                review_text = (
                    f"🟡 <b>IMPERSONATION REVIEW</b>\n\n"
                    f"✅ Real: {data.get('real')}\n"
                    f"🆔 Real ID: <code>{data.get('real_id')}</code>\n\n"
                    f"❌ Fake: {data.get('fake')}\n"
                    f"🆔 Fake ID: <code>{data.get('fake_id')}</code>\n\n"
                    f"👤 Reporter ID: <code>{data.get('reporter_chat_id')}</code>"
                )
            else:
                review_text = (
                    f"⚠️ <b>NEW REPORT #{rid}</b>\n\n"
                    f"👤 Reporter: {data.get('reporter')}\n"
                    f"🆔 Reporter ID: <code>{data.get('reporter_chat_id')}</code>\n\n"
                    f"🎯 Target: {data.get('target')}\n"
                    f"🆔 Target ID: <code>{data.get('target_chat_id')}</code>\n\n"
                    f"💰 Amount: ${data.get('amount')}\n"
                    f"🔗 Proof: {data.get('proof')}"
                )

            markup = InlineKeyboardMarkup()
            markup.add(
                InlineKeyboardButton("Approve ✅", callback_data=f"approve_{rid}"),
                InlineKeyboardButton("Reject ❌", callback_data=f"reject_{rid}")
            )
            bot.send_message(REVIEW_CHANNEL_ID, review_text, reply_markup=markup)
            bot.send_message(cid, "Your report has been submitted for review", reply_markup=ReplyKeyboardRemove())

            user_state.pop(cid, None)
            show_main_menu(cid)

    except Exception as e:
        print("HANDLE ERROR:", e)
    finally:
        user_lock.pop(cid, None)

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    try:
        if call.data.startswith("approve_"):
            rid = call.data.split("_")[1]
            data = reports.get(rid)

            if not data or data.get("approved"):
                bot.answer_callback_query(call.id, "Already approved or missing.")
                return

            if data["type"] == "Imp Report":
                fake_uname = format_username(data.get('fake'))
                fake_id = data.get('fake_id', 'Unknown')
                real_uname = format_username(data.get('real'))
                real_id = data.get('real_id', 'Unknown')
                
                caption = (
                    f"❌ Fake: <a href='tg://user?id={fake_id}'>{fake_uname}</a> ({fake_id})\n"
                    f"✅ Real: <a href='tg://user?id={real_id}'>{real_uname}</a> ({real_id})"
                )
                
                markup = InlineKeyboardMarkup()
                markup.row(
                    InlineKeyboardButton("Real Profile", url=f"tg://user?id={real_id}"),
                    InlineKeyboardButton("Fake Profile", url=f"tg://user?id={fake_id}")
                )
                
                sent = bot.send_photo(MAIN_CHANNEL_ID, REPORT_PNG_URL, caption=caption, reply_markup=markup)
                auto_ban_in_groups(fake_id, fake_uname)

            else:
                target_uname = format_username(data.get('target'))
                target_id = data.get('target_chat_id', 'Unknown')

                caption = f"❌ <b>User:</b> {target_uname} (Telegram User ID: {target_id}) <b>has been marked as a scammer.</b>"
                
                markup = InlineKeyboardMarkup()
                buttons = []
                if str(target_id).isdigit():
                    buttons.append(InlineKeyboardButton("View Profile", url=f"tg://user?id={target_id}"))
                if data.get("proof"):
                    buttons.append(InlineKeyboardButton("View Proof", url=data["proof"]))
                
                if buttons:
                    markup.row(*buttons) 

                sent = bot.send_photo(MAIN_CHANNEL_ID, REPORT_PNG_URL, caption=caption, reply_markup=markup)
                auto_ban_in_groups(target_id, target_uname)

            reports[rid]["approved"] = True
            reports[rid]["status"] = "approved"
            reports[rid]["msg_id"] = sent.message_id
            
            msg_link = f"https://t.me/{MAIN_CHANNEL_USERNAME}/{sent.message_id}"
            reports[rid]["msg_link"] = msg_link
            save()

            try:
                notify_markup = InlineKeyboardMarkup()
                notify_markup.add(InlineKeyboardButton("View Post", url=msg_link))
                bot.send_message(
                    data.get("reporter_chat_id"), 
                    "✅ Your report was successfully approved and uploaded to channel.",
                    reply_markup=notify_markup
                )
            except Exception as e:
                pass

            bot.edit_message_text(f"Report #{rid} Approved ✅", call.message.chat.id, call.message.message_id)
            bot.answer_callback_query(call.id, "Approved")

        elif call.data.startswith("reject_"):
            rid = call.data.split("_")[1]
            data = reports.get(rid)
            if data:
                data["status"] = "rejected"
                reports[rid] = data
                save()
                try:
                    bot.send_message(data.get("reporter_chat_id"), "Your report has been denied. Try again later.")
                except:
                    pass
            bot.edit_message_text(f"Report #{rid} Rejected ❌", call.message.chat.id, call.message.message_id)

        elif call.data.startswith("appealapprove_"):
            uid = int(call.data.split("_")[1])
            removed = 0
            for rid, data in reports.items():
                target_id = data.get("target_chat_id")
                fake_id = data.get("fake_id")

                if target_id == uid or fake_id == uid:
                    try:
                        msg_id = data.get("msg_id")
                        if msg_id:
                            bot.delete_message(MAIN_CHANNEL_ID, msg_id)
                            removed += 1
                        reports[rid]["approved"] = False
                        reports[rid]["status"] = "appeal_accepted"
                    except Exception as e:
                        pass
            save()
            try:
                bot.send_message(uid, f"Your appeal has been accepted, \n{removed} report(s) removed.")
            except:
                pass
            bot.edit_message_text("Appeal Approved ✅", call.message.chat.id, call.message.message_id)

        elif call.data.startswith("appealreject_"):
            uid = int(call.data.split("_")[1])
            try:
                bot.send_message(uid, "Your appeal has been rejected.")
            except:
                pass
            bot.edit_message_text("Appeal Rejected ❌", call.message.chat.id, call.message.message_id)

        elif call.data == "approve_monthly":
            raw_text = call.message.text or call.message.caption or ""
            if "ADMIN REVIEW: Monthly Report" in raw_text:
                final_text = raw_text.split("ADMIN REVIEW: Monthly Report")[1].strip()
            else:
                final_text = raw_text
            bot.send_message(MAIN_CHANNEL_ID, final_text)
            bot.edit_message_text("Monthly Report Posted ✅", call.message.chat.id, call.message.message_id)

        elif call.data == "reject_monthly":
            bot.edit_message_text("Monthly Report Rejected ❌", call.message.chat.id, call.message.message_id)

    except Exception as e:
        print("CALLBACK ERROR:", e)

@bot.message_handler(func=lambda msg: msg.chat.type in ["group", "supergroup"])
def track_groups(msg):
    if msg.chat.id not in group_ids:
        group_ids.add(msg.chat.id)
        save_groups()


def run_telethon_background():
    asyncio.set_event_loop(telethon_loop)
    telethon_loop.run_forever()

if __name__ == "__main__":
    # Start web server for Render
    threading.Thread(target=run_web, daemon=True).start()
    
    print("⏳ Connecting Telethon Client...")
    try:
        telethon_client.start()
        print("✅ Telethon Account Linked Successfully!")
    except Exception as e:
        print("❌ Telethon Connection Failed:", e)

    t = threading.Thread(target=run_telethon_background, daemon=True)
    t.start()

    print("🚀 BOT STARTED ON RENDER")
    
    while True:
        try:
            bot.infinity_polling(timeout=30, long_polling_timeout=20)
        except Exception as e:
            print("POLLING ERROR:", e)
            time.sleep(5)