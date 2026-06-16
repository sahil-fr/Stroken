import os
import json
import time
import io
import threading
import asyncio
import logging
from datetime import datetime, timedelta

# Third-Party Dependencies
import pytz
import requests
import telebot
from telebot.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove
)
from PIL import Image, ImageDraw, ImageFont
from apscheduler.schedulers.background import BackgroundScheduler
import sqlite3
from telethon import TelegramClient
from aiohttp import web
from flask import Flask
from threading import Thread

BOT_TOKEN = os.environ.get("BOT_TOKEN")
API_ID = int(os.environ.get("API_ID", 1234567))
API_HASH = os.environ.get("API_HASH")

bot = telebot.TeleBot(BOT_TOKEN)

BOT_USERNAME = "FraudsWatchlistBOT"
MAIN_CHANNEL_USERNAME = "FraudsWatchlist"
REVIEW_CHANNEL_ID = -1003289844580
MAIN_CHANNEL_ID = -1002807922369
# Images Setup
NEW_START_PNG = "https://t.me/ScamsWatchlist/40"       
MAIN_CHANNEL_POST_PNG = "https://t.me/ScamsWatchlist/56" 

global_report_counter = 250

user_state = {}
report_data = {}
user_settings = {} 
group_ids = set()  # Auto promo lists tracking ke liye

telethon_client = TelegramClient('bot_session', API_ID, API_HASH)
telethon_loop = asyncio.new_event_loop()

def start_telethon_loop():
    asyncio.set_event_loop(telethon_loop)
    telethon_client.start(bot_token=BOT_TOKEN)
    telethon_loop.run_forever()

threading.Thread(target=start_telethon_loop, daemon=True).start()

# --- Sync function to resolve real ID from username via Telethon ---
def get_real_id_from_tg(username_or_id):
    target = str(username_or_id).replace("@", "").strip()
    if target.isdigit():
        return target # Agar pehle se hi ID hai to wahi return karega
    
    async def fetch():
        try:
            entity = await telethon_client.get_entity(target)
            return str(entity.id)
        except Exception as e:
            print(f"Telethon Entity Fetch Error for {target}: {e}")
            return "N/A"
            
    future = asyncio.run_coroutine_threadsafe(fetch(), telethon_loop)
    return future.result()

db_scammers = {
    "smoken": {"proof_link": "https://t.me/example_post/12", "type": "User Report", "reports_count": 2, "victims": 0, "status": "Not flagged", "is_scammer": False}
}

def get_welcome_text():
    return (
        f"<b>Welcome to @{MAIN_CHANNEL_USERNAME}</b>\n\n"
        f"A specialized platform committed\n"
        f"to reporting scammers.\n\n"
        f"• <a href='https://t.me/FraudsWatchlist/23'>How to Report a Scammer</a>\n"
        f"• <a href='https://t.me/FraudsWatchlist/270'>FAQ and Terms</a>\n\n"
        f"All reports are reviewed by mods\n"
        f"before being published.\n"
        f"Type /help for all commands &\n"
        f"features.\n\n"
        f"<b>Powered By: @NOTEXnetwork</b>"
    )

def get_main_inline_markup():
    inline_markup = InlineKeyboardMarkup()
    inline_markup.row(
        InlineKeyboardButton("Create Report", callback_data="inline_create_report"),
        InlineKeyboardButton("Lookup", callback_data="inline_lookup_help")
    )
    inline_markup.row(
        InlineKeyboardButton("Use a Middleman", url="https://t.me/middlemams"),
        InlineKeyboardButton("Add Bot to Group", url=f"https://t.me/{BOT_USERNAME}?startgroup=true")
    )
    return inline_markup

def get_scammer_inline_markup(proof_url):
    inline_markup = InlineKeyboardMarkup()
    final_url = proof_url if proof_url else f"https://t.me/{MAIN_CHANNEL_USERNAME}"
    inline_markup.row(
        InlineKeyboardButton("Create Appeal", callback_data="inline_create_appeal"),
        InlineKeyboardButton("View Report", url=final_url)
    )
    return inline_markup

def get_main_inline_markup():
    inline_markup = InlineKeyboardMarkup()
    inline_markup.row(
        InlineKeyboardButton("Create Report", callback_data="inline_create_report"),
        InlineKeyboardButton("Lookup", callback_data="inline_lookup_help")
    )
    inline_markup.row(
        InlineKeyboardButton("Use a Middleman", url="https://t.me/middlemams"),
        InlineKeyboardButton("Add Bot to Group", url=f"https://t.me/{BOT_USERNAME}?startgroup=true")
    )
    return inline_markup

def init_extra_db():
    # timeout=30 add karne se bot wait karega, turant error nahi dega
    conn = sqlite3.connect("anti_scam.db", timeout=30)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS banned_logs (
            group_id INTEGER,
            user_id TEXT,
            username TEXT,
            PRIMARY KEY (group_id, user_id)
        )
    ''')
    conn.commit()
    conn.close()

init_extra_db()

def get_cancel_markup():
    inline_markup = InlineKeyboardMarkup()
    inline_markup.row(InlineKeyboardButton("Cancel Report", callback_data="inline_cancel_report"))
    return inline_markup

def get_back_menu_markup():
    inline_markup = InlineKeyboardMarkup()
    inline_markup.row(InlineKeyboardButton("⬅️ Back to Menu", callback_data="back_to_menu"))
    return inline_markup

def get_back_main_menu_markup():
    inline_markup = InlineKeyboardMarkup()
    inline_markup.row(InlineKeyboardButton("⬅️ Back to Main Menu", callback_data="back_to_main_menu"))
    return inline_markup

def generate_profile_card(user_id, username, display_name, reports, victims, status, is_scammer, avatar_bytes=None):
    img = Image.new('RGB', (1000, 562), color='#0b0c10')
    draw = ImageDraw.Draw(img)
    
    draw.rounded_rectangle([60, 330, 330, 480], radius=30, fill='#1f2833')
    draw.rounded_rectangle([360, 330, 630, 480], radius=30, fill='#1f2833')
    draw.rounded_rectangle([660, 330, 940, 480], radius=30, fill='#1f2833')
    
    flag_color = '#c5a059' if not is_scammer else '#8b0000'
    flag_text = "NON-SCAMMER" if not is_scammer else "SCAMMER"
    draw.rounded_rectangle([690, 60, 930, 110], radius=20, fill=flag_color)
    draw.rounded_rectangle([330, 230, 680, 290], radius=30, fill='#1f2833')

    try:
        font_title = ImageFont.truetype("arial.ttf", 40)
        font_sub = ImageFont.truetype("arial.ttf", 22)
        font_stat = ImageFont.truetype("arial.ttf", 55)
        font_banner = ImageFont.truetype("arial.ttf", 24)
    except:
        font_title = font_sub = font_stat = font_banner = ImageFont.load_default()

    draw.text((330, 60), "USERNAME", fill='#858585', font=font_sub)
    draw.text((330, 90), f"@{username}", fill='#ffffff', font=font_title)
    
    draw.text((330, 150), "DISPLAY NAME", fill='#858585', font=font_sub)
    draw.text((330, 180), f"{display_name}", fill='#ffffff', font=font_title)
    
    alert_info = "This account has not been flagged.\nNo suspicious activity found." if not is_scammer else "This account has been flagged!\nSuspicious activity tracked."
    draw.text((400, 238), alert_info, fill='#ffffff', font=ImageFont.load_default())

    draw.text((130, 360), "Reports", fill='#ffffff', font=font_sub)
    draw.text((170, 400), str(reports), fill='#ffffff', font=font_stat)
    
    draw.text((440, 360), "Victims", fill='#ffffff', font=font_sub)
    draw.text((475, 400), str(victims), fill='#ffffff', font=font_stat)
    
    draw.text((750, 360), "Status", fill='#ffffff', font=font_sub)
    draw.text((700, 410), str(status), fill='#ffffff', font=ImageFont.truetype("arial.ttf", 35))
    draw.text((720, 72), flag_text, fill='#ffffff', font=font_banner)

    if avatar_bytes:
        try:
            avatar = Image.open(io.BytesIO(avatar_bytes)).resize((230, 230))
            mask = Image.new('L', (230, 230), 0)
            mask_draw = ImageDraw.Draw(mask)
            mask_draw.ellipse((0, 0, 230, 230), fill=255)
            img.paste(avatar, (65, 60), mask=mask)
        except:
            draw.ellipse((65, 60, 295, 290), outline='#ffffff', width=3)
    else:
        draw.ellipse((65, 60, 295, 290), outline='#ffffff', width=3)

    output = io.BytesIO()
    img.save(output, format='PNG')
    output.seek(0)
    return output

@bot.message_handler(commands=['start'])
def start_cmd(msg):
    if msg.chat.type == "private":
        cid = msg.chat.id
        user_state.pop(cid, None)
        report_data.pop(cid, None)
        
        # 1. Niche ka persistent bottom menu keyboard setup
        reply_markup_bottom = ReplyKeyboardMarkup(resize_keyboard=True)
        reply_markup_bottom.row(KeyboardButton("Cancel Report"))
        
        # 2. Welcome caption text (Promo completely removed as per last update)
        full_caption = get_welcome_text()
        
        # 3. Main photo message jisme dono markup integrated hain
        try:
            bot.send_photo(
                chat_id=cid, 
                photo=NEW_START_PNG, 
                caption=full_caption, 
                reply_markup=get_main_inline_markup(), # Inline keyboard buttons
                parse_mode='HTML'
            )
            
        except Exception as e:
            print("START COMMAND ERROR:", e)
            # Fallback text message agar image delivery fail ho
            bot.send_message(cid, full_caption, reply_markup=get_main_inline_markup(), parse_mode='HTML')

@bot.message_handler(commands=['lookup'])
def lookup_cmd(msg):
    if msg.chat.type == "private":
        cid = msg.chat.id
        args = msg.text.split()
        
        # Validation checking agar user kuch na likhe
        if len(args) < 2:
            bot.send_message(cid, "❌ <b>Usage:</b> <code>/lookup @username</code> or <code>/lookup user_id</code>", parse_mode='HTML')
            return
            
        input_target = args[1].strip()
        raw_target = input_target.replace("@", "").lower()
        
        # Background mein Telethon se Real ID resolve karna (Agar username diya ho)
        resolved_id = get_real_id_from_tg(input_target)
        
        # SQLite Database se target se match khane wali saari reports fetch karna
        conn = sqlite3.connect("anti_scam.db")
        cursor = conn.cursor()
        cursor.execute("""
            SELECT report_type, target, reporter_id, status 
            FROM reports 
            WHERE LOWER(target) = ? OR LOWER(target) = ? OR reporter_id = ?
        """, (raw_target, f"@{raw_target}", resolved_id))
        rows = cursor.fetchall()
        conn.close()
        
        if not rows:
            bot.send_message(cid, f"No reports found for {input_target}. Account is clean.", parse_mode='HTML')
        else:
            text = f"Lookup results for {input_target} ({len(rows)} total logs):\n\n"
            
            for row in rows:
                rep_type, target_name, reporter_id, status = row
                
                # Username checking wrapper (@N/A fallback engine)
                target_clean = str(target_name).strip()
                if not target_clean.startswith("@") and not target_clean.isalpha():
                    # Agar target sirf digits (User ID) hai aur username nahi mila
                    display_username = "@N/A"
                    display_id = target_clean
                elif target_clean.startswith("@"):
                    display_username = target_clean
                    display_id = resolved_id if resolved_id != "Unknown" else "Hidden"
                else:
                    display_username = f"@{target_clean}"
                    display_id = resolved_id if resolved_id != "Unknown" else "Hidden"
                
                # Dynamic Status Translation
                clean_status = "Pending"
                if "Approved" in status:
                    clean_status = "Approved"
                elif "Denied" in status or "Reject" in status:
                    clean_status = "Declined"
                elif "Overturned" in status:
                    clean_status = "Overturned"
                
                # Exact requested structure layout print: @username | user_id | Status
                text += f"{display_username} | {display_id} | {clean_status}\n"
                
            bot.send_message(cid, text, parse_mode='HTML', reply_markup=get_back_main_menu_markup())

@bot.message_handler(commands=['help'])
def help_cmd(msg):
    if msg.chat.type == "private":
        help_text = (
            "<b>Frauds Watchlist Bot — Features</b>\n\n"
            "<b>Reporting</b>\n"
            "• /start — open the main menu and create a report\n"
            "• /myreports — view all your reports and their status\n"
            "• Forward any scammer's DM to the bot — get a one-tap \"Report this user?\" prompt\n"
            "• Submit More Proof — if a report is denied for proof, reopen just the proof step\n"
            "• /settings — toggle DM notifications when approved\n\n"
            "<b>Lookup</b>\n"
            "• /lookup &lt;@username | id&gt; — visual profile card with reports, victims, total scammed\n\n"
            "<b>Appeals</b>\n"
            "• If you've been marked as a scammer, press Create Appeal on /start"
        )
        bot.send_message(msg.chat.id, help_text, parse_mode='HTML', reply_markup=get_back_menu_markup())

@bot.message_handler(commands=['myreports'])
def myreports_cmd(msg):
    if msg.chat.type == "private":
        cid = msg.chat.id
        
        # Real-time SQLite Database se user ki details fetch karna
        conn = sqlite3.connect("anti_scam.db")
        cursor = conn.cursor()
        cursor.execute("SELECT report_id, report_type, target, status FROM reports WHERE reporter_id = ?", (cid,))
        rows = cursor.fetchall()
        conn.close()
        
        if not rows:
            text = "📂 <b>Your Reports — page 1/1 (0 total)</b>\n\nNo active reports found under your profile tracking queue."
        else:
            total_count = len(rows)
            text = f"📂 <b>Your Reports — page 1/1 ({total_count} total)</b>\n\n"
            for row in rows:
                # database se real target nikal rahe hain (jo user ne enter kiya tha)
                rep_id, rep_type, target, status = row
                
                # Short clean dynamic formatting
                clean_type = "Impersonator" if "Imp" in rep_type else "User"
                
                # Ab '@jakky' ki jagah '{target}' use kiya hai, jisse real reported username/id hi dikhega
                text += f"#{rep_id} ({clean_type}) — {target} — {status}\n"
                
        bot.send_message(cid, text, parse_mode='HTML', reply_markup=get_back_main_menu_markup())

@bot.message_handler(commands=['check'])
def check_cmd(msg):
    args = msg.text.split()
    if len(args) < 2:
        bot.send_message(msg.chat.id, "❌ Usage: /check @username or /check user_id")
        return
        
    target = args[1].replace("@", "").strip()
    cid = msg.chat.id
    
    try:
        chat_info = bot.get_chat(args[1] if args[1].startswith("@") else target)
        target_id = chat_info.id
        username = chat_info.username if chat_info.username else "N/A"
        display_name = chat_info.first_name if chat_info.first_name else "Telegram User"
    except:
        target_id = target
        username = target
        display_name = target

    avatar_bytes = None
    try:
        photos = bot.get_user_profile_photos(target_id, limit=1)
        if photos.total_count > 0:
            file_id = photos.photos[0][0].file_id
            file_info = bot.get_file(file_id)
            avatar_bytes = requests.get(f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_info.file_path}").content
    except:
        pass

    key = target.lower()
    if key in db_scammers:
        scam_info = db_scammers[key]
        reports_count = scam_info.get("reports_count", 2)
        victims_count = scam_info.get("victims", 0)
        status_text = scam_info.get("status", "Not flagged")
        is_scammer = scam_info.get("is_scammer", True)
    else:
        reports_count = 2
        victims_count = 0
        status_text = "Not flagged"
        is_scammer = False

    card_img = generate_profile_card(target_id, username, display_name, reports_count, victims_count, status_text, is_scammer, avatar_bytes)
    
    check_markup = InlineKeyboardMarkup()
    profile_url = f"tg://openmessage?user_id={target_id}" if username == "N/A" else f"https://t.me/{username}"
    check_markup.row(InlineKeyboardButton("View Profile", url=profile_url))
    check_markup.row(InlineKeyboardButton("Report User", callback_data="report_user_start"))
    
    bot.send_photo(cid, photo=card_img, reply_markup=check_markup)

@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    cid = call.message.chat.id
    mid = call.message.message_id

    if call.data in ["back_to_menu", "back_to_main_menu"]:
        try: bot.delete_message(cid, mid)
        except: pass
        
        u_name = call.from_user.username if call.from_user.username else ""
        conn = sqlite3.connect("anti_scam.db")
        cursor = conn.cursor()
        cursor.execute("SELECT proof_link FROM reports WHERE (target = ? OR target = ? OR reporter_id = ?) AND status = 'Approved'", (str(cid), f"@{u_name}", str(cid)))
        scam_row = cursor.fetchone()
        conn.close()
        
        if scam_row:
            bot.send_photo(cid, photo=NEW_START_PNG, caption=f"{get_welcome_text()}\n\n<b>RESTRICTED:</b>\nYou've been marked as a scammer.", reply_markup=get_scammer_inline_markup(scam_row[0]), parse_mode='HTML')
        else:
            bot.send_photo(cid, photo=NEW_START_PNG, caption=get_welcome_text(), reply_markup=get_main_inline_markup(), parse_mode='HTML')

    elif call.data == "inline_lookup_help":
        lookup_help_text = (
            "<b>Account Lookup System</b>\n\n"
            "To check any user's background or report logs, please use the command format below:\n\n"
            "<b>Usage:</b>\n"
            "<code>/lookup @username</code>\n"
            "OR\n"
            "<code>/lookup user_id</code>"
        )
        try: bot.edit_message_caption(chat_id=cid, message_id=mid, caption=lookup_help_text, reply_markup=get_back_main_menu_markup(), parse_mode='HTML')
        except: pass

    elif call.data == "inline_create_report":
        report_markup = InlineKeyboardMarkup()
        report_markup.row(InlineKeyboardButton("User Report", callback_data="report_user_start"), InlineKeyboardButton("Imp Report", callback_data="report_imp_start"))
        report_markup.row(InlineKeyboardButton("Cancel", callback_data="inline_cancel_report"))
        bot.edit_message_caption(chat_id=cid, message_id=mid, caption="Select a report type", reply_markup=report_markup)

    elif call.data == "inline_cancel_report":
        bot.edit_message_caption(chat_id=cid, message_id=mid, caption="Your report has been cancelled.", reply_markup=get_main_inline_markup(), parse_mode='HTML')

    elif call.data == "inline_create_appeal" or call.data == "report_appeal_trigger":
        user_state[cid] = "AWAITING_APPEAL_TEXT"
        bot.edit_message_caption(chat_id=cid, message_id=mid, caption="<b>Appeal Submission:</b>\n\nPlease write detailed reasons/proofs of why this flag is wrong:", reply_markup=get_cancel_markup(), parse_mode='HTML')

    elif call.data == "report_user_start":
        user_state[cid] = "AWAITING_USER_TARGET"
        report_data[cid] = {"type": "User Report"}
        bot.edit_message_caption(chat_id=cid, message_id=mid, caption="Enter the username or user ID of the user you would like to report:", reply_markup=get_cancel_markup())

    elif call.data == "report_imp_start":
        user_state[cid] = "AWAITING_IMP_TARGET"
        report_data[cid] = {"type": "Imp Report"}
        bot.edit_message_caption(chat_id=cid, message_id=mid, caption="Enter the username or user ID of the user you would like to report:", reply_markup=get_cancel_markup())

    # --- ADMIN ACTIONS (APPROVE VERIFICATION) ---
    elif call.data.startswith("adm_app_"):
        parts = call.data.split("_")
        reporter_id = int(parts[2])
        report_id = parts[3]
        
        data = report_data.get(reporter_id, {})
        rep_type = data.get('type', 'User Report')
        
        target_raw = str(data.get('target', '')).replace("@", "").strip()
        target_id = str(data.get('target_id', 'Unknown'))
        proof_chan = data.get('proof_channel', 'https://t.me')
        
        public_markup = InlineKeyboardMarkup()
        
        if "User" in rep_type:
            if target_raw.isdigit():
                user_line = f"@N/A (<a href='tg://openmessage?user_id={target_raw}'>{target_raw}</a>)"
            else:
                user_line = f"@{target_raw} (<a href='tg://openmessage?user_id={target_id}'>{target_id}</a>)"
                
            public_text = f"❌ <b>User</b> {user_line} <b>has been marked as a scammer.</b>"
            profile_url = f"tg://openmessage?user_id={target_id if target_id.isdigit() else target_raw}"
            public_markup.row(
                InlineKeyboardButton("View Profile", url=profile_url), 
                InlineKeyboardButton("View Proof", url=proof_chan)
            )
        else:
            real_raw = str(data.get('real_target', '')).replace("@", "").strip()
            real_id = str(data.get('real_target_id', 'Unknown'))
            
            fake_line = f"@{target_raw} ({target_id})"
            real_line = f"@{real_raw} ({real_id})"
            
            public_text = f"❌<b>Impersonator:</b> {fake_line}\n✅<b>Real User:</b> {real_line}"
            
            fake_url = f"tg://openmessage?user_id={target_id if target_id.isdigit() else target_raw}"
            real_url = f"tg://openmessage?user_id={real_id if real_id.isdigit() else real_raw}"
            public_markup.row(
                InlineKeyboardButton("Real Profile", url=real_url), 
                InlineKeyboardButton("Fake Profile", url=fake_url)
            )

        # Main Channel par photo upload karna
        sent_photo = bot.send_photo(MAIN_CHANNEL_ID, photo=MAIN_CHANNEL_POST_PNG, caption=public_text, reply_markup=public_markup, parse_mode='HTML')
        
        # Unique Post Link dynamic generate karna (Aapki settings ke hisab se exact format)
        post_url = f"https://t.me/{MAIN_CHANNEL_USERNAME}/{sent_photo.message_id}"
        
        conn = sqlite3.connect("anti_scam.db")
        cursor = conn.cursor()
        cursor.execute("UPDATE reports SET status = 'Approved', proof_link = ? WHERE report_id = ?", (post_url, report_id))
        conn.commit()
        conn.close()

        # Reporter ko custom message aur clickable "View Post" link bhej dena
        reporter_markup = InlineKeyboardMarkup().row(InlineKeyboardButton("View Post ↗", url=post_url))
        bot.send_message(reporter_id, "Your report was successfully approved and uploaded to channel.", reply_markup=reporter_markup)
        
        # Review Channel ke buttons hatana aur text update karna
        orig_caption = call.message.caption if call.message.caption else ""
        updated_caption = f"{orig_caption}\n\n<b>Status: Approve ✅</b>"
        
        try:
            bot.edit_message_caption(
                chat_id=REVIEW_CHANNEL_ID, 
                message_id=mid, 
                caption=updated_caption, 
                reply_markup=None, # Buttons remove ho gaye
                parse_mode='HTML'
            )
        except Exception as e:
            print("Error updating review text:", e)

    # --- ADMIN ACTIONS (REJECT / OVERTURN CHAT BAN FLOW) ---
    elif call.data.startswith("adm_rej_"):
        parts = call.data.split("_")
        reporter_id = int(parts[2])
        report_id = parts[3]
        
        data = report_data.get(reporter_id, {})
        target_raw = str(data.get('target', '')).replace("@", "").strip()
        target_id = get_real_id_from_tg(target_raw)

        conn = sqlite3.connect("anti_scam.db")
        cursor = conn.cursor()
        cursor.execute("UPDATE reports SET status = 'Denied' WHERE report_id = ?", (report_id,))
        conn.commit()
        conn.close()

        # UNBAN INJECTION SYSTEM
        conn = sqlite3.connect("anti_scam.db")
        cursor = conn.cursor()
        cursor.execute("SELECT group_id, username FROM banned_logs WHERE user_id = ? OR username = ?", (target_id, target_raw))
        banned_groups = cursor.fetchall()
        conn.close()

        if banned_groups:
            for group in banned_groups:
                gid, g_uname = group
                try:
                    bot.unban_chat_member(gid, int(target_id) if target_id.isdigit() else target_raw)
                    display_target = f"@{g_uname}" if g_uname else f"User ID: {target_id}"
                    bot.send_message(gid, f"<b>Appeal Approved:</b> {display_target} has been unbanned from this group.", parse_mode='HTML')
                except: pass
                    
            conn = sqlite3.connect("anti_scam.db")
            cursor = conn.cursor()
            cursor.execute("DELETE FROM banned_logs WHERE user_id = ? OR username = ?", (target_id, target_raw))
            conn.commit()
            conn.close()

        # Reporter ko rejection message bhej dena (Jo aapka pehle wala setting tha)
        bot.send_message(reporter_id, "❌ Your report has been denied. Try again later.")
        
        # Review Channel ke buttons hatana aur text update karna
        orig_caption = call.message.caption if call.message.caption else ""
        updated_caption = f"{orig_caption}\n\n<b>Status: Reject ❌</b>"
        
        try:
            bot.edit_message_caption(
                chat_id=REVIEW_CHANNEL_ID, 
                message_id=mid, 
                caption=updated_caption, 
                reply_markup=None, # Buttons remove ho gaye
                parse_mode='HTML'
            )
        except Exception as e:
            print("Error updating review text:", e)

@bot.message_handler(func=lambda msg: True)
def handle_text_inputs(msg):
    cid = msg.chat.id
    state = user_state.get(cid)
    u_name = msg.from_user.username if msg.from_user.username else ""

    if msg.text == "Cancel Report" or msg.text == "Create Appeal":
        if msg.text == "Create Appeal":
            user_state[cid] = "AWAITING_APPEAL_TEXT"
            bot.send_message(cid, "<b>Appeal Submission:</b>\nPlease write detailed reasons/proofs of why this flag is wrong:", reply_markup=get_cancel_markup(), parse_mode='HTML')
            return
            
        user_state.pop(cid, None)
        report_data.pop(cid, None)
        
        conn = sqlite3.connect("anti_scam.db")
        cursor = conn.cursor()
        cursor.execute("SELECT proof_link FROM reports WHERE (target = ? OR target = ? OR reporter_id = ?) AND status = 'Approved'", (str(cid), f"@{u_name}", str(cid)))
        scam_row = cursor.fetchone()
        conn.close()
        
        reply_markup_bottom = ReplyKeyboardMarkup(resize_keyboard=True)
        if scam_row:
            reply_markup_bottom.row(KeyboardButton("Create Appeal"))
            bot.send_photo(cid, photo=NEW_START_PNG, caption=f"{get_welcome_text()}\n\n<b>RESTRICTED:</b>\nYou've been marked as a scammer.", reply_markup=get_scammer_inline_markup(scam_row[0]), parse_mode='HTML')
            bot.send_message(cid, "Menu refreshed.", reply_markup=reply_markup_bottom)
        else:
            reply_markup_bottom.row(KeyboardButton("Cancel Report"))
            bot.send_photo(cid, photo=NEW_START_PNG, caption="Your session has been cancelled.", reply_markup=get_main_inline_markup(), parse_mode='HTML')
            bot.send_message(cid, "Menu refreshed.", reply_markup=reply_markup_bottom)
        return

    if not state: return

    # --- C. SCAMMER APPEAL SUBMISSION TEXT FLOW ---
    if state == "AWAITING_APPEAL_TEXT":
        appeal_reason = msg.text
        user_state.pop(cid, None)
        
        conn = sqlite3.connect("anti_scam.db")
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO reports (reporter_id, report_type, target, status) VALUES (?, 'Appeal Request', ?, 'Pending review')",
            (cid, f"@{u_name}" if u_name else f"ID: {cid}")
        )
        conn.commit()
        current_report_id = cursor.lastrowid
        conn.close()
        
        review_markup = InlineKeyboardMarkup()
        review_markup.row(
            InlineKeyboardButton("Approve Unban", callback_data=f"adm_rej_{cid}_{current_report_id}"), 
            InlineKeyboardButton("Keep Banned", callback_data=f"adm_app_{cid}_{current_report_id}")
        )
        
        review_msg = (
            f"<b>BAN APPEAL #{current_report_id}</b>\n\n"
            f"Appeal User: @{u_name} \n"
            f"Appeal User ID: <code>{cid}</code>\n\n"
            f"Reason Provided:\n<i>{appeal_reason}</i>"
        )
        bot.send_message(REVIEW_CHANNEL_ID, review_msg, reply_markup=review_markup, parse_mode='HTML')
        bot.send_message(cid, "Your appeal request has been submitted successfully to the administrators!", reply_markup=get_back_main_menu_markup())

    # --- A. USER REPORT STEPS BLOCK ---
    elif state == "AWAITING_USER_TARGET":
        resolved_id = get_real_id_from_tg(msg.text)
        report_data[cid]["target"] = msg.text
        report_data[cid]["target_id"] = resolved_id
        user_state[cid] = "AWAITING_DEAL_VALUE"
        bot.send_message(cid, "Enter the deal value:", reply_markup=get_cancel_markup())

    elif state == "AWAITING_DEAL_VALUE":
        report_data[cid]["deal_value"] = msg.text
        user_state[cid] = "AWAITING_SUMMARY"
        bot.send_message(cid, "Write a short summary of what happened:", reply_markup=get_cancel_markup())

    elif state == "AWAITING_SUMMARY":
        report_data[cid]["summary"] = msg.text
        user_state[cid] = "AWAITING_PROOF_CHANNEL"
        bot.send_message(cid, "Please create a telegram channel and send all the proof to the channel.\nOnce done, send me the channel url.", reply_markup=get_cancel_markup())

    elif state == "AWAITING_PROOF_CHANNEL":
        if "t.me/" not in msg.text:
            bot.send_message(cid, "Invalid link. Please enter a valid Telegram channel link:")
            return
        report_data[cid]["proof_channel"] = msg.text
        
        data = report_data.get(cid, {})
        user_state.pop(cid, None)
        
        try:
            rep_chat = bot.get_chat(cid)
            rep_username = f"@{rep_chat.username}" if rep_chat.username else "N/A"
        except: rep_username = "N/A"

        conn = sqlite3.connect("anti_scam.db")
        cursor = conn.cursor()
        cursor.execute("INSERT INTO reports (reporter_id, report_type, target, status) VALUES (?, 'User Report', ?, 'Pending review')", (cid, data.get('target', '@Unknown')))
        conn.commit()
        current_report_id = cursor.lastrowid
        conn.close()
        
        review_markup = InlineKeyboardMarkup()
        review_markup.row(InlineKeyboardButton("Approve ✅", callback_data=f"adm_app_{cid}_{current_report_id}"), InlineKeyboardButton("Reject ❌", callback_data=f"adm_rej_{cid}_{current_report_id}"))
        
        review_msg = (
            f"⚠️ <b>NEW REPORT #{current_report_id}</b>\n\n"
            f"👤 Reporter: {rep_username}\n"
            f"🆔 Reporter ID: <code>{cid}</code>\n\n"
            f"🎯 Target: {data.get('target')}\n"
            f"🆔 Target ID: <code>{data.get('target_id', 'Unknown')}</code>\n\n"
            f"💰 Amount: {data.get('deal_value', 'N/A')}\n"
            f"🔗 Proof: {data.get('proof_channel', 'N/A')}"
        )
        bot.send_message(REVIEW_CHANNEL_ID, review_msg, reply_markup=review_markup, parse_mode='HTML')
        bot.send_message(cid, "Your report has been submitted!", reply_markup=get_back_main_menu_markup())

    # --- B. IMPERSONATOR REPORT STEPS (DIRECT FLOW) ---
    elif state == "AWAITING_IMP_TARGET":
        resolved_id = get_real_id_from_tg(msg.text)
        report_data[cid]["target"] = msg.text
        report_data[cid]["target_id"] = resolved_id
        user_state[cid] = "AWAITING_REAL_TARGET"
        bot.send_message(cid, "Enter the real user's username or user ID:", reply_markup=get_cancel_markup())

    elif state == "AWAITING_REAL_TARGET":
        resolved_real_id = get_real_id_from_tg(msg.text)
        report_data[cid]["real_target"] = msg.text
        report_data[cid]["real_target_id"] = resolved_real_id
        
        data = report_data.get(cid, {})
        user_state.pop(cid, None)
        
        conn = sqlite3.connect("anti_scam.db")
        cursor = conn.cursor()
        cursor.execute("INSERT INTO reports (reporter_id, report_type, target, status) VALUES (?, 'Imp Report', ?, 'Pending review')", (cid, data.get('target', '@Unknown')))
        conn.commit()
        current_report_id = cursor.lastrowid
        conn.close()
        
        review_markup = InlineKeyboardMarkup()
        review_markup.row(InlineKeyboardButton("Approve ✅", callback_data=f"adm_app_{cid}_{current_report_id}"), InlineKeyboardButton("Reject ❌", callback_data=f"adm_rej_{cid}_{current_report_id}"))
        
        review_msg = (
            f"🟡 <b>IMPERSONATION REVIEW</b>\n\n"
            f"✅ Real: {data.get('real_target')}\n"
            f"🆔 Real ID: <code>{data.get('real_target_id', 'Unknown')}</code>\n\n"
            f"❌ Fake: {data.get('target')}\n"
            f"🆔 Fake ID: <code>{data.get('target_id', 'Unknown')}</code>\n\n"
            f"👤 Reporter ID: <code>{cid}</code>"
        )
        bot.send_message(REVIEW_CHANNEL_ID, review_msg, reply_markup=review_markup, parse_mode='HTML')
        bot.send_message(cid, "Your report has been submitted!", reply_markup=get_back_main_menu_markup())

@bot.message_handler(content_types=['new_chat_members'])
def auto_ban_scammers(msg):
    cid = msg.chat.id
    bot_member = bot.get_chat_member(cid, bot.get_me().id)
    if bot_member.status in ['administrator', 'creator']:
        for member in msg.new_chat_members:
            uid = str(member.id)
            u_name = member.username if member.username else ""
            
            conn = sqlite3.connect("anti_scam.db")
            cursor = conn.cursor()
            cursor.execute("SELECT report_id FROM reports WHERE (target = ? OR target = ?) AND status = 'Approved'", (uid, f"@{u_name}"))
            row = cursor.fetchone()
            conn.close()
            
            if row:
                try:
                    bot.ban_chat_member(cid, member.id)
                    conn = sqlite3.connect("anti_scam.db")
                    cursor = conn.cursor()
                    cursor.execute("INSERT OR REPLACE INTO banned_logs (group_id, user_id, username) VALUES (?, ?, ?)", (cid, uid, u_name))
                    conn.commit()
                    conn.close()
                    
                    display_name = f"@{member.username}" if member.username else "@N/A"
                    ban_msg = f"{display_name} ({uid}) has been marked as a scammer and banned from this group."
                    ban_markup = InlineKeyboardMarkup().row(InlineKeyboardButton("View Proof", url=f"https://t.me/{MAIN_CHANNEL_USERNAME}"))
                    bot.send_message(cid, ban_msg, reply_markup=ban_markup)
                except Exception as e:
                    print(f"Auto-Ban Fault: {e}")

def auto_promo():
    try:
        print("PROMO LOOP STARTED")
        for gid in list(group_ids):
            try:
                markup = InlineKeyboardMarkup()
                markup.add(InlineKeyboardButton("@fraudswatchlist", url="https://t.me/FraudsWatchlist"))
                bot.send_message(
                    gid,
                    "🌟 Keep your community safe with @fraudswatchlist\n\nReport scammers and verify profiles.",
                    reply_markup=markup
                )
                time.sleep(2)
            except:
                pass
        print("PROMO COMPLETE")
    except:
        pass

try:
    indian_tz = pytz.timezone("Asia/Kolkata")
    scheduler = BackgroundScheduler(timezone=indian_tz)
except:
    scheduler = BackgroundScheduler()

scheduler.add_job(auto_promo, 'interval', hours=1) 
scheduler.start()
app = Flask('')

@app.route('/')
def home():
    return "Anti-Scam Watchlist Bot is running 24/7 successfully!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_flask)
    t.start()

if __name__ == "__main__":
    print("Initializing Flask server for Render port binding...")
    keep_alive()
    
    print("Anti-Scam Flag Watchlist Engine Booted Successfully without errors...")
    bot.infinity_polling()