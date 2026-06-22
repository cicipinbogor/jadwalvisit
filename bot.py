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

# Ambil kredensial dari Environment Variables Railway
BOT_TOKEN = os.environ.get('BOT_TOKEN')
SHEET_ID = os.environ.get('SHEET_ID')
CREDS_JSON = os.environ.get('GOOGLE_CREDENTIALS')
MY_CHAT_IDS_STR = os.environ.get('MY_CHAT_ID', '') 
CALENDAR_ID = os.environ.get('CALENDAR_ID', 'primary') # Email pribadi kamu yang sudah dishare aksesnya

# Ekstrak daftar Chat ID menjadi list
CHAT_ID_LIST = [cid.strip() for cid in MY_CHAT_IDS_STR.split(',') if cid.strip()]

bot = telebot.TeleBot(BOT_TOKEN)

# Setup koneksi ke Google Workspace (Sheets & Calendar)
creds_dict = json.loads(CREDS_JSON)
scopes = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/calendar"
]
creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)

# Inisialisasi API Google Sheets & Calendar
client = gspread.authorize(creds)
sheet = client.open_by_key(SHEET_ID)
visit_ws = sheet.worksheet('Visit')
post_ws = sheet.worksheet('Posting')
calendar_service = build('calendar', 'v3', credentials=creds)

# Cek dan buat otomatis sheet 'Keuangan' jika belum ada
try:
    keuangan_ws = sheet.worksheet('Keuangan')
except gspread.exceptions.WorksheetNotFound:
    keuangan_ws = sheet.add_worksheet(title="Keuangan", rows="1000", cols="4")
    keuangan_ws.append_row(["Tanggal", "Jenis", "Nominal", "Keterangan"])

# --- SISTEM LISENSI BOT (SaaS) ---
LICENSE_CACHE = {
    'exp_date': datetime.min,
    'status': 'LOCKED',
    'key': '',
    'last_checked': None
}

def generate_key():
    return "CCPN-" + ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))

def sync_lisensi_from_sheet():
    try:
        ws = sheet.worksheet('Lisensi')
    except gspread.exceptions.WorksheetNotFound:
        ws = sheet.add_worksheet(title="Lisensi", rows="10", cols="2")
        ws.append_row(["Key", "Value"])
        now = datetime.now()
        trial_exp = now + timedelta(days=1) # Mengatur masa trial bawaan (1 hari)
        new_key = generate_key()
        ws.append_row(["Status", "TRIAL"])
        ws.append_row(["ExpiredDate", trial_exp.strftime("%d/%m/%Y %H:%M:%S")])
        ws.append_row(["AccessKey", new_key])
        
        LICENSE_CACHE['status'] = "TRIAL"
        LICENSE_CACHE['exp_date'] = trial_exp
        LICENSE_CACHE['key'] = new_key
        LICENSE_CACHE['last_checked'] = datetime.now()
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
            "Masa penggunaan bot (Trial/Bulanan) kamu telah habis.\n"
            "Silakan cek *Google Sheets* tab *'Lisensi'* untuk melihat Kode Akses terbaru yang sudah di-generate otomatis oleh sistem.\n\n"
            "🔑 Ketik perintah ini untuk mengaktifkan bot 30 hari ke depan:\n"
            "`/lisensi [Kode_Akses]`\n"
            "_Contoh: /lisensi CCPN-X1Y2Z3_"
        )
        if is_call:
            bot.answer_callback_query(message_or_call.id, "⚠️ Bot Terkunci! Cek pesan baru.", show_alert=True)
            bot.send_message(msg.chat.id, warning_text, parse_mode="Markdown")
        else:
            bot.reply_to(msg, warning_text, parse_mode="Markdown")
        return False
    return True

# --- INTEGRASI GOOGLE CALENDAR ENGINE ---
def push_to_google_calendar(resto_name, date_str, time_str):
    try:
        # Parsing tanggal dan jam masuk ke objek datetime
        start_dt = datetime.strptime(f"{date_str} {time_str}", "%d/%m/%Y %H:%M")
        # Set durasi visit otomatis 2 jam (Sesuai MoU / Waktu Liputan)
        end_dt = start_dt + timedelta(hours=2)
        
        event_body = {
            'summary': f"🎥 Visit Liputan: {resto_name}",
            'location': 'Bogor, West Java, Indonesia',
            'description': f"Jadwal liputan Food Vlogger untuk {resto_name}. Diinput otomatis melalui Bot J.A.R.V.I.S.",
            'start': {
                'dateTime': start_dt.strftime("%Y-%m-%dT%H:%M:%S"),
                'timeZone': 'Asia/Jakarta',
            },
            'end': {
                'dateTime': end_dt.strftime("%Y-%m-%dT%H:%M:%S"),
                'timeZone': 'Asia/Jakarta',
            },
            'reminders': {
                'useDefault': False,
                'overrides': [
                    {'method': 'popup', 'minutes': 120},  # Notif 2 jam sebelum syuting
                    {'method': 'popup', 'minutes': 1440}, # Notif H-1 agar siap-siap gear kamera
                ],
            },
        }
        
        calendar_service.events().insert(calendarId=CALENDAR_ID, body=event_body).execute()
        return True
    except Exception as e:
        print(f"Error push Google Calendar: {str(e)}")
        return False


# --- TEKS DEFAULT UNTUK PENGATURAN ---
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
• ✨ *FREE Collab on Instagram*
• Keep video permanent
• Prioritas jadwal upload
• Harga: Rp 800.000

➕ *ADDITIONAL MENU*
• *Owning Content (Hak Milik Video):*
  - Kualitas 2K: +Rp 200.000
  - Kualitas 4K: +Rp 300.000
• *Additional Story (Instagram):*
  - 1x Story: +Rp 30.000
  - 2x Story: +Rp 50.000

📌 *Catatan:*
• Harga berlaku untuk wilayah Bogor & sekitarnya.
• Untuk Syarat & Ketentuan lengkap silakan ketik /sk

Silakan balas pesan ini jika ada paket yang sesuai atau ingin berdiskusi lebih lanjut! 🙏"""

DEFAULT_RATECARDUMKM = """🤝 *RATE CARD KHUSUS UMKM*

Halo! Sebagai bentuk *support* untuk usaha rintisan dan UMKM kuliner lokal, Cicipin Bogor menyediakan paket penawaran khusus yang lebih terjangkau:

🌱 *PAKET SUPPORT UMKM*
• 1x Visit & Liputan Outlet
• 1x Video tayang di IG Reels (termasuk mirroring ke TikTok)
• Keep video permanent
• Harga Khusus: *Rp 400.000*

📌 *Catatan:*
• Harga khusus ini berlaku untuk bisnis skala kecil/menengah di wilayah Bogor & sekitarnya.
• Jadwal upload akan disesuaikan dengan antrean slot reguler.
• Untuk Syarat & Ketentuan lengkap silakan ketik /sk

Mari maju bersama memajukan kuliner lokal! Silakan balas pesan ini untuk menentukan jadwal visit. 🙏"""

DEFAULT_SK = """📝 *SYARAT & KETENTUAN (S&K) KERJA SAMA*

Untuk menjaga kenyamanan dan profesionalisme proses produksi konten, berikut adalah S&K yang berlaku:

1️⃣ *Proses Liputan & Konsumsi*
• Pihak resto menyediakan menu andalan yang akan di-review secara gratis.
• Proses syuting memakan waktu sekitar 1-2 jam.

2️⃣ *Sistem Pembayaran (Payment)*
• Down Payment (DP) sebesar 50% wajib dibayarkan maksimal H-3 sebelum jadwal visit untuk mengunci slot.
• Pelunasan sisa 50% dilakukan maksimal H-1 sebelum video resmi ditayangkan (upload).

3️⃣ *Reschedule & Pembatalan*
• Perubahan jadwal visit wajib diinfokan paling lambat H-2 sebelum hari liputan.
• Jika pihak klien membatalkan kerja sama sepihak, maka DP dianggap hangus.

4️⃣ *Kebijakan Revisi Video*
• Klien berhak mendapatkan revisi video maksimal 1x (revisi minor seperti salah info harga, teks, atau penulisan nama).

5️⃣ *Hak Cipta & Penggunaan Video*
• Hak cipta video sepenuhnya milik creator. Konten akan ditayangkan secara permanen di akun creator.
• Klien dilarang mengunggah ulang (re-upload) video utuh tanpa membeli opsi *Owning Content*."""

try:
    settings_ws = sheet.worksheet('Pengaturan')
except gspread.exceptions.WorksheetNotFound:
    settings_ws = sheet.add_worksheet(title="Pengaturan", rows="10", cols="2")
    settings_ws.append_row(["Key", "Value"])
    settings_ws.append_row(["ratecard", DEFAULT_RATECARD])
    settings_ws.append_row(["ratecardumkm", DEFAULT_RATECARDUMKM])
    settings_ws.append_row(["sk", DEFAULT_SK])

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

# --- PENGATURAN KEYBOARD ---
def get_main_menu_markup():
    markup = telebot.types.InlineKeyboardMarkup(row_width=2)
    btn1 = telebot.types.InlineKeyboardButton('📅 Jadwal Visit', callback_data='menu_visit')
    btn2 = telebot.types.InlineKeyboardButton('🚀 Jadwal Posting', callback_data='menu_posting')
    btn3 = telebot.types.InlineKeyboardButton('💰 Rekap Keuangan', callback_data='menu_rekap')
    btn4 = telebot.types.InlineKeyboardButton('📑 Administrasi', callback_data='menu_admin')
    btn5 = telebot.types.InlineKeyboardButton('🎙️ Bantuan Suara', callback_data='menu_helpvoice')
    btn6 = telebot.types.InlineKeyboardButton('⚙️ Rate Card & S&K', callback_data='menu_settings')
    markup.add(btn1, btn2, btn3, btn4, btn5, btn6)
    return markup

def get_back_markup():
    markup = telebot.types.InlineKeyboardMarkup()
    markup.add(telebot.types.InlineKeyboardButton('🔙 Kembali ke Menu', callback_data='menu_main'))
    return markup

def get_pagination_markup(current_page, total_items, prefix):
    markup = telebot.types.InlineKeyboardMarkup(row_width=3)
    buttons = []
    total_pages = math.ceil(total_items / 10)
    
    if current_page > 0:
        buttons.append(telebot.types.InlineKeyboardButton('⬅️ Prev', callback_data=f'{prefix}_{current_page - 1}'))
    
    buttons.append(telebot.types.InlineKeyboardButton(f'{current_page + 1} / {total_pages}', callback_data='ignore'))
    
    if current_page < total_pages - 1:
        buttons.append(telebot.types.InlineKeyboardButton('Next ➡️', callback_data=f'{prefix}_{current_page + 1}'))
        
    if buttons:
        markup.row(*buttons)
        
    markup.add(telebot.types.InlineKeyboardButton('🔙 Kembali ke Menu', callback_data='menu_main'))
    return markup


# --- COMMAND START & LISENSI HANDLING ---
@bot.message_handler(commands=['start', 'menu'])
def send_welcome(message):
    if not check_lisensi_gate(message): return
    
    teks = (
        "🤖 *Bot J.A.R.V.I.S Cicipin Bogor Aktif!*\n\n"
        "Halo bos! Mau ngurusin apa kita hari ini?\n\n"
        "Silakan tap menu di bawah pesan ini, atau kalau lagi repot di jalan, langsung aja kirim *Voice Note* untuk kasih perintah (jadwalin visit, rekap uang, bikin SPK, dll) 🎙️🔥"
    )
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
        new_exp = datetime.now() + timedelta(days=30) # Masa aktif langganan bulanan SaaS
        new_key = generate_key()
        
        ws = sheet.worksheet('Lisensi')
        try:
            c1 = ws.find("Status")
            ws.update_cell(c1.row, 2, "ACTIVE")
            c2 = ws.find("ExpiredDate")
            ws.update_cell(c2.row, 2, new_exp.strftime("%d/%m/%Y %H:%M:%S"))
            c3 = ws.find("AccessKey")
            ws.update_cell(c3.row, 2, new_key)
        except gspread.exceptions.CellNotFound:
            ws.clear()
            ws.append_row(["Key", "Value"])
            ws.append_row(["Status", "ACTIVE"])
            ws.append_row(["ExpiredDate", new_exp.strftime("%d/%m/%Y %H:%M:%S")])
            ws.append_row(["AccessKey", new_key])
        
        LICENSE_CACHE['status'] = "ACTIVE"
        LICENSE_CACHE['exp_date'] = new_exp
        LICENSE_CACHE['key'] = new_key
        LICENSE_CACHE['last_checked'] = datetime.now()
        
        bot.reply_to(message, "✅ *Lisensi Berhasil Diaktifkan!*\n\nBot telah terbuka dan aktif selama 30 hari ke depan. Kunci akses baru untuk bulan depan sudah digenerate otomatis.", parse_mode="Markdown")
        send_welcome(message)
    else:
        bot.reply_to(message, "❌ *Kunci Akses Salah atau Kadaluarsa!* Silakan cek kunci terbaru di tab 'Lisensi' Google Sheets.", parse_mode="Markdown")


# --- HANDLER KLIK TOMBOL INLINE ---
@bot.callback_query_handler(func=lambda call: call.data.startswith('menu_') or call.data.startswith('visit_page_') or call.data.startswith('post_page_') or call.data == 'ignore')
def handle_inline_menu(call):
    bot.answer_callback_query(call.id)
    if call.data == 'ignore': return
    if not check_lisensi_gate(call): return

    if call.data == 'menu_main':
        teks = (
            "🤖 *Bot J.A.R.V.I.S Cicipin Bogor Aktif!*\n\n"
            "Halo bos! Mau ngurusin apa kita hari ini?\n\n"
            "Silakan tap menu di bawah pesan ini, atau kalau lagi repot di jalan, langsung aja kirim *Voice Note* untuk kasih perintah (jadwalin visit, rekap uang, bikin SPK, dll) 🎙️🔥"
        )
        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=teks, reply_markup=get_main_menu_markup(), parse_mode='Markdown')
    elif call.data == 'menu_visit':
        list_visit(call.message, is_edit=True, page=0)
    elif call.data.startswith('visit_page_'):
        page = int(call.data.split('_')[-1])
        list_visit(call.message, is_edit=True, page=page)
    elif call.data == 'menu_posting':
        list_posting(call.message, is_edit=True, page=0)
    elif call.data.startswith('post_page_'):
        page = int(call.data.split('_')[-1])
        list_posting(call.message, is_edit=True, page=page)
    elif call.data == 'menu_rekap':
        rekap_bulan(call.message, is_edit=True)
    elif call.data == 'menu_helpvoice':
        send_help_voice(call.message, is_edit=True)
    elif call.data == 'menu_admin':
        teks = (
            "💼 *MENU ADMINISTRASI KLIEN*\n\n"
            "Untuk fitur ini, kamu bisa pakai *Suara* (cek di 🎙️ Bantuan Suara) atau ketik manual dengan format:\n\n"
            "📝 *Surat Perjanjian (SPK):*\n`/spk Nama Resto - Nama Paket`\n\n"
            "📄 *Invoice DP (50%):*\n`/invoice Nama Resto - Item=Harga`\n\n"
            "📄 *Invoice Lunas (Full):*\n`/invoicefull Nama Resto - Item=Harga`\n\n"
            "🧾 *Kwitansi Lunas:*\n`/kwitansi Nama Resto - Nominal - Keterangan`"
        )
        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=teks, reply_markup=get_back_markup(), parse_mode='Markdown')
    elif call.data == 'menu_settings':
        teks = (
            "⚙️ *PENGATURAN RATE CARD & S&K*\n\n"
            "Pilih dokumen yang mau kamu lihat (klik link biru):\n"
            "1. /ratecard (Untuk ubah: /editrc)\n"
            "2. /ratecardumkm (Untuk ubah: /editrcumkm)\n"
            "3. /sk (Untuk ubah: /editsk)"
        )
        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=teks, reply_markup=get_back_markup(), parse_mode='Markdown')

@bot.message_handler(commands=['help', 'helpvoice'])
def send_help_voice(message, is_edit=False):
    if not check_lisensi_gate(message): return
    teks = (
        "🎙️ *PANDUAN PERINTAH SUARA (VOICE COMMAND)*\n\n"
        "📅 *1. PENJADWALAN*\n"
        "• *Tambah Visit:* _\"Bot, tambah visit besok jam 2 siang di resto Brano Pizzeria\"_\n"
        "• *Centang Visit:* _\"Bot, tolong centang visit resto Brano Pizzeria\"_\n"
        "• *Batal Visit:* _\"Bot, batal visit besok jam 2 siang\"_\n"
        "• *Tambah Posting:* _\"Bot, tambah posting lusa untuk konten Bakso Mercon\"_\n"
        "• *Batal Posting:* _\"Bot, hapus jadwal posting tanggal 25 Juni\"_\n"
        "• *Cek Jadwal:* _\"Bot, lihat jadwal visit hari ini\"_\n\n"
        "📑 *2. ADMINISTRASI*\n"
        "• *Buat SPK:* _\"Bot, bikin SPK resto Kopi Daun paket Support UMKM\"_\n"
        "• *Buat Invoice DP:* _\"Bot, bikin invoice resto Ayam Bakar Pak Ndut paket Reguler harga 500 ribu\"_\n"
        "• *Buat Invoice Lunas:* _\"Bot, buat invoice resto Brano Pizzeria paket Gacor nominal 800 ribu lunas\"_\n"
        "• *Buat Kwitansi:* _\"Bot, bikin kwitansi resto Sate Maranggi nominal 400 ribu\"_\n"
        "• *Tampilkan Menu:* _\"Bot, kirim rate card\"_\n\n"
        "💰 *3. KEUANGAN*\n"
        "• *Pemasukan / Pengeluaran:* Catat transaksi keuangan langsung sebut nominal & jenisnya.\n\n"
        "💡 *Tips:* Jangan gabungkan 2 perintah dalam 1 Voice Note. Sebutkan angka dengan bensin/nominal secara natural."
    )
    if is_edit:
        bot.edit_message_text(chat_id=message.chat.id, message_id=message.message_id, text=teks, parse_mode='Markdown', reply_markup=get_back_markup())
    else:
        bot.reply_to(message, teks, parse_mode='Markdown', reply_markup=get_back_markup())

# --- VOICE COMMAND ROUTER (OTAK UTAMA) ---
@bot.message_handler(content_types=['voice'])
def handle_voice_global(message):
    if not check_lisensi_gate(message): return
    try:
        msg = bot.reply_to(message, "⏳ _Sedang mencerna pesan suara kamu..._", parse_mode="Markdown")
        
        file_info = bot.get_file(message.voice.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        
        ogg_path = f"voice_{message.message_id}.ogg"
        wav_path = f"voice_{message.message_id}.wav"
        
        with open(ogg_path, 'wb') as new_file:
            new_file.write(downloaded_file)
            
        audio = AudioSegment.from_file(ogg_path, format="ogg")
        audio.export(wav_path, format="wav")
        
        r = sr.Recognizer()
        with sr.AudioFile(wav_path) as source:
            audio_data = r.record(source)
            teks_hasil = r.recognize_google(audio_data, language="id-ID")
        
        os.remove(ogg_path)
        os.remove(wav_path)
        
        teks_lower = teks_hasil.lower()
        bot.edit_message_text(f"🗣️ *Terdengar:* _{teks_hasil}_\n🚀 _Memproses perintah..._", chat_id=message.chat.id, message_id=msg.message_id, parse_mode="Markdown")

        if any(kata in teks_lower for kata in ["help voice", "bantuan suara", "tutorial perintah suara", "cara perintah suara"]):
            message.text = "/helpvoice"
            return send_help_voice(message)
        elif any(kata in teks_lower for kata in ["lihat", "cek", "rekap"]):
            if "visit" in teks_lower or "kunjungan" in teks_lower:
                message.text = "/jadwalvisit"
                return list_visit(message)
            elif "posting" in teks_lower or "konten" in teks_lower:
                message.text = "/jadwalposting"
                return list_posting(message)
            elif "bulan" in teks_lower or "keuangan" in teks_lower or "rekap" in teks_lower:
                message.text = "/rekapbulan"
                return rekap_bulan(message)
        elif any(kata in teks_lower for kata in ["centang", "selesai", "tandai"]) and ("visit" in teks_lower or "kunjungan" in teks_lower):
            match_resto = re.search(r'(?:resto|di|ke|namanya)\s+([a-zA-Z0-9\s]+)', teks_lower)
            resto = match_resto.group(1).strip() if match_resto else ""
            if not resto:
                resto = teks_lower.replace("bot", "").replace("centang", "").replace("selesai", "").replace("tandai", "").replace("visit", "").replace("kunjungan", "").replace("resto", "").replace("sudah", "").replace("di", "").strip()
            message.text = f"/centangvisit {resto}"
            return mark_done_visit(message)
        elif any(kata in teks_lower for kata in ["batal", "hapus", "cancel"]) and ("visit" in teks_lower or "kunjungan" in teks_lower):
            date_str, time_str = parse_tanggal_jam(teks_lower)
            if not date_str or not time_str:
                bot.send_message(message.chat.id, "⚠️ Sebutkan tanggal dan jam visit yang mau dibatalkan.")
                return
            message.text = f"/batalvisit {date_str} {time_str}"
            return cancel_visit(message)
        elif any(kata in teks_lower for kata in ["batal", "hapus", "cancel"]) and ("posting" in teks_lower or "konten" in teks_lower):
            date_str, _ = parse_tanggal_jam(teks_lower)
            if not date_str:
                bot.send_message(message.chat.id, "⚠️ Sebutkan tanggal posting yang mau dibatalkan.")
                return
            message.text = f"/batalposting {date_str}"
            return cancel_posting(message)
        elif any(kata in teks_lower for kata in ["visit", "kunjungan", "masukin jadwal", "tambah jadwal"]):
            date_str, time_str = parse_tanggal_jam(teks_lower)
            match_resto = re.search(r'(?:di\s+resto|di|resto|ke|namanya)\s+([a-zA-Z0-9\s]+)', teks_lower)
            resto = match_resto.group(1).strip().title() if match_resto else "Resto Baru"
            if not date_str: date_str = datetime.now().strftime("%d/%m/%Y")
            if not time_str: time_str = "12:00"
            message.text = f"/tambahvisit {date_str} {time_str} {resto}"
            return add_visit(message)
        elif any(kata in teks_lower for kata in ["posting", "konten"]):
            date_str, _ = parse_tanggal_jam(teks_lower)
            match_resto = re.search(r'(?:konten|resto|untuk|tentang)\s+([a-zA-Z0-9\s]+)', teks_lower)
            resto = match_resto.group(1).strip().title() if match_resto else "Konten Baru"
            if not date_str: date_str = datetime.now().strftime("%d/%m/%Y")
            message.text = f"/tambahposting {date_str} {resto}"
            return add_posting(message)
        elif any(kata in teks_lower for kata in ["rate card umkm", "ratecard umkm", "paket umkm", "harga umkm"]):
            message.text = "/ratecardumkm"
            return send_ratecard_umkm(message)
        elif any(kata in teks_lower for kata in ["rate card", "ratecard", "harga paket"]):
            message.text = "/ratecard"
            return send_ratecard(message)
        elif any(kata in teks_lower for kata in ["syarat dan ketentuan", "aturan main"]):
            message.text = "/sk"
            return send_sk(message)
        elif "invoice" in teks_lower:
            is_full = "full" in teks_lower or "lunas" in teks_lower
            nominal_inv = extract_nominal(teks_lower)
            if nominal_inv:
                resto = "Klien"
                item_name = "Paket Konten"
                match_all = re.search(r'resto\s+(.+?)\s+(?:paket|item)\s+(.+?)\s+(?:harga|nominal)', teks_lower)
                if match_all:
                    resto = match_all.group(1).strip().title()
                    item_name = match_all.group(2).strip().title()
                else:
                    match_resto = re.search(r'resto\s+(.+?)\s+(?:harga|nominal)', teks_lower)
                    if match_resto: resto = match_resto.group(1).strip().title()
                if is_full:
                    message.text = f"/invoicefull {resto} - {item_name}={nominal_inv}"
                    return generate_invoice_full(message)
                else:
                    message.text = f"/invoice {resto} - {item_name}={nominal_inv}"
                    return generate_invoice(message)
            else:
                bot.send_message(message.chat.id, "⚠️ Format invoice suara kurang jelas.")
                return
        elif "kwitansi" in teks_lower:
            match_kwt = re.search(r'(?:kwitansi|resto)\s+(.+?)\s+(?:sebesar|nominal)\s+(.+?)\s+(?:untuk|buat)\s+(.+)', teks_lower)
            if match_kwt:
                resto = match_kwt.group(1).title()
                nominal_kwt = extract_nominal(match_kwt.group(2))
                ket = match_kwt.group(3).capitalize()
                if nominal_kwt:
                    message.text = f"/kwitansi {resto} - {nominal_kwt} - {ket}"
                    return generate_kwitansi(message)
            bot.send_message(message.chat.id, "⚠️ Format kwitansi suara salah.")
            return
        elif "spk" in teks_lower:
            match_spk = re.search(r'(?:spk|resto)\s+(.+?)\s+(?:dengan\s+)?(?:paket)\s+(.+)', teks_lower)
            if match_spk:
                resto = match_spk.group(1).title()
                paket = "Paket " + match_spk.group(2).title()
                message.text = f"/spk {resto} - {paket}"
                return generate_spk(message)
            bot.send_message(message.chat.id, "⚠️ Format SPK suara salah.")
            return
        else:
            nominal = extract_nominal(teks_lower)
            if not nominal:
                bot.send_message(message.chat.id, "⚠️ Maaf, instruksi suara tidak dikenali. Ketik /helpvoice.")
                return
            tgl_sekarang = datetime.now().strftime("%d/%m/%Y")
            if any(kata in teks_lower for kata in ["pemasukan", "terima uang", "terima dp", "pelunasan", "bayaran", "cair"]):
                keuangan_ws.append_row([tgl_sekarang, "Pemasukan", nominal, teks_hasil.capitalize()])
                bot.send_message(message.chat.id, f"✅ *Pemasukan Dicatat via Suara!*")
            elif any(kata in teks_lower for kata in ["keluar", "pengeluaran", "beli", "bayar", "bensin", "parkir"]):
                keuangan_ws.append_row([tgl_sekarang, "Pengeluaran", nominal, teks_hasil.capitalize()])
                bot.send_message(message.chat.id, f"📉 *Pengeluaran Dicatat via Suara!*")
            else:
                bot.send_message(message.chat.id, "⚠️ Bingung ini uang masuk atau keluar.")
    except Exception as e:
        bot.reply_to(message, f"⚠️ Terjadi kesalahan sistem: {str(e)}")

# --- FUNGSI PROSES DATA & INPUT SHEET ---
@bot.message_handler(commands=['tambahvisit'])
def add_visit(message):
    if not check_lisensi_gate(message): return
    try:
        parts = message.text.split(maxsplit=3)
        if len(parts) < 4: return

        date_str = parts[1].replace('-', '/')
        time_str = parts[2]
        resto_name = parts[3]

        visit_date = datetime.strptime(date_str, "%d/%m/%Y")
        datetime.strptime(time_str, "%H:%M")

        visits = visit_ws.get_all_records()
        daily_visits = [v for v in visits if str(v.get('Tanggal', '')).strip() == date_str]

        if len(daily_visits) >= 3:
            bot.reply_to(message, f"❌ Kuota visit tanggal {date_str} sudah penuh.")
            return

        if any(str(v.get('Jam', '')).strip() == time_str for v in daily_visits):
            bot.reply_to(message, f"❌ Jadwal jam {time_str} sudah terisi.")
            return

        # Simpan ke Google Sheet
        visit_ws.append_row([date_str, time_str, resto_name])

        # PUSH OTOMATIS KE GOOGLE CALENDAR
        cal_status = push_to_google_calendar(resto_name, date_str, time_str)
        cal_msg = "🗓️ Otomatis tersinkronisasi ke Google Calendar HP kamu!" if cal_status else "⚠️ Gagal push ke Google Calendar (Cek setelan sharing kamu)."

        posts = post_ws.get_all_records()
        post_dates = [datetime.strptime(p['TanggalPosting'], "%d/%m/%Y") for p in posts if str(p.get('TanggalPosting', '')).strip() and p['Resto'].lower() != 'dummy']

        if post_dates:
            post_date = max(max(post_dates) + timedelta(days=1), visit_date + timedelta(days=1))
        else:
            post_date = visit_date + timedelta(days=1)

        post_date_str = post_date.strftime("%d/%m/%Y")
        post_ws.append_row([post_date_str, resto_name])

        bot.send_message(message.chat.id, f"✅ *Berhasil Dijadwalkan!*\n\n🎥 Visit: {resto_name} ({date_str} {time_str})\n🚀 Antrean Posting: {post_date_str}\n\n{cal_msg}", parse_mode="Markdown")
    except Exception as e:
        bot.send_message(message.chat.id, f"Terjadi kesalahan: {str(e)}")

@bot.message_handler(commands=['jadwalvisit'])
def list_visit(message, is_edit=False, page=0):
    if not check_lisensi_gate(message): return
    try:
        visits = visit_ws.get_all_records()
        valid_visits = [v for v in visits if str(v.get('Tanggal', '')).strip() and v['Resto'].lower() != 'dummy']
        valid_visits = sorted(valid_visits, key=lambda x: (safe_date_parse(x.get('Tanggal', '')), str(x.get('Jam', ''))))
        
        total_items = len(valid_visits)
        if total_items == 0:
            reply = "Belum ada jadwal visit yang terdaftar."
            markup = get_back_markup()
        else:
            items_per_page = 10
            paginated_visits = valid_visits[page*items_per_page : (page+1)*items_per_page]
            
            reply = f"📌 *List Jadwal Visit (Halaman {page+1}):*\n\n"
            current_date = ""
            for v in paginated_visits:
                tgl_str = v.get('Tanggal', '').strip()
                dt = safe_date_parse(tgl_str)
                header_tanggal = f"{HARI_INDO[dt.weekday()]} {dt.day} {BULAN_INDO[dt.month - 1]}"
                if header_tanggal != current_date:
                    if current_date != "": reply += "\n"
                    reply += f"*{header_tanggal}*\n"
                    current_date = header_tanggal
                reply += f"• {v['Resto']} {v['Jam']}\n"
            markup = get_pagination_markup(page, total_items, 'visit_page')
            
        if is_edit:
            bot.edit_message_text(chat_id=message.chat.id, message_id=message.message_id, text=reply, parse_mode='Markdown', reply_markup=markup)
        else:
            bot.send_message(message.chat.id, reply, parse_mode='Markdown', reply_markup=markup)
    except Exception as e:
        bot.send_message(message.chat.id, f"Kesalahan: {str(e)}")

@bot.message_handler(commands=['jadwalposting'])
def list_posting(message, is_edit=False, page=0):
    if not check_lisensi_gate(message): return
    try:
        posts = post_ws.get_all_records()
        valid_posts = [p for p in posts if str(p.get('TanggalPosting', '')).strip() and p['Resto'].lower() != 'dummy']
        valid_posts = sorted(valid_posts, key=lambda x: safe_date_parse(x.get('TanggalPosting', '')))
        
        total_items = len(valid_posts)
        if total_items == 0:
            reply = "Belum ada antrean jadwal posting."
            markup = get_back_markup()
        else:
            items_per_page = 10
            paginated_posts = valid_posts[page*items_per_page : (page+1)*items_per_page]
            reply = f"🚀 *List Antrean Posting (Halaman {page+1}):*\n\n"
            for p in paginated_posts:
                dt = safe_date_parse(p.get('TanggalPosting', ''))
                reply += f"• {HARI_INDO[dt.weekday()]}, {p['TanggalPosting']} - Konten: {p['Resto']}\n"
            markup = get_pagination_markup(page, total_items, 'post_page')
        
        if is_edit:
            bot.edit_message_text(chat_id=message.chat.id, message_id=message.message_id, text=reply, parse_mode='Markdown', reply_markup=markup)
        else:
            bot.send_message(message.chat.id, reply, parse_mode='Markdown', reply_markup=markup)
    except Exception as e:
        bot.reply_to(message, f"Kesalahan: {str(e)}")

# --- CRUDS LAIN (SAMA SEPERTI SEBELUMNYA SINKRON KE KATEGORI LISENSI) ---
@bot.message_handler(commands=['tambahposting'])
def add_posting(message):
    if not check_lisensi_gate(message): return
    try:
        parts = message.text.split(maxsplit=2)
        date_str = parts[1].replace('-', '/')
        resto_name = parts[2]
        post_ws.append_row([date_str, resto_name])
        bot.send_message(message.chat.id, f"✅ Jadwal posting ditambahkan.")
    except Exception as e: bot.reply_to(message, str(e))

@bot.message_handler(commands=['batalvisit'])
def cancel_visit(message):
    if not check_lisensi_gate(message): return
    try:
        parts = message.text.split(maxsplit=2)
        date_str, time_str = parts[1].replace('-', '/'), parts[2]
        visits = visit_ws.get_all_records()
        for idx, v in enumerate(visits, start=2):
            if str(v.get('Tanggal', '')).strip() == date_str and str(v.get('Jam', '')).strip() == time_str:
                visit_ws.delete_rows(idx)
                bot.reply_to(message, "🗑 Jadwal visit dibatalkan.")
                return
    except Exception as e: bot.reply_to(message, str(e))

@bot.message_handler(commands=['batalposting'])
def cancel_posting(message):
    if not check_lisensi_gate(message): return
    try:
        parts = message.text.split(maxsplit=1)
        post_date = parts[1].replace('-', '/')
        posts = post_ws.get_all_records()
        for idx, p in enumerate(posts, start=2):
            if str(p.get('TanggalPosting', '')).strip() == post_date:
                post_ws.delete_rows(idx)
                bot.reply_to(message, "🗑 Jadwal posting dibatalkan.")
                return
    except Exception as e: bot.reply_to(message, str(e))

bot.infinity_polling()
