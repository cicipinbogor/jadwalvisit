import telebot
from telebot import types
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from datetime import datetime, timedelta
import os
import json
import re
import math
import random
import string
from fpdf import FPDF
from apscheduler.schedulers.background import BackgroundScheduler
from pydub import AudioSegment
import speech_recognition as sr

# ==========================================
# 1. KONFIGURASI AWAL & KREDENSIAL
# ==========================================
BOT_TOKEN = os.environ.get('BOT_TOKEN')
SHEET_ID = os.environ.get('SHEET_ID')
CREDS_JSON = os.environ.get('GOOGLE_CREDENTIALS')
MY_CHAT_IDS_STR = os.environ.get('MY_CHAT_ID', '') 
CALENDAR_ID = os.environ.get('CALENDAR_ID', 'primary')

CHAT_ID_LIST = [cid.strip() for cid in MY_CHAT_IDS_STR.split(',') if cid.strip()]
bot = telebot.TeleBot(BOT_TOKEN)

creds_dict = json.loads(CREDS_JSON)
scopes = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/calendar"
]
creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)

# Koneksi Google Sheets
client = gspread.authorize(creds)
sheet = client.open_by_key(SHEET_ID)
visit_ws = sheet.worksheet('Visit')
post_ws = sheet.worksheet('Posting')

try:
    keuangan_ws = sheet.worksheet('Keuangan')
except gspread.exceptions.WorksheetNotFound:
    keuangan_ws = sheet.add_worksheet(title="Keuangan", rows="1000", cols="4")
    keuangan_ws.append_row(["Tanggal", "Jenis", "Nominal", "Keterangan"])

# Koneksi Google Calendar
try:
    calendar_service = build('calendar', 'v3', credentials=creds)
except Exception as e:
    print(f"Warning: Google Calendar API belum diaktifkan. {e}")
    calendar_service = None


# ==========================================
# 2. VARIABEL & TEKS DEFAULT
# ==========================================
HARI_INDO = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
BULAN_INDO = ["Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September", "Oktober", "November", "Desember"]

DEFAULT_RATECARD = """📄 *RATE CARD & KERJA SAMA*

Halo! Terima kasih atas ketertarikannya bekerja sama. Berikut adalah penawaran paket liputan kuliner/review:

📦 *PAKET REGULER (Review Standar)*
• 1x Visit & Liputan Resto
• 1x Video tayang di TikTok & IG Reels
• ✨ *FREE Collab on Instagram*
• Keep video permanent
• Harga: Rp 500.000

🚀 *PAKET GACOR (Grand Opening / Event)*
• 1x Visit & Liputan Prioritas
• 1x Video (TikTok & IG Reels) dengan Hook Khusus Promosi
• Harga: Rp 800.000

➕ *ADDITIONAL MENU*
• Kualitas 4K: +Rp 300.000
• Additional Story (Instagram): +Rp 30.000/story

Silakan balas pesan ini jika ada paket yang sesuai! 🙏"""

DEFAULT_RATECARDUMKM = """🤝 *RATE CARD KHUSUS UMKM*

Halo! Sebagai bentuk *support* untuk usaha rintisan dan UMKM kuliner lokal, Cicipin Bogor menyediakan penawaran khusus:

🌱 *PAKET SUPPORT UMKM*
• 1x Visit & Liputan Outlet
• 1x Video tayang di IG Reels & TikTok
• Keep video permanent
• Harga Khusus: *Rp 400.000*

Mari maju bersama memajukan kuliner lokal! 🙏"""

DEFAULT_SK = """📝 *SYARAT & KETENTUAN (S&K)*
1. Pihak resto menyediakan menu andalan yang akan di-review.
2. DP 50% wajib dibayarkan maksimal H-3 sebelum visit.
3. Pelunasan sisa 50% dilakukan maksimal H-1 sebelum video tayang.
4. Jika klien membatalkan sepihak, DP dianggap hangus.
5. Hak cipta video sepenuhnya milik creator (Dilarang re-upload utuh)."""

try:
    settings_ws = sheet.worksheet('Pengaturan')
except gspread.exceptions.WorksheetNotFound:
    settings_ws = sheet.add_worksheet(title="Pengaturan", rows="10", cols="2")
    settings_ws.append_row(["Key", "Value"])
    settings_ws.append_row(["ratecard", DEFAULT_RATECARD])
    settings_ws.append_row(["ratecardumkm", DEFAULT_RATECARDUMKM])
    settings_ws.append_row(["sk", DEFAULT_SK])


# ==========================================
# 3. SISTEM LISENSI SAAS
# ==========================================
LICENSE_CACHE = {'exp_date': datetime.min, 'status': 'LOCKED', 'key': '', 'last_checked': None}

def generate_key():
    return "CCPN-" + ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))

def sync_lisensi_from_sheet():
    try:
        ws = sheet.worksheet('Lisensi')
    except gspread.exceptions.WorksheetNotFound:
        ws = sheet.add_worksheet(title="Lisensi", rows="10", cols="2")
        ws.append_row(["Key", "Value"])
        trial_exp = datetime.now() + timedelta(days=1)
        new_key = generate_key()
        ws.append_row(["Status", "TRIAL"])
        ws.append_row(["ExpiredDate", trial_exp.strftime("%d/%m/%Y %H:%M:%S")])
        ws.append_row(["AccessKey", new_key])
        
        LICENSE_CACHE.update({'status': "TRIAL", 'exp_date': trial_exp, 'key': new_key, 'last_checked': datetime.now()})
        return
        
    records = ws.get_all_records()
    data = {str(r.get('Key', '')).strip(): str(r.get('Value', '')).strip() for r in records}
    
    LICENSE_CACHE['status'] = data.get('Status', 'LOCKED')
    LICENSE_CACHE['key'] = data.get('AccessKey', '')
    try:
        LICENSE_CACHE['exp_date'] = datetime.strptime(data.get('ExpiredDate', ''), "%d/%m/%Y %H:%M:%S")
    except:
        LICENSE_CACHE['exp_date'] = datetime.min
    LICENSE_CACHE['last_checked'] = datetime.now()

sync_lisensi_from_sheet()

def check_lisensi_gate(message_or_call):
    is_call = hasattr(message_or_call, 'data')
    msg = message_or_call.message if is_call else message_or_call
    
    if not is_call and msg.text and msg.text.startswith('/lisensi'):
        return True
        
    if LICENSE_CACHE['last_checked'] is None or (datetime.now() - LICENSE_CACHE['last_checked']).total_seconds() > 300:
        sync_lisensi_from_sheet()
        
    if datetime.now() > LICENSE_CACHE['exp_date']:
        warning_text = (
            "⚠️ *BOT TERKUNCI (MASA AKTIF HABIS)* ⚠️\n\n"
            "Masa penggunaan bot kamu telah habis. Silakan hubungi Admin untuk meminta Kode Akses perpanjangan.\n\n"
            "🔑 Ketik perintah ini untuk mengaktifkan:\n`/lisensi [Kode_Akses]`"
        )
        if is_call:
            bot.answer_callback_query(message_or_call.id, "⚠️ Bot Terkunci! Cek pesan baru.", show_alert=True)
            bot.send_message(msg.chat.id, warning_text, parse_mode="Markdown")
        else:
            bot.reply_to(msg, warning_text, parse_mode="Markdown")
        return False
    return True


# ==========================================
# 4. FUNGSI UTILITY & HELPER
# ==========================================
def update_pengaturan(key, new_value):
    records = settings_ws.get_all_records()
    row_to_edit = None
    for idx, r in enumerate(records, start=2):
        if str(r.get('Key', '')).strip().lower() == key:
            row_to_edit = idx
            break
    if row_to_edit:
        settings_ws.update_cell(row_to_edit, 2, new_value)
    else:
        settings_ws.append_row([key, new_value])

def safe_date_parse(date_str):
    try: return datetime.strptime(str(date_str).strip().replace('-', '/'), "%d/%m/%Y")
    except: return datetime.min

def parse_tanggal_jam(teks):
    teks_lower = teks.lower()
    now = datetime.now()
    date_str, time_str = None, None

    if "hari ini" in teks_lower: date_str = now.strftime("%d/%m/%Y")
    elif "besok" in teks_lower: date_str = (now + timedelta(days=1)).strftime("%d/%m/%Y")
    elif "lusa" in teks_lower: date_str = (now + timedelta(days=2)).strftime("%d/%m/%Y")
    else:
        bulan_dict = {"januari": "01", "februari": "02", "maret": "03", "april": "04", "mei": "05", "juni": "06", "juli": "07", "agustus": "08", "september": "09", "oktober": "10", "november": "11", "desember": "12"}
        for bln_indo, bln_angka in bulan_dict.items():
            match = re.search(fr'(?:tanggal\s+)?(\d{{1,2}})\s+{bln_indo}(?:\s+(?:tahun\s+)?(\d{{4}}))?', teks_lower)
            if match:
                tgl = match.group(1).zfill(2)
                thn = match.group(2) if match.group(2) else str(now.year)
                date_str = f"{tgl}/{bln_angka}/{thn}"
                break
        if not date_str:
            m = re.search(r'(?:tanggal\s+)?(\d{1,2})(?:/|\s+bulan\s+)(\d{1,2})(?:(?:/|\s+tahun\s+)(\d{4}))?', teks_lower)
            if m:
                tgl, bln, thn = m.group(1).zfill(2), m.group(2).zfill(2), m.group(3) if m.group(3) else str(now.year)
                date_str = f"{tgl}/{bln}/{thn}"

    match_jam = re.search(r'jam\s+(\d{1,2})(?:[\.\:\s]([0-5]\d))?\s*(pagi|siang|sore|malam)?', teks_lower)
    if match_jam:
        h = int(match_jam.group(1))
        m = match_jam.group(2) if match_jam.group(2) else "00"
        ket = match_jam.group(3)
        if ket in ['siang', 'sore'] and h < 12: h += 12
        if ket == 'malam' and h < 12: h += 12
        if ket == 'malam' and h == 12: h = 12
        time_str = f"{str(h).zfill(2)}:{m}"

    return date_str, time_str

def extract_nominal(teks):
    teks_angka = teks.lower().replace("seribu", "1000").replace("sejuta", "1000000").replace(" ribu", "000").replace("ribu", "000").replace(" juta", "000000").replace("juta", "000000").replace(".", "").replace("rupiah", "").replace(",", "")
    angka_matches = re.findall(r'\d+', teks_angka)
    return max([int(x) for x in angka_matches]) if angka_matches else None

def push_to_google_calendar(resto_name, date_str, time_str):
    if not calendar_service: return False
    try:
        start_dt = datetime.strptime(f"{date_str} {time_str}", "%d/%m/%Y %H:%M")
        end_dt = start_dt + timedelta(hours=2)
        event_body = {
            'summary': f"🎥 Visit: {resto_name}",
            'location': 'Bogor',
            'description': f"Jadwal liputan Food Vlogger untuk {resto_name}.",
            'start': {'dateTime': start_dt.strftime("%Y-%m-%dT%H:%M:%S"), 'timeZone': 'Asia/Jakarta'},
            'end': {'dateTime': end_dt.strftime("%Y-%m-%dT%H:%M:%S"), 'timeZone': 'Asia/Jakarta'},
            'reminders': {'useDefault': False, 'overrides': [{'method': 'popup', 'minutes': 120}, {'method': 'popup', 'minutes': 1440}]},
        }
        calendar_service.events().insert(calendarId=CALENDAR_ID, body=event_body).execute()
        return True
    except: return False


# ==========================================
# 5. UI KEYBOARDS & MENU
# ==========================================
def get_main_menu_markup():
    markup = telebot.types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        telebot.types.InlineKeyboardButton('📅 Jadwal Visit', callback_data='menu_visit'),
        telebot.types.InlineKeyboardButton('🚀 Jadwal Posting', callback_data='menu_posting'),
        telebot.types.InlineKeyboardButton('💰 Rekap Keuangan', callback_data='menu_rekap'),
        telebot.types.InlineKeyboardButton('📑 Administrasi', callback_data='menu_admin'),
        telebot.types.InlineKeyboardButton('🎙️ Bantuan Suara', callback_data='menu_helpvoice'),
        telebot.types.InlineKeyboardButton('⚙️ Rate Card & S&K', callback_data='menu_settings')
    )
    return markup

def get_back_markup():
    markup = telebot.types.InlineKeyboardMarkup()
    markup.add(telebot.types.InlineKeyboardButton('🔙 Kembali ke Menu', callback_data='menu_main'))
    return markup

def get_pagination_markup(current_page, total_items, prefix):
    markup = telebot.types.InlineKeyboardMarkup(row_width=3)
    buttons = []
    total_pages = math.ceil(total_items / 10)
    
    if current_page > 0: buttons.append(telebot.types.InlineKeyboardButton('⬅️ Prev', callback_data=f'{prefix}_{current_page - 1}'))
    buttons.append(telebot.types.InlineKeyboardButton(f'{current_page + 1} / {total_pages}', callback_data='ignore'))
    if current_page < total_pages - 1: buttons.append(telebot.types.InlineKeyboardButton('Next ➡️', callback_data=f'{prefix}_{current_page + 1}'))
        
    if buttons: markup.row(*buttons)
    markup.add(telebot.types.InlineKeyboardButton('🔙 Kembali ke Menu', callback_data='menu_main'))
    return markup

# ==========================================
# 6. ROUTER PERINTAH TEKS DASAR & LISENSI
# ==========================================
@bot.message_handler(commands=['start', 'menu'])
def send_welcome(message):
    if not check_lisensi_gate(message): return
    teks = "🤖 *Bot J.A.R.V.I.S Cicipin Bogor Aktif!*\n\nHalo bos! Mau ngurusin apa kita hari ini?\n\nSilakan tap menu di bawah pesan ini, atau kirim *Voice Note* untuk kasih perintah (jadwalin visit, rekap uang, dll) 🎙️🔥"
    bot.reply_to(message, teks, reply_markup=get_main_menu_markup(), parse_mode='Markdown')

@bot.message_handler(commands=['lisensi'])
def proses_lisensi(message):
    parts = message.text.split()
    if len(parts) < 2:
        bot.reply_to(message, "⚠️ Format salah. Ketik: `/lisensi [Kode_Akses]`", parse_mode="Markdown")
        return
        
    input_key = parts[1].strip()
    sync_lisensi_from_sheet()
    
    if input_key == LICENSE_CACHE.get('key', '') and input_key != "":
        new_exp = datetime.now() + timedelta(days=30)
        new_key = generate_key()
        
        ws = sheet.worksheet('Lisensi')
        try:
            c1 = ws.find("Status")
            ws.update_cell(c1.row, 2, "ACTIVE")
            c2 = ws.find("ExpiredDate")
            ws.update_cell(c2.row, 2, new_exp.strftime("%d/%m/%Y %H:%M:%S"))
            c3 = ws.find("AccessKey")
            ws.update_cell(c3.row, 2, new_key)
        except Exception as e:
            pass 
            
        LICENSE_CACHE['status'] = "ACTIVE"
        LICENSE_CACHE['exp_date'] = new_exp
        LICENSE_CACHE['key'] = new_key
        LICENSE_CACHE['last_checked'] = datetime.now()
        
        bot.reply_to(message, "✅ *Lisensi Berhasil Diaktifkan!*\n\nBot telah terbuka dan aktif selama 30 hari ke depan.", parse_mode="Markdown")
        send_welcome(message)
    else:
        bot.reply_to(message, "❌ *Kunci Akses Salah atau Kadaluarsa!* Silakan hubungi Admin untuk mendapatkan kunci terbaru.", parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data.startswith('menu_') or call.data.startswith('visit_page_') or call.data.startswith('post_page_') or call.data == 'ignore')
def handle_inline_menu(call):
    bot.answer_callback_query(call.id)
    if call.data == 'ignore': return
    if not check_lisensi_gate(call): return

    if call.data == 'menu_main':
        teks = "🤖 *Bot J.A.R.V.I.S Cicipin Bogor Aktif!*\n\nHalo bos! Mau ngurusin apa kita hari ini?\n\nSilakan tap menu di bawah, atau kirim *Voice Note* 🎙️🔥"
        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=teks, reply_markup=get_main_menu_markup(), parse_mode='Markdown')
    elif call.data == 'menu_visit': list_visit(call.message, is_edit=True, page=0)
    elif call.data.startswith('visit_page_'): list_visit(call.message, is_edit=True, page=int(call.data.split('_')[-1]))
    elif call.data == 'menu_posting': list_posting(call.message, is_edit=True, page=0)
    elif call.data.startswith('post_page_'): list_posting(call.message, is_edit=True, page=int(call.data.split('_')[-1]))
    elif call.data == 'menu_rekap': rekap_bulan(call.message, is_edit=True)
    elif call.data == 'menu_helpvoice': send_help_voice(call.message, is_edit=True)
    elif call.data == 'menu_admin':
        teks = "💼 *MENU ADMINISTRASI KLIEN*\n\n📝 *SPK:*\n`/spk Nama Resto - Nama Paket`\n\n📄 *Invoice DP (50%):*\n`/invoice Nama Resto - Item=Harga`\n\n📄 *Invoice Full:*\n`/invoicefull Nama Resto - Item=Harga`\n\n🧾 *Kwitansi:*\n`/kwitansi Nama Resto - Nominal - Keterangan`"
        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=teks, reply_markup=get_back_markup(), parse_mode='Markdown')
    elif call.data == 'menu_settings':
        teks = "⚙️ *PENGATURAN RATE CARD & S&K*\n\nPilih untuk melihat/mengedit:\n1. /ratecard (Edit: /editrc)\n2. /ratecardumkm (Edit: /editrcumkm)\n3. /sk (Edit: /editsk)"
        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=teks, reply_markup=get_back_markup(), parse_mode='Markdown')


# ==========================================
# 7. ROUTING PERINTAH SUARA (SUPER SMART NLP)
# ==========================================
@bot.message_handler(commands=['help', 'helpvoice'])
def send_help_voice(message, is_edit=False):
    if not check_lisensi_gate(message): return
    teks = (
        "🎙️ *PANDUAN VOICE COMMAND*\n\n"
        "• *Visit:* _\"Bot, tambah visit besok jam 2 siang untuk Brano Pizzeria\"_\n"
        "• *Centang:* _\"Bot, centang visit resto Brano Pizzeria\"_\n"
        "• *Batal:* _\"Bot, batal visit besok jam 2 siang\"_\n"
        "• *Posting:* _\"Bot, tambah posting lusa konten Bakso Mercon\"_\n"
        "• *Invoice:* _\"Bot, bikin invoice untuk Brano paket Gacor harga 800 ribu lunas\"_\n"
        "• *SPK:* _\"Bot, bikin SPK untuk Kopi Daun paket Gacor\"_\n"
        "• *Kwitansi:* _\"Bot, bikin kuitansi buat Sate Maranggi nominal 400 ribu\"_\n"
        "• *Keuangan:* _\"Bot, catat pengeluaran beli bensin 50 ribu\"_"
    )
    if is_edit: bot.edit_message_text(chat_id=message.chat.id, message_id=message.message_id, text=teks, parse_mode='Markdown', reply_markup=get_back_markup())
    else: bot.reply_to(message, teks, parse_mode='Markdown', reply_markup=get_back_markup())

@bot.message_handler(content_types=['voice'])
def handle_voice_global(message):
    if not check_lisensi_gate(message): return
    try:
        msg = bot.reply_to(message, "⏳ _Sedang mencerna suara..._", parse_mode="Markdown")
        
        file_info = bot.get_file(message.voice.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        ogg_path, wav_path = f"v_{message.message_id}.ogg", f"v_{message.message_id}.wav"
        
        with open(ogg_path, 'wb') as new_file: new_file.write(downloaded_file)
        AudioSegment.from_file(ogg_path, format="ogg").export(wav_path, format="wav")
        
        r = sr.Recognizer()
        with sr.AudioFile(wav_path) as source: teks_hasil = r.recognize_google(r.record(source), language="id-ID")
        os.remove(ogg_path)
        os.remove(wav_path)
        
        teks_lower = teks_hasil.lower()
        bot.edit_message_text(f"🗣️ *Terdengar:* _{teks_hasil}_\n🚀 _Memproses..._", chat_id=message.chat.id, message_id=msg.message_id, parse_mode="Markdown")

        # Routing Perintah Bantuan
        if any(kata in teks_lower for kata in ["help", "bantuan", "tutorial", "panduan", "cara pakai", "cara perintah"]):
            return send_help_voice(message)
        
        # Routing Lihat Jadwal / Rekap
        elif any(kata in teks_lower for kata in ["lihat", "cek", "rekap", "kirim", "tampil", "tunjuk"]):
            if "posting" in teks_lower or "konten" in teks_lower: return list_posting(message)
            elif "keuangan" in teks_lower or "bulan" in teks_lower: return rekap_bulan(message)
            else: return list_visit(message) 
            
        elif any(kata in teks_lower for kata in ["centang", "selesai", "tandai"]) and "visit" in teks_lower:
            resto = re.search(r'(?:resto|di|ke|namanya)\s+([a-zA-Z0-9\s]+)', teks_lower)
            resto_str = resto.group(1).strip() if resto else teks_lower.replace("centang","").replace("visit","").replace("resto","").strip()
            message.text = f"/centangvisit {resto_str}"
            return mark_done_visit(message)
            
        elif any(kata in teks_lower for kata in ["batal", "hapus"]) and "visit" in teks_lower:
            date_str, time_str = parse_tanggal_jam(teks_lower)
            if not date_str or not time_str: return bot.send_message(message.chat.id, "⚠️ Sebutkan tanggal & jam visit dengan jelas.")
            message.text = f"/batalvisit {date_str} {time_str}"
            return cancel_visit(message)
            
        elif any(kata in teks_lower for kata in ["batal", "hapus"]) and "posting" in teks_lower:
            date_str, _ = parse_tanggal_jam(teks_lower)
            if not date_str: return bot.send_message(message.chat.id, "⚠️ Sebutkan tanggal posting yang mau dihapus.")
            message.text = f"/batalposting {date_str}"
            return cancel_posting(message)

        # FITUR ADMINISTRASI
        elif "invoice" in teks_lower:
            is_full = "full" in teks_lower or "lunas" in teks_lower
            nominal = extract_nominal(teks_lower)
            
            if nominal:
                resto, item = "Klien", "Paket Konten"
                m_resto = re.search(r'(?:invoice)(?:\s+untuk|\s+resto|\s+buat)?\s+(.+?)\s+(?:harga|seharga|nominal|sebesar|\d)', teks_lower)
                if m_resto: 
                    raw_text = m_resto.group(1).strip()
                    if " paket " in f" {raw_text} ":
                        r_split = re.split(r'\spaket\s', raw_text, 1)
                        resto = r_split[0].strip().title()
                        item = "Paket " + r_split[1].strip().title()
                    else:
                        resto = raw_text.title()
                
                cmd = "/invoicefull" if is_full else "/invoice"
                message.text = f"{cmd} {resto} - {item}={nominal}"
                return handle_invoice(message) 
            else:
                return bot.send_message(message.chat.id, "⚠️ Format invoice kurang jelas. Mohon sebutkan nominal harganya.")
                
        elif "kwitansi" in teks_lower or "kuitansi" in teks_lower:
            nominal_kwt = extract_nominal(teks_lower)
            if nominal_kwt:
                resto, ket = "Klien", "Pembayaran Liputan"
                
                m_resto = re.search(r'(?:kwitansi|kuitansi)(?:\s+untuk|\s+resto|\s+buat)?\s+(.+?)\s+(?:sebesar|nominal|harga|seharga|\d)', teks_lower)
                if m_resto: 
                    raw_text = m_resto.group(1).strip()
                    if " paket " in f" {raw_text} ":
                        r_split = re.split(r'\spaket\s', raw_text, 1)
                        resto = r_split[0].strip().title()
                        ket = "Paket " + r_split[1].strip().capitalize()
                    else:
                        resto = raw_text.title()
                
                m_ket = re.search(r'(?:untuk|buat)\s+([a-zA-Z0-9\s]+)$', teks_lower)
                if m_ket and m_ket.group(1).strip().lower() not in resto.lower():
                    ket = m_ket.group(1).strip().capitalize()
                    
                message.text = f"/kwitansi {resto} - {nominal_kwt} - {ket}"
                return generate_kwitansi(message) 
            return bot.send_message(message.chat.id, "⚠️ Format kuitansi kurang jelas. Sebutkan nominalnya.")
            
        elif "spk" in teks_lower:
            resto, paket = "Klien", "Paket Liputan"
            
            m_resto = re.search(r'(?:spk)(?:\s+untuk|\s+resto|\s+buat)?\s+(.+?)\s+(?:dengan\s+paket|paket)', teks_lower)
            if m_resto: 
                resto = m_resto.group(1).strip().title()
            else:
                mr = re.search(r'(?:spk)(?:\s+untuk|\s+resto|\s+buat)?\s+([a-zA-Z0-9\s]+)', teks_lower)
                if mr: resto = mr.group(1).strip().title()
                
            m_paket = re.search(r'(?:paket)\s+([a-zA-Z0-9\s]+)', teks_lower)
            if m_paket: paket = "Paket " + m_paket.group(1).strip().title()
            
            message.text = f"/spk {resto} - {paket}"
            return generate_spk(message) 

        # JADWAL & PERINTAH LAINNYA
        elif any(kata in teks_lower for kata in ["visit", "tambah jadwal"]):
            date_str, time_str = parse_tanggal_jam(teks_lower)
            resto = re.search(r'(?:di\s+resto|di|resto|ke|untuk|buat)\s+([a-zA-Z0-9\s]+)', teks_lower)
            resto_str = resto.group(1).strip().title() if resto else "Resto Baru"
            message.text = f"/tambahvisit {date_str or datetime.now().strftime('%d/%m/%Y')} {time_str or '12:00'} {resto_str}"
            return add_visit(message)
            
        elif "posting" in teks_lower or "konten" in teks_lower:
            date_str, _ = parse_tanggal_jam(teks_lower)
            resto = re.search(r'(?:konten|resto|untuk|buat)\s+([a-zA-Z0-9\s]+)', teks_lower)
            resto_str = resto.group(1).strip().title() if resto else "Konten Baru"
            message.text = f"/tambahposting {date_str or datetime.now().strftime('%d/%m/%Y')} {resto_str}"
            return add_posting(message)
            
        elif any(kata in teks_lower for kata in ["rate card", "ratecard", "red card", "rekad", "harga paket", "price list"]):
            if "umkm" in teks_lower:
                message.text = "/ratecardumkm"
                return send_docs(message)
            message.text = "/ratecard"
            return send_docs(message)
            
        elif any(kata in teks_lower for kata in ["syarat dan ketentuan", "aturan main", "s & k"]):
            message.text = "/sk"
            return send_docs(message)
            
        else:
            nominal = extract_nominal(teks_lower)
            if not nominal: return bot.send_message(message.chat.id, "⚠️ Maaf, perintah suara tidak dipahami.")
            tgl = datetime.now().strftime("%d/%m/%Y")
            if any(k in teks_lower for k in ["pemasukan", "terima", "cair", "pelunasan"]):
                keuangan_ws.append_row([tgl, "Pemasukan", nominal, teks_hasil.capitalize()])
                bot.send_message(message.chat.id, "✅ *Pemasukan Dicatat via Suara!*", parse_mode="Markdown")
            elif any(k in teks_lower for k in ["keluar", "beli", "bayar", "bensin", "parkir", "makan"]):
                keuangan_ws.append_row([tgl, "Pengeluaran", nominal, teks_hasil.capitalize()])
                bot.send_message(message.chat.id, "📉 *Pengeluaran Dicatat via Suara!*", parse_mode="Markdown")

    except Exception as e:
        bot.reply_to(message, f"⚠️ Kesalahan sistem voice: {e}")


# ==========================================
# 8. HANDLERS DOKUMEN & ADMIN (PDF PREMIUM)
# ==========================================
def build_invoice_pdf(resto, parsed_items, total_harga, no_inv, tgl_sekarang, is_full=False):
    pdf = FPDF()
    pdf.add_page()
    
    if os.path.exists("logo.png"):
        pdf.image("logo.png", x=10, y=8, w=28)
        pdf.set_xy(42, 12)
    else:
        pdf.set_xy(10, 12)
        
    pdf.set_font("helvetica", "B", 24)
    pdf.set_text_color(0, 0, 0)
    pdf.cell(0, 8, "Cicipin Bogor", ln=True)
    
    if os.path.exists("logo.png"): pdf.set_x(42)
    pdf.set_font("helvetica", "", 10)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 5, "Instagram Food Vlogger & Digital Content Creator", ln=True)
    
    if os.path.exists("logo.png"): pdf.set_x(42)
    pdf.set_font("helvetica", "I", 9)
    pdf.set_text_color(120, 120, 120)
    pdf.cell(0, 5, "WhatsApp: 085173134492 | Email: cicipinbogor@gmail.com", ln=True)
    
    current_y = pdf.get_y()
    if os.path.exists("logo.png") and current_y < 40:
        pdf.set_y(42)
    else:
        pdf.ln(8)
        
    pdf.set_draw_color(200, 200, 200)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(10)
    
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("helvetica", "B", 18)
    pdf.cell(0, 10, "INVOICE TAGIHAN", ln=True)
    pdf.ln(2)
    
    pdf.set_font("helvetica", "B", 10)
    pdf.cell(30, 6, "No. Invoice", 0, 0)
    pdf.set_font("helvetica", "", 10)
    pdf.cell(60, 6, f": {no_inv}", 0, 0)
    
    pdf.set_font("helvetica", "B", 10)
    pdf.cell(30, 6, "Klien / Resto", 0, 0)
    pdf.set_font("helvetica", "", 10)
    pdf.cell(0, 6, f": {resto}", ln=True)
    
    pdf.set_font("helvetica", "B", 10)
    pdf.cell(30, 6, "Tanggal", 0, 0)
    pdf.set_font("helvetica", "", 10)
    pdf.cell(60, 6, f": {tgl_sekarang}", 0, 1)
    pdf.ln(10)
    
    # Tabel Header
    pdf.set_font("helvetica", "B", 11)
    pdf.set_fill_color(240, 240, 240) 
    pdf.set_draw_color(180, 180, 180)
    pdf.cell(120, 10, "Deskripsi Item", border=1, align="C", fill=True)
    pdf.cell(70, 10, "Biaya (IDR)", border=1, ln=True, align="C", fill=True)
    
    pdf.set_font("helvetica", "", 11)
    
    # Cetak Item dengan Wrap Text Otomatis
    for item in parsed_items:
        text = f" {item['name']}"
        price_text = f"Rp {item['price']:,}"
        
        x = pdf.get_x()
        y = pdf.get_y()
        
        # Cetak deskripsi (otomatis turun ke bawah kalau kepanjangan)
        pdf.multi_cell(120, 8, text, border=1, align="L")
        
        # Kalkulasi tinggi kotak yang baru saja dibuat
        next_y = pdf.get_y()
        row_h = next_y - y
        
        # Pindah kursor ke sebelah kanan untuk cetak harga dengan tinggi yang sama
        pdf.set_xy(x + 120, y)
        pdf.cell(70, row_h, price_text, border=1, ln=True, align="R")
        
        # Kembalikan kursor ke kiri bawah untuk baris selanjutnya
        pdf.set_xy(10, next_y)
    
    # Cetak Total
    if not is_full:
        pdf.set_font("helvetica", "B", 11)
        pdf.cell(120, 10, "Total Keseluruhan", border=1, align="R", fill=True)
        pdf.cell(70, 10, f"Rp {total_harga:,}", border=1, ln=True, align="R", fill=True)
        
        dp_harga = int(total_harga * 0.5)
        pdf.cell(120, 10, "Down Payment (DP 50% untuk Kunci Jadwal)", border=1, align="R")
        pdf.cell(70, 10, f"Rp {dp_harga:,}", border=1, ln=True, align="R")
    else:
        pdf.set_font("helvetica", "B", 11)
        pdf.cell(120, 10, "Total Tagihan (Pembayaran Penuh / Full)", border=1, align="R", fill=True)
        pdf.cell(70, 10, f"Rp {total_harga:,}", border=1, ln=True, align="R", fill=True)
        
    pdf.ln(15)
    
    pdf.set_font("helvetica", "B", 11)
    pdf.cell(0, 6, "Metode Pembayaran Transfer:", ln=True)
    pdf.set_font("helvetica", "", 11)
    pdf.cell(0, 6, "- Bank: Seabank", ln=True)
    pdf.cell(0, 6, "- No. Rekening: 901177950990", ln=True)
    pdf.cell(0, 6, "- Atas Nama: Afrizal", ln=True)
    pdf.ln(15)
    
    pdf.set_font("helvetica", "I", 9)
    pdf.set_text_color(150, 150, 150)
    if not is_full:
        pdf.cell(0, 5, "*Mohon kirimkan bukti transfer jika pembayaran DP telah dilakukan.", ln=True, align="C")
    else:
        pdf.cell(0, 5, "*Mohon kirimkan bukti transfer jika proses pembayaran pelunasan telah dilakukan.", ln=True, align="C")
        
    pdf.cell(0, 5, "Terima kasih atas kepercayaan Anda bekerja sama dengan Cicipin Bogor!", ln=True, align="C")
    
    return pdf

@bot.message_handler(commands=['invoice', 'invoicefull'])
def handle_invoice(message):
    if not check_lisensi_gate(message): return
    try:
        is_full = 'full' in message.text.split()[0]
        parts = message.text.split(maxsplit=1)[1].split('-', 1)
        resto = parts[0].strip()
        items = [{"name": i.split('=')[0].strip(), "price": int(i.split('=')[1].replace('.','').replace('Rp','').strip())} for i in parts[1].split(';') if '=' in i]
        total = sum(i['price'] for i in items)
        no_inv = f"INV/CCPN/{datetime.now().strftime('%Y%m%d')}/{str(message.message_id)[-4:]}"
        
        pdf = build_invoice_pdf(resto, items, total, no_inv, datetime.now().strftime("%d/%m/%Y"), is_full)
        pdf_name = f"Invoice_{resto.replace(' ', '')}.pdf"
        pdf.output(pdf_name)
        
        caption = f"✅ *Invoice Dibuat!*\nKlien: {resto}\nTotal: Rp{total:,}\nTagihan: Rp{total if is_full else int(total*0.5):,}"
        with open(pdf_name, 'rb') as f: bot.send_document(message.chat.id, f, caption=caption, parse_mode='Markdown')
        os.remove(pdf_name)
    except Exception as e: bot.reply_to(message, "⚠️ Format salah. Gunakan: /invoice Nama - Item=100000")

@bot.message_handler(commands=['kwitansi'])
def generate_kwitansi(message):
    if not check_lisensi_gate(message): return
    try:
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2 or '-' not in parts[1]: return bot.reply_to(message, "⚠️ Format: /kwitansi Resto - Nominal - Keterangan")
            
        subparts = parts[1].split('-')
        resto = subparts[0].strip()
        nominal = int(subparts[1].strip().replace('.', '').replace('Rp', '').strip())
        keterangan = subparts[2].strip()
        tgl_sekarang = datetime.now().strftime("%d/%m/%Y")
        no_kwt = f"KWT/CCPN/{datetime.now().strftime('%Y%m%d')}/{str(message.message_id)[-4:]}"
        
        pdf_name = f"Kwitansi_{resto.replace(' ', '')}.pdf"
        pdf = FPDF()
        pdf.add_page()
        
        if os.path.exists("logo.png"):
            pdf.image("logo.png", x=10, y=8, w=28)
            pdf.set_xy(42, 12)
        else:
            pdf.set_xy(10, 12)
            
        pdf.set_font("helvetica", "B", 24)
        pdf.set_text_color(0, 0, 0)
        pdf.cell(0, 8, "Cicipin Bogor", ln=True)
        
        if os.path.exists("logo.png"): pdf.set_x(42)
        pdf.set_font("helvetica", "", 10)
        pdf.set_text_color(100, 100, 100)
        pdf.cell(0, 5, "Instagram Food Vlogger & Digital Content Creator", ln=True)
        
        if os.path.exists("logo.png"): pdf.set_x(42)
        pdf.set_font("helvetica", "I", 9)
        pdf.set_text_color(120, 120, 120)
        pdf.cell(0, 5, "WhatsApp: 085173134492 | Email: cicipinbogor@gmail.com", ln=True)
        
        current_y = pdf.get_y()
        if os.path.exists("logo.png") and current_y < 40:
            pdf.set_y(42)
        else:
            pdf.ln(8)
            
        pdf.set_draw_color(200, 200, 200)
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(12)
        
        pdf.set_text_color(0, 0, 0)
        pdf.set_font("helvetica", "B", 18)
        pdf.cell(0, 10, "KWITANSI PEMBAYARAN", ln=True, align="C")
        pdf.ln(8)
        
        pdf.set_font("helvetica", "B", 11)
        pdf.cell(45, 8, "No. Kwitansi", 0, 0); pdf.set_font("helvetica", "", 11); pdf.cell(0, 8, f": {no_kwt}", ln=True)
        pdf.set_font("helvetica", "B", 11)
        pdf.cell(45, 8, "Telah Terima Dari", 0, 0); pdf.set_font("helvetica", "", 11); pdf.cell(0, 8, f": {resto}", ln=True)
        pdf.set_font("helvetica", "B", 11)
        pdf.cell(45, 8, "Uang Sejumlah", 0, 0); pdf.set_font("helvetica", "B", 14); pdf.set_text_color(0, 100, 0); pdf.cell(0, 8, f": Rp {nominal:,}", ln=True)
        pdf.set_text_color(0, 0, 0)
        pdf.set_font("helvetica", "B", 11)
        pdf.cell(45, 8, "Untuk Pembayaran", 0, 0); pdf.set_font("helvetica", "", 11); pdf.multi_cell(0, 8, f": {keterangan}")
        pdf.ln(15)
        
        pdf.set_font("helvetica", "", 11)
        pdf.cell(120, 6, "", 0, 0)
        pdf.cell(70, 6, f"Bogor, {tgl_sekarang}", 0, 1, "C")
        
        y_ttd = pdf.get_y()
        lunas_file = next((ext for ext in ["lunas.jpg", "lunas.png", "LUNAS.png"] if os.path.exists(ext)), None)
        if lunas_file: pdf.image(lunas_file, x=20, y=y_ttd - 8, w=55)
            
        ttd_file = next((ext for ext in ["ttd.png", "ttd.jpg", "TTD.png"] if os.path.exists(ext)), None)
        if ttd_file: pdf.image(ttd_file, x=152.5, y=y_ttd + 2, w=25)
        
        pdf.ln(30)
        pdf.set_font("helvetica", "BU", 11)
        pdf.cell(120, 6, "", 0, 0)
        pdf.cell(70, 6, "Cicipin Bogor", 0, 1, "C")
        pdf.set_font("helvetica", "I", 9)
        pdf.set_text_color(150, 150, 150)
        pdf.cell(120, 6, "", 0, 0)
        pdf.cell(70, 4, "Verified Official Receipt", 0, 1, "C")
        
        pdf.output(pdf_name)
        with open(pdf_name, 'rb') as f: bot.send_document(message.chat.id, f, caption=f"✅ Kwitansi Lunas untuk {resto}", parse_mode='Markdown')
        os.remove(pdf_name)
    except Exception as e: bot.reply_to(message, f"Kesalahan Kwitansi: {e}")

@bot.message_handler(commands=['spk'])
def generate_spk(message):
    if not check_lisensi_gate(message): return
    try:
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2 or '-' not in parts[1]: return bot.reply_to(message, "⚠️ Format: /spk Resto - Nama Paket")
            
        resto, paket = parts[1].split('-', 1)
        resto, paket = resto.strip(), paket.strip()
        tgl_sekarang = datetime.now().strftime("%d/%m/%Y")
        
        pdf_name = f"SPK_{resto.replace(' ', '')}.pdf"
        pdf = FPDF()
        pdf.add_page()
        
        if os.path.exists("logo.png"):
            pdf.image("logo.png", x=10, y=8, w=28)
            pdf.set_xy(42, 12)
        else:
            pdf.set_xy(10, 12)

        pdf.set_font("helvetica", "B", 24)
        pdf.set_text_color(0, 0, 0)
        pdf.cell(0, 8, "Cicipin Bogor", ln=True)

        if os.path.exists("logo.png"): pdf.set_x(42)
        pdf.set_font("helvetica", "", 10)
        pdf.set_text_color(100, 100, 100)
        pdf.cell(0, 5, "Instagram Food Vlogger & Digital Content Creator", ln=True)

        if os.path.exists("logo.png"): pdf.set_x(42)
        pdf.set_font("helvetica", "I", 9)
        pdf.set_text_color(120, 120, 120)
        pdf.cell(0, 5, "WhatsApp: 085173134492 | Email: cicipinbogor@gmail.com", ln=True)

        current_y = pdf.get_y()
        if os.path.exists("logo.png") and current_y < 40:
            pdf.set_y(42)
        else:
            pdf.ln(8)

        pdf.set_draw_color(200, 200, 200)
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(10)

        pdf.set_text_color(0, 0, 0)
        pdf.set_font("helvetica", "B", 14)
        pdf.cell(0, 8, "SURAT PERJANJIAN KERJA SAMA (MoU)", ln=True, align="C")
        pdf.ln(8)

        pdf.set_font("helvetica", "", 11)
        teks_pembuka = f"Pada hari ini, tanggal {tgl_sekarang}, disepakati kesepakatan kerja sama promosi digital (Food Vlogger Review) antara:"
        pdf.multi_cell(0, 6, teks_pembuka)
        pdf.ln(4)

        pdf.set_font("helvetica", "B", 11)
        pdf.cell(35, 6, "Pihak Pertama", 0, 0); pdf.set_font("helvetica", "", 11); pdf.cell(0, 6, ": Cicipin Bogor (Kreator Konten)", ln=True)
        pdf.set_font("helvetica", "B", 11)
        pdf.cell(35, 6, "Pihak Kedua", 0, 0); pdf.set_font("helvetica", "", 11); pdf.cell(0, 6, f": {resto} (Klien / Resto)", ln=True)
        pdf.ln(4)

        pdf.multi_cell(0, 6, f"Kedua belah pihak sepakat untuk bekerja sama dalam pembuatan konten review kuliner dengan rincian paket: {paket}. Berikut adalah syarat dan ketentuan yang mengikat kedua belah pihak secara sah:")
        pdf.ln(4)

        pdf.set_font("helvetica", "B", 11)
        pdf.cell(0, 6, "Pasal 1: Proses Liputan & Hak Konten", ln=True)
        pdf.set_font("helvetica", "", 11)
        pdf.multi_cell(0, 6, "- Pihak Kedua menyediakan menu andalan yang akan di-review secara gratis untuk kebutuhan liputan visual dan pencicipan.\n- Proses syuting memakan waktu sekitar 1-2 jam di lokasi Pihak Kedua.")
        pdf.ln(2)

        pdf.set_font("helvetica", "B", 11)
        pdf.cell(0, 6, "Pasal 2: Sistem Pembayaran & Reschedule", ln=True)
        pdf.set_font("helvetica", "", 11)
        pdf.multi_cell(0, 6, "- Down Payment (DP) 50% wajib dibayarkan maksimal H-3 sebelum jadwal visit untuk mengunci jadwal (Slot).\n- Pelunasan 50% dilakukan maksimal H-1 sebelum video resmi ditayangkan di media sosial.\n- Jika Pihak Kedua membatalkan sepihak setelah DP dibayarkan, maka DP dianggap hangus.\n- Reschedule maksimal diinfokan H-2 sebelum hari liputan.")
        pdf.ln(2)

        pdf.set_font("helvetica", "B", 11)
        pdf.cell(0, 6, "Pasal 3: Hak Cipta & Kebijakan Upload Ulang", ln=True)
        pdf.set_font("helvetica", "", 11)
        pdf.multi_cell(0, 6, "- Pihak Kedua berhak mendapat revisi video maksimal 1x (hanya berlaku untuk revisi minor berupa ralat teks harga, alamat, atau penulisan nama).\n- Hak Cipta video sepenuhnya merupakan milik Pihak Pertama (Cicipin Bogor).\n- Pihak Kedua DILARANG KERAS MENGUNGGAH ULANG (re-upload) video utuh ke platform manapun (TikTok, IG, FB) tanpa membeli opsi Hak Milik (Owning Content) terlebih dahulu. Pihak Kedua hanya diperbolehkan melakukan fitur 'Share' atau 'Collab'.")
        pdf.ln(12)

        pdf.set_font("helvetica", "", 11)
        pdf.cell(95, 6, "Pihak Pertama,", 0, 0, "C")
        pdf.cell(95, 6, "Pihak Kedua,", 0, 1, "C")

        y_ttd = pdf.get_y()
        ttd_file = next((ext for ext in ["ttd.png", "ttd.jpg", "TTD.png"] if os.path.exists(ext)), None)
        if ttd_file: pdf.image(ttd_file, x=45, y=y_ttd + 2, w=25)

        pdf.ln(25) 
        pdf.set_font("helvetica", "BU", 11)
        pdf.cell(95, 6, "Cicipin Bogor", 0, 0, "C")
        pdf.cell(95, 6, f"{resto}", 0, 1, "C")
        
        pdf.output(pdf_name)
        with open(pdf_name, 'rb') as f: bot.send_document(message.chat.id, f, caption=f"✅ SPK Dibuat untuk {resto}", parse_mode='Markdown')
        os.remove(pdf_name)
    except Exception as e: bot.reply_to(message, f"Kesalahan SPK: {e}")


# ==========================================
# 9. HANDLERS DATA & JADWAL
# ==========================================
@bot.message_handler(commands=['jadwalvisit'])
def list_visit(message, is_edit=False, page=0):
    if not check_lisensi_gate(message): return
    try:
        visits = visit_ws.get_all_records()
        valid_visits = []
        for v in visits:
            tgl_str = str(v.get('Tanggal', '')).strip().replace('-', '/')
            resto = str(v.get('Resto', '')).strip()
            if tgl_str and resto.lower() != 'dummy':
                valid_visits.append({'Tanggal': tgl_str, 'Jam': str(v.get('Jam', '')), 'Resto': resto})
                
        valid_visits = sorted(valid_visits, key=lambda x: (safe_date_parse(x.get('Tanggal', '')), str(x.get('Jam', ''))))
        
        total_items = len(valid_visits)
        if total_items == 0:
            reply, markup = "Belum ada jadwal visit yang terdaftar.", get_back_markup()
        else:
            paginated = valid_visits[page*10 : (page+1)*10]
            reply, current_date = f"📌 *List Jadwal Visit (Halaman {page+1}):*\n\n", ""
            for v in paginated:
                dt = safe_date_parse(v.get('Tanggal', ''))
                header = f"{HARI_INDO[dt.weekday()]} {dt.day} {BULAN_INDO[dt.month - 1]}" if dt != datetime.min else v.get('Tanggal')
                if header != current_date:
                    reply += f"{chr(10) if current_date else ''}*{header}*\n"
                    current_date = header
                reply += f"• {v['Resto']} {v['Jam']}\n"
            markup = get_pagination_markup(page, total_items, 'visit_page')
            
        if is_edit: bot.edit_message_text(chat_id=message.chat.id, message_id=message.message_id, text=reply, parse_mode='Markdown', reply_markup=markup) 
        else: bot.send_message(message.chat.id, reply, parse_mode='Markdown', reply_markup=markup)
    except Exception as e: bot.send_message(message.chat.id, f"Kesalahan: {e}")

@bot.message_handler(commands=['jadwalposting'])
def list_posting(message, is_edit=False, page=0):
    if not check_lisensi_gate(message): return
    try:
        posts = post_ws.get_all_records()
        valid_posts = []
        for p in posts:
            tgl_str = str(p.get('TanggalPosting', '')).strip().replace('-', '/')
            resto = str(p.get('Resto', '')).strip()
            if tgl_str and resto.lower() != 'dummy':
                valid_posts.append({'TanggalPosting': tgl_str, 'Resto': resto})
                
        valid_posts = sorted(valid_posts, key=lambda x: safe_date_parse(x.get('TanggalPosting', '')))
        
        total_items = len(valid_posts)
        if total_items == 0:
            reply, markup = "Belum ada antrean posting.", get_back_markup()
        else:
            paginated = valid_posts[page*10 : (page+1)*10]
            reply = f"🚀 *List Antrean Posting (Halaman {page+1}):*\n\n"
            for p in paginated:
                dt = safe_date_parse(p.get('TanggalPosting', ''))
                reply += f"• {HARI_INDO[dt.weekday()]} {dt.day}, {p['TanggalPosting']} - Konten: {p['Resto']}\n" if dt != datetime.min else f"• {p['TanggalPosting']} - {p['Resto']}\n"
            markup = get_pagination_markup(page, total_items, 'post_page')
        
        if is_edit: bot.edit_message_text(chat_id=message.chat.id, message_id=message.message_id, text=reply, parse_mode='Markdown', reply_markup=markup) 
        else: bot.send_message(message.chat.id, reply, parse_mode='Markdown', reply_markup=markup)
    except Exception as e: bot.reply_to(message, f"Kesalahan: {e}")

@bot.message_handler(commands=['tambahvisit'])
def add_visit(message):
    if not check_lisensi_gate(message): return
    try:
        parts = message.text.split(maxsplit=3)
        if len(parts) < 4: return bot.reply_to(message, "⚠️ Format: /tambahvisit DD/MM/YYYY HH:MM Nama Resto")
        date_str, time_str, resto_name = parts[1].replace('-', '/'), parts[2], parts[3]
        visit_date = datetime.strptime(date_str, "%d/%m/%Y")
        
        daily = [v for v in visit_ws.get_all_records() if str(v.get('Tanggal', '')).strip().replace('-', '/') == date_str]
        if len(daily) >= 3: return bot.reply_to(message, "❌ Kuota visit penuh.")
        if any(str(v.get('Jam', '')).strip() == time_str for v in daily): return bot.reply_to(message, "❌ Jam bentrok!")

        visit_ws.append_row([date_str, time_str, resto_name])
        cal_status = push_to_google_calendar(resto_name, date_str, time_str)
        cal_msg = "\n🗓️ Sinkron ke Calendar HP!" if cal_status else ""

        post_dates = []
        for p in post_ws.get_all_records():
            tgl_p = str(p.get('TanggalPosting', '')).strip().replace('-', '/')
            if tgl_p and p.get('Resto', '').lower() != 'dummy':
                try: post_dates.append(datetime.strptime(tgl_p, "%d/%m/%Y"))
                except: pass
                
        post_date = max(max(post_dates) + timedelta(days=1), visit_date + timedelta(days=1)) if post_dates else visit_date + timedelta(days=1)
        post_ws.append_row([post_date.strftime("%d/%m/%Y"), resto_name])

        bot.send_message(message.chat.id, f"✅ *Berhasil!*\n🎥 Visit: {resto_name} ({date_str} {time_str})\n🚀 Posting: {post_date.strftime('%d/%m/%Y')}{cal_msg}", parse_mode="Markdown")
    except Exception as e: bot.send_message(message.chat.id, f"Error: {e}")

@bot.message_handler(commands=['tambahposting'])
def add_posting(message):
    if not check_lisensi_gate(message): return
    try:
        parts = message.text.split(maxsplit=2)
        if len(parts) < 3: return
        date_str, resto_name = parts[1].replace('-', '/'), parts[2]
        post_ws.append_row([date_str, resto_name])
        bot.send_message(message.chat.id, f"✅ Jadwal posting ditambahkan.")
    except Exception as e: bot.reply_to(message, str(e))

@bot.message_handler(commands=['batalvisit'])
def cancel_visit(message):
    if not check_lisensi_gate(message): return
    try:
        parts = message.text.split(maxsplit=2)
        if len(parts) < 3: return
        date_str, time_str = parts[1].replace('-', '/'), parts[2]
        for idx, v in enumerate(visit_ws.get_all_records(), start=2):
            if str(v.get('Tanggal', '')).strip().replace('-', '/') == date_str and str(v.get('Jam', '')).strip() == time_str:
                visit_ws.delete_rows(idx)
                return bot.reply_to(message, "🗑 Jadwal visit dibatalkan.")
    except Exception as e: bot.reply_to(message, str(e))

@bot.message_handler(commands=['batalposting'])
def cancel_posting(message):
    if not check_lisensi_gate(message): return
    try:
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2: return
        post_date = parts[1].replace('-', '/')
        for idx, p in enumerate(post_ws.get_all_records(), start=2):
            if str(p.get('TanggalPosting', '')).strip().replace('-', '/') == post_date:
                post_ws.delete_rows(idx)
                return bot.reply_to(message, "🗑 Jadwal posting dibatalkan.")
    except Exception as e: bot.reply_to(message, str(e))

@bot.message_handler(commands=['rekapbulan'])
def rekap_bulan(message, is_edit=False):
    if not check_lisensi_gate(message): return
    try:
        target_date = datetime.now()
        target_month_str = target_date.strftime("%m/%Y")
        total_masuk, total_keluar = 0, 0
        
        for row in keuangan_ws.get_all_records():
            tgl = str(row.get('Tanggal', '')).strip().replace('-', '/')
            if not tgl: continue
            try:
                dt = datetime.strptime(tgl, "%d/%m/%Y")
                if dt.month == target_date.month and dt.year == target_date.year:
                    jns, nom = str(row.get('Jenis', '')).lower(), int(row.get('Nominal', 0))
                    if jns == 'pemasukan': total_masuk += nom
                    elif jns == 'pengeluaran': total_keluar += nom
            except: pass
                
        reply = f"📊 *REKAP BULAN {target_month_str}*\n\n🟢 Masuk: Rp{total_masuk:,}\n🔴 Keluar: Rp{total_keluar:,}\n⭐ Profit: Rp{total_masuk - total_keluar:,}\n"
        if is_edit: bot.edit_message_text(chat_id=message.chat.id, message_id=message.message_id, text=reply, parse_mode='Markdown', reply_markup=get_back_markup())
        else: bot.send_message(message.chat.id, reply, parse_mode='Markdown', reply_markup=get_back_markup())
    except Exception as e: bot.send_message(message.chat.id, f"Error: {e}")

@bot.message_handler(commands=['ratecard', 'rc', 'ratecardumkm', 'rcumkm', 'sk'])
def send_docs(message):
    if not check_lisensi_gate(message): return
    cmd = message.text.replace('/', '').lower()
    key_map = {'ratecard': 'ratecard', 'rc': 'ratecard', 'ratecardumkm': 'ratecardumkm', 'rcumkm': 'ratecardumkm', 'sk': 'sk'}
    try:
        val = next((str(r['Value']) for r in settings_ws.get_all_records() if str(r.get('Key', '')).strip().lower() == key_map[cmd]), "-")
        bot.send_message(message.chat.id, val, parse_mode='Markdown')
    except: pass

@bot.message_handler(commands=['editrc', 'editratecard', 'editrcumkm', 'editratecardumkm', 'editsk'])
def edit_docs(message):
    if not check_lisensi_gate(message): return
    try:
        cmd = message.text.split()[0].replace('/edit', '').replace('ratecard', 'rc')
        parts = message.text.split(maxsplit=1)
        key_map = {'rc': 'ratecard', 'rcumkm': 'ratecardumkm', 'sk': 'sk'}
        
        if len(parts) < 2:
            val = next((str(r['Value']) for r in settings_ws.get_all_records() if str(r.get('Key', '')).strip().lower() == key_map[cmd]), "-")
            return bot.reply_to(message, f"📋 *Template saat ini:*\n\n`{val}`\n\nKirim ulang dengan format `/edit{cmd} [Teks Baru]`", parse_mode='Markdown')
            
        update_pengaturan(key_map[cmd], parts[1].strip())
        bot.reply_to(message, "✅ Teks berhasil diperbarui!")
    except Exception as e: bot.reply_to(message, f"Error: {e}")

bot.infinity_polling()
