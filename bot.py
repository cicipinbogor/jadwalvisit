import telebot
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, timedelta
import os
import json

# Ambil kredensial dari Environment Variables Railway
BOT_TOKEN = os.environ.get('BOT_TOKEN')
SHEET_ID = os.environ.get('SHEET_ID')
CREDS_JSON = os.environ.get('GOOGLE_CREDENTIALS')

bot = telebot.TeleBot(BOT_TOKEN)

# Setup koneksi ke Google Sheets
creds_dict = json.loads(CREDS_JSON)
scopes = ["https://www.googleapis.com/auth/spreadsheets"]
creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
client = gspread.authorize(creds)

sheet = client.open_by_key(SHEET_ID)
visit_ws = sheet.worksheet('Visit')
post_ws = sheet.worksheet('Posting')

# Fungsi khusus agar format DD/MM/YYYY tetap bisa diurutkan (sorting) dengan benar
def safe_date_parse(date_str):
    try:
        return datetime.strptime(str(date_str).strip(), "%d/%m/%Y")
    except:
        return datetime.min

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    teks = (
        "🤖 Bot Jadwal Vlogger Aktif!\n\n"
        "Cara pakai:\n"
        "1. /tambahvisit DD/MM/YYYY HH:MM Nama Resto\n"
        "   (Contoh: /tambahvisit 20/06/2026 14:00 Kedai Kopi)\n"
        "2. /jadwalvisit - Lihat jadwal visit\n"
        "3. /jadwalposting - Lihat antrean konten"
    )
    bot.reply_to(message, teks)

@bot.message_handler(commands=['tambahvisit'])
def add_visit(message):
    try:
        # Pisahkan pesan menjadi maksimal 4 bagian
        parts = message.text.split(maxsplit=3)
        if len(parts) < 4:
            bot.reply_to(message, "⚠️ Format salah. Gunakan: /tambahvisit DD/MM/YYYY HH:MM Nama Resto")
            return

        date_str = parts[1]
        time_str = parts[2]
        resto_name = parts[3]

        # Validasi format tanggal dan jam terlebih dahulu
        visit_date = datetime.strptime(date_str, "%d/%m/%Y")
        datetime.strptime(time_str, "%H:%M")

        # Validasi Jadwal Visit
        visits = visit_ws.get_all_records()
        daily_visits = [v for v in visits if str(v.get('Tanggal', '')).strip() == date_str]

        if len(daily_visits) >= 3:
            bot.reply_to(message, f"❌ Kuota visit tanggal {date_str} sudah penuh (Maks 3).")
            return

        if any(str(v.get('Jam', '')).strip() == time_str for v in daily_visits):
            bot.reply_to(message, f"❌ Jadwal jam {time_str} pada {date_str} sudah terisi. Jam tidak boleh bentrok!")
            return

        # Simpan Jadwal Visit
        visit_ws.append_row([date_str, time_str, resto_name])

        # Logika Penjadwalan Posting Otomatis
        posts = post_ws.get_all_records()
        
        post_dates = []
        for p in posts:
            p_date_str = str(p.get('TanggalPosting', '')).strip()
            if p_date_str and p_date_str.lower() != 'dummy':
                try:
                    p_date = datetime.strptime(p_date_str, "%d/%m/%Y")
                    post_dates.append(p_date)
                except ValueError:
                    continue

        if post_dates:
            latest_post_date = max(post_dates)
            post_date = max(latest_post_date + timedelta(days=1), visit_date + timedelta(days=1))
        else:
            post_date = visit_date + timedelta(days=1)

        post_date_str = post_date.strftime("%d/%m/%Y")
        post_ws.append_row([post_date_str, resto_name])

        bot.reply_to(message, f"✅ Berhasil!\n\n🎥 Visit {resto_name} dijadwalkan pada {date_str} {time_str}.\n🗓 Jadwal posting otomatis masuk antrean tanggal {post_date_str}.")

    except ValueError:
        bot.reply_to(message, "⚠️ Format tanggal/jam salah. Pastikan menggunakan DD/MM/YYYY dan HH:MM.")
    except Exception as e:
        bot.reply_to(message, f"Terjadi kesalahan sistem: {str(e)}")

@bot.message_handler(commands=['jadwalvisit'])
def list_visit(message):
    try:
        visits = visit_ws.get_all_records()
        if not visits:
            bot.reply_to(message, "Belum ada jadwal visit yang terdaftar.")
            return
        
        reply = "📌 List Jadwal Visit:\n\n"
        # Urutkan menggunakan fungsi safe_date_parse agar kronologisnya benar
        for v in sorted(visits, key=lambda x: (safe_date_parse(x.get('Tanggal', '')), str(x.get('Jam', '')))):
            if v.get('Tanggal') and str(v.get('Resto', '')).lower() != 'dummy':
                reply += f"• {v['Tanggal']} | {v['Jam']} - {v['Resto']}\n"
        
        if reply == "📌 List Jadwal Visit:\n\n":
            bot.reply_to(message, "Belum ada jadwal visit yang terdaftar.")
        else:
            bot.reply_to(message, reply)
            
    except Exception as e:
        bot.reply_to(message, f"Terjadi kesalahan: {str(e)}")

@bot.message_handler(commands=['jadwalposting'])
def list_posting(message):
    try:
        posts = post_ws.get_all_records()
        if not posts:
            bot.reply_to(message, "Belum ada antrean jadwal posting.")
            return
        
        reply = "🚀 List Antrean Posting (1 Hari 1 Konten):\n\n"
        # Urutkan menggunakan fungsi safe_date_parse agar kronologisnya benar
        for p in sorted(posts, key=lambda x: safe_date_parse(x.get('TanggalPosting', ''))):
            if p.get('TanggalPosting') and str(p.get('Resto', '')).lower() != 'dummy':
                reply += f"• {p['TanggalPosting']} - Konten: {p['Resto']}\n"
        
        if reply == "🚀 List Antrean Posting (1 Hari 1 Konten):\n\n":
            bot.reply_to(message, "Belum ada antrean jadwal posting.")
        else:
            bot.reply_to(message, reply)
            
    except Exception as e:
        bot.reply_to(message, f"Terjadi kesalahan: {str(e)}")

bot.infinity_polling()
