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

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    teks = (
        "🤖 Bot Jadwal Vlogger Aktif!\n\n"
        "Cara pakai:\n"
        "1. /tambahvisit YYYY-MM-DD HH:MM Nama Resto\n"
        "   (Contoh: /tambahvisit 2026-06-20 14:00 Kedai Kopi)\n"
        "2. /jadwalvisit - Lihat jadwal visit\n"
        "3. /jadwalposting - Lihat antrean konten"
    )
    bot.reply_to(message, teks)

@bot.message_handler(commands=['tambahvisit'])
def add_visit(message):
    try:
        # Pisahkan pesan menjadi maksimal 4 bagian: command, tanggal, jam, resto
        parts = message.text.split(maxsplit=3)
        if len(parts) < 4:
            bot.reply_to(message, "⚠️ Format salah. Gunakan: /tambahvisit YYYY-MM-DD HH:MM Nama Resto")
            return

        date_str = parts[1]
        time_str = parts[2]
        resto_name = parts[3]

        # Validasi Jadwal Visit
        visits = visit_ws.get_all_records()
        daily_visits = [v for v in visits if str(v.get('Tanggal', '')) == date_str]

        if len(daily_visits) >= 3:
            bot.reply_to(message, f"❌ Kuota visit tanggal {date_str} sudah penuh (Maks 3).")
            return

        if any(str(v.get('Jam', '')) == time_str for v in daily_visits):
            bot.reply_to(message, f"❌ Jadwal jam {time_str} pada {date_str} sudah terisi. Jam tidak boleh bentrok!")
            return

        # Simpan Jadwal Visit
        visit_ws.append_row([date_str, time_str, resto_name])

        # Logika Penjadwalan Posting Otomatis (H+1 atau hari kosong berikutnya)
        visit_date = datetime.strptime(date_str, "%Y-%m-%d")
        post_date = visit_date + timedelta(days=1)

        posts = post_ws.get_all_records()
        existing_post_dates = [str(p.get('TanggalPosting', '')) for p in posts]

        # Cari slot hari kosong untuk posting
        while post_date.strftime("%Y-%m-%d") in existing_post_dates:
            post_date += timedelta(days=1)

        post_date_str = post_date.strftime("%Y-%m-%d")
        post_ws.append_row([post_date_str, resto_name])

        bot.reply_to(message, f"✅ Berhasil!\n\n🎥 Visit {resto_name} dijadwalkan pada {date_str} {time_str}.\n🗓 Jadwal posting otomatis masuk ke tanggal {post_date_str}.")

    except ValueError:
        bot.reply_to(message, "⚠️ Format tanggal/jam salah. Pastikan menggunakan YYYY-MM-DD dan HH:MM.")
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
        # Urutkan berdasarkan tanggal lalu jam, diubah ke string untuk mencegah error tipe data
        for v in sorted(visits, key=lambda x: (str(x.get('Tanggal', '')), str(x.get('Jam', '')))):
            if v.get('Tanggal') and v.get('Resto'): # Pastikan baris tidak kosong
                reply += f"• {v['Tanggal']} | {v['Jam']} - {v['Resto']}\n"
        
        # Cek jika tidak ada isinya selain header
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
        # Urutkan berdasarkan tanggal posting, diubah ke string
        for p in sorted(posts, key=lambda x: str(x.get('TanggalPosting', ''))):
            if p.get('TanggalPosting') and p.get('Resto'): # Pastikan baris tidak kosong
                reply += f"• {p['TanggalPosting']} - Konten: {p['Resto']}\n"
        
        # Cek jika tidak ada isinya selain header
        if reply == "🚀 List Antrean Posting (1 Hari 1 Konten):\n\n":
            bot.reply_to(message, "Belum ada antrean jadwal posting.")
        else:
            bot.reply_to(message, reply)
            
    except Exception as e:
        bot.reply_to(message, f"Terjadi kesalahan: {str(e)}")

bot.infinity_polling()
