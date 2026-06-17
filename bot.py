import telebot
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from datetime import datetime, timedelta
import os
import json
from fpdf import FPDF
from apscheduler.schedulers.background import BackgroundScheduler

# Ambil kredensial dari Environment Variables Railway
BOT_TOKEN = os.environ.get('BOT_TOKEN')
SHEET_ID = os.environ.get('SHEET_ID')
FOLDER_ID = os.environ.get('FOLDER_ID') # ID Folder Google Drive untuk simpan Invoice
CREDS_JSON = os.environ.get('GOOGLE_CREDENTIALS')
MY_CHAT_IDS_STR = os.environ.get('MY_CHAT_ID', '') 

# Ekstrak daftar Chat ID menjadi list
CHAT_ID_LIST = [cid.strip() for cid in MY_CHAT_IDS_STR.split(',') if cid.strip()]

bot = telebot.TeleBot(BOT_TOKEN)

# Setup koneksi ke Google Workspace (Sheets & Drive)
creds_dict = json.loads(CREDS_JSON)
scopes = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive" 
]
creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
client = gspread.authorize(creds)

sheet = client.open_by_key(SHEET_ID)
visit_ws = sheet.worksheet('Visit')
post_ws = sheet.worksheet('Posting')

def safe_date_parse(date_str):
    try:
        return datetime.strptime(str(date_str).strip(), "%d/%m/%Y")
    except:
        return datetime.min

# Fungsi Reminder H-1
def kirim_reminder_h1():
    try:
        if not CHAT_ID_LIST:
            return

        besok = datetime.now() + timedelta(days=1)
        tgl_besok_str = besok.strftime("%d/%m/%Y")

        visits = visit_ws.get_all_records()
        posts = post_ws.get_all_records()

        visit_besok = [v for v in visits if str(v.get('Tanggal', '')).strip() == tgl_besok_str]
        post_besok = [p for p in posts if str(p.get('TanggalPosting', '')).strip() == tgl_besok_str]

        pesan = f"🔔 *REMINDER H-1 JADWAL BESOK ({tgl_besok_str})*\n\n"
        pesan += "🎥 *Jadwal Visit Besok:*\n"
        if visit_besok:
            visit_besok_sorted = sorted(visit_besok, key=lambda x: str(x.get('Jam', '')))
            for idx, v in enumerate(visit_besok_sorted, start=1):
                pesan += f"{idx}. ⏰ {v['Jam']} -> {v['Resto']}\n"
        else:
            pesan += "• Tidak ada jadwal visit untuk besok.\n"

        pesan += "\n🚀 *Jadwal Posting Konten Besok:*\n"
        if post_besok:
            for p in post_besok:
                if str(p.get('Resto', '')).lower() != 'dummy':
                    pesan += f"• 📝 Konten: {p['Resto']}\n"
        else:
            pesan += "• Tidak ada antrean postingan untuk besok.\n"

        pesan += "\nJangan lupa siapkan baterai kamera, bersihkan memory card, dan jaga kesehatan ya! 💪🔥"

        for chat_id in CHAT_ID_LIST:
            try:
                bot.send_message(chat_id, pesan, parse_mode='Markdown')
            except Exception as e:
                print(f"Gagal mengirim reminder ke {chat_id}: {str(e)}")

    except Exception as e:
        print(f"Gagal memproses fungsi reminder: {str(e)}")

# Setup Scheduler
scheduler = BackgroundScheduler(timezone="Asia/Jakarta") 
scheduler.add_job(kirim_reminder_h1, 'cron', hour=20, minute=0)
scheduler.start()

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    teks = (
        "🤖 Bot Jadwal Vlogger Aktif!\n\n"
        "Cara pakai:\n"
        "1. /tambahvisit DD/MM/YYYY HH:MM Nama Resto\n"
        "2. /editvisit TglLama JamLama TglBaru JamBaru NamaResto\n"
        "3. /editposting TglPosting NamaRestoBaru\n"
        "4. /batalvisit DD/MM/YYYY HH:MM\n"
        "5. /batalposting DD/MM/YYYY\n"
        "6. /jadwalvisit - Lihat jadwal visit\n"
        "7. /jadwalposting - Lihat antrean konten\n"
        "8. /ratecard - Template harga paket\n"
        "9. /sk - Template Syarat & Ketentuan\n"
        "10. /invoice Nama Resto - Nama Paket - Harga\n"
        "    (Contoh: /invoice Ketan Mansour - Paket Gacor - 800000)"
    )
    bot.reply_to(message, teks, parse_mode='Markdown')

@bot.message_handler(commands=['ratecard'])
def send_ratecard(message):
    teks = (
        "📄 *TEMPLATE RATE CARD & KERJA SAMA*\n\n"
        "Halo! Terima kasih atas ketertarikannya bekerja sama. Berikut adalah penawaran paket liputan kuliner/review:\n\n"
        "📦 *PAKET REGULER (Review Standar)*\n"
        "• 1x Visit & Liputan Resto\n"
        "• 1x Video tayang di TikTok & IG Reels\n"
        "• ✨ *FREE Collab on Instagram*\n"
        "• Keep video permanent\n"
        "• Harga: Rp 500.000\n\n"
        "🚀 *PAKET GACOR (Grand Opening / Event)*\n"
        "• 1x Visit & Liputan Prioritas\n"
        "• 1x Video (TikTok & IG Reels) dengan Hook Khusus Promosi\n"
        "• ✨ *FREE Collab on Instagram*\n"
        "• Keep video permanent\n"
        "• Prioritas jadwal upload\n"
        "• Harga: Rp 800.000\n\n"
        "➕ *ADDITIONAL MENU*\n"
        "• *Owning Content (Hak Milik Video):*\n"
        "  - Kualitas 2K: +Rp 200.000\n"
        "  - Kualitas 4K: +Rp 300.000\n"
        "• *Additional Story (Instagram):*\n"
        "  - 1x Story: +Rp 30.000\n"
        "  - 2x Story: +Rp 50.000\n\n"
        "📌 *Catatan:*\n"
        "• Harga berlaku untuk wilayah Bogor & sekitarnya.\n"
        "• Untuk Syarat & Ketentuan lengkap silakan ketik /sk\n\n"
        "Silakan balas pesan ini jika ada paket yang sesuai atau ingin berdiskusi lebih lanjut! 🙏"
    )
    bot.reply_to(message, teks, parse_mode='Markdown')

@bot.message_handler(commands=['sk'])
def send_sk(message):
    teks = (
        "📝 *TEMPLATE SYARAT & KETENTUAN (S&K) KERJA SAMA*\n\n"
        "Untuk menjaga kenyamanan dan profesionalisme proses produksi konten, berikut adalah S&K yang berlaku:\n\n"
        "1️⃣ *Proses Liputan & Konsumsi*\n"
        "• Pihak resto menyediakan menu andalan yang akan di-review secara gratis.\n"
        "• Proses syuting memakan waktu sekitar 1-2 jam.\n\n"
        "2️⃣ *Sistem Pembayaran (Payment)*\n"
        "• Down Payment (DP) sebesar 50% wajib dibayarkan maksimal H-3 sebelum jadwal visit untuk mengunci slot.\n"
        "• Pelunasan sisa 50% dilakukan maksimal H-1 sebelum video resmi ditayangkan (upload).\n\n"
        "3️⃣ *Reschedule & Pembatalan*\n"
        "• Perubahan jadwal visit wajib diinfokan paling lambat H-2 sebelum hari liputan.\n"
        "• Jika pihak klien membatalkan kerja sama sepihak, maka DP dianggap hangus.\n\n"
        "4️⃣ *Kebijakan Revisi Video*\n"
        "• Klien berhak mendapatkan revisi video maksimal 1x (revisi minor seperti salah info harga, teks, atau penulisan nama).\n\n"
        "5️⃣ *Hak Cipta & Penggunaan Video*\n"
        "• Hak cipta video sepenuhnya milik creator. Konten akan ditayangkan secara permanen di akun creator.\n"
        "• Klien dilarang mengunggah ulang (re-upload) video utuh tanpa membeli opsi *Owning Content*."
    )
    bot.reply_to(message, teks, parse_mode='Markdown')

@bot.message_handler(commands=['invoice'])
def generate_invoice(message):
    try:
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2 or '-' not in parts[1]:
            bot.reply_to(message, "⚠️ Format salah. Gunakan:\n/invoice Nama Resto - Nama Paket - Harga\n\nContoh: /invoice Ketan Mansour - Paket Gacor - 800000")
            return
        
        subparts = parts[1].split('-')
        if len(subparts) < 3:
            bot.reply_to(message, "⚠️ Detail kurang lengkap. Pastikan memasukkan Nama Resto, Paket, dan Harga yang dipisah dengan tanda strip.")
            return

        resto = subparts[0].strip()
        paket = subparts[1].strip()
        harga_str = subparts[2].strip().replace('.', '').replace('Rp', '').strip()
        
        harga = int(harga_str)
        dp_harga = int(harga * 0.5)
        
        tgl_sekarang = datetime.now().strftime("%d/%m/%Y")
        no_inv = f"INV/{datetime.now().strftime('%Y%m%d')}/{str(message.message_id)}"
        
        pdf_filename = f"Invoice_{resto.replace(' ', '_')}.pdf"
        
        # --- PROSES PEMBUATAN PDF (fpdf2) ---
        pdf = FPDF()
        pdf.add_page()
        
        # Desain Header Invoice
        pdf.set_font("helvetica", "B", 20)
        pdf.cell(0, 10, "INVOICE TAGIHAN", ln=True, align="C")
        pdf.set_font("helvetica", "", 10)
        pdf.cell(0, 6, "Digital Content Creator & Food Vlogger", ln=True, align="C")
        pdf.ln(10)
        
        # Informasi Utama Invoice
        pdf.set_font("helvetica", "B", 11)
        pdf.cell(40, 6, "No. Invoice", 0, 0)
        pdf.set_font("helvetica", "", 11)
        pdf.cell(0, 6, f": {no_inv}", ln=True)
        
        pdf.set_font("helvetica", "B", 11)
        pdf.cell(40, 6, "Tanggal", 0, 0)
        pdf.set_font("helvetica", "", 11)
        pdf.cell(0, 6, f": {tgl_sekarang}", ln=True)
        
        pdf.set_font("helvetica", "B", 11)
        pdf.cell(40, 6, "Klien / Resto", 0, 0)
        pdf.set_font("helvetica", "", 11)
        pdf.cell(0, 6, f": {resto}", ln=True)
        pdf.ln(8)
        
        # Tabel Rincian Harga
        pdf.set_font("helvetica", "B", 11)
        pdf.cell(110, 8, "Deskripsi Paket Kerja Sama", 1, 0, "C")
        pdf.cell(80, 8, "Total Biaya (IDR)", 1, 1, "C")
        
        pdf.set_font("helvetica", "", 11)
        pdf.cell(110, 10, f"Review Kuliner - {paket}", 1, 0, "L")
        pdf.cell(80, 10, f"Rp {harga:,.0f}", 1, 1, "R")
        pdf.ln(5)
        
        # Informasi Down Payment
        pdf.set_font("helvetica", "B", 11)
        pdf.cell(110, 8, "Down Payment (DP 50% untuk Kunci Jadwal):", 0, 0, "R")
        pdf.cell(80, 8, f"Rp {dp_harga:,.0f}", 0, 1, "R")
        pdf.ln(10)
        
        # Ketentuan Pembayaran (Ganti tanda peluru dengan tanda strip agar fpdf tidak error)
        pdf.set_font("helvetica", "B", 10)
        pdf.cell(0, 6, "Metode Pembayaran Transfer:", ln=True)
        pdf.set_font("helvetica", "", 10)
        pdf.cell(0, 5, "- Bank BCA: [Isi No Rekening Kamu]", ln=True)
        pdf.cell(0, 5, "- Atas Nama: [Isi Nama Kamu]", ln=True)
        pdf.ln(10)
        
        pdf.set_font("helvetica", "I", 9)
        pdf.cell(0, 5, "*Catatan: Harap kirimkan bukti transfer jika sudah melakukan pembayaran DP.", ln=True, align="C")
        
        # Simpan file
        pdf.output(pdf_filename)
        
        # --- PROSES UPLOAD KE GOOGLE DRIVE ---
        bot.reply_to(message, "⏳ Sedang memproses pembuatan PDF dan mengunggah ke Google Drive...")
        
        drive_service = build('drive', 'v3', credentials=creds)
        file_metadata = {
            'name': f"Invoice_{resto}_{datetime.now().strftime('%d-%m-%Y')}.pdf",
            'parents': [FOLDER_ID] if FOLDER_ID else []
        }
        media = MediaFileUpload(pdf_filename, mimetype='application/pdf')
        
        uploaded_file = drive_service.files().create(
            body=file_metadata, 
            media_body=media, 
            fields='id, webViewLink'
        ).execute()
        
        drive_link = uploaded_file.get('webViewLink')
        
        if os.path.exists(pdf_filename):
            os.remove(pdf_filename)
            
        bot.reply_to(message, f"✅ *Invoice Sukses Dibuat!*\n\n📄 Klien: {resto}\n📋 Paket: {paket}\n💰 Total: Rp {harga:,.0f}\n📉 Tagihan DP (50%): Rp {dp_harga:,.0f}\n\n📂 *Link Google Drive:*\n{drive_link}", parse_mode='Markdown')

    except ValueError:
        bot.reply_to(message, "⚠️ Kesalahan input harga. Pastikan menulis angka harga dengan benar tanpa simbol mata uang.")
    except Exception as e:
        bot.reply_to(message, f"Terjadi kesalahan sistem: {str(e)}")

@bot.message_handler(commands=['tambahvisit'])
def add_visit(message):
    try:
        parts = message.text.split(maxsplit=3)
        if len(parts) < 4:
            bot.reply_to(message, "⚠️ Format salah. Gunakan: /tambahvisit DD/MM/YYYY HH:MM Nama Resto")
            return

        date_str = parts[1].replace('-', '/')
        time_str = parts[2]
        resto_name = parts[3]

        visit_date = datetime.strptime(date_str, "%d/%m/%Y")
        datetime.strptime(time_str, "%H:%M")

        visits = visit_ws.get_all_records()
        daily_visits = [v for v in visits if str(v.get('Tanggal', '')).strip() == date_str]

        if len(daily_visits) >= 3:
            bot.reply_to(message, f"❌ Kuota visit tanggal {date_str} sudah penuh (Maks 3).")
            return

        if any(str(v.get('Jam', '')).strip() == time_str for v in daily_visits):
            bot.reply_to(message, f"❌ Jadwal jam {time_str} pada {date_str} sudah terisi. Jam tidak boleh bentrok!")
            return

        visit_ws.append_row([date_str, time_str, resto_name])

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

@bot.message_handler(commands=['editvisit'])
def edit_visit(message):
    try:
        parts = message.text.split(maxsplit=5)
        if len(parts) < 6:
            bot.reply_to(message, "⚠️ Format salah. Gunakan:\n/editvisit TglLama JamLama TglBaru JamBaru Nama Resto")
            return

        old_date = parts[1].replace('-', '/')
        old_time = parts[2]
        new_date = parts[3].replace('-', '/')
        new_time = parts[4]
        new_resto = parts[5]

        datetime.strptime(new_date, "%d/%m/%Y")
        datetime.strptime(new_time, "%H:%M")

        visits = visit_ws.get_all_records()
        
        row_to_edit = None
        for idx, v in enumerate(visits, start=2):
            if str(v.get('Tanggal', '')).strip() == old_date and str(v.get('Jam', '')).strip() == old_time:
                row_to_edit = idx
                break
        
        if not row_to_edit:
            bot.reply_to(message, f"❌ Jadwal visit lama pada {old_date} jam {old_time} tidak ditemukan.")
            return

        other_visits = [v for v in visits if not (str(v.get('Tanggal', '')).strip() == old_date and str(v.get('Jam', '')).strip() == old_time)]
        daily_visits_new = [v for v in other_visits if str(v.get('Tanggal', '')).strip() == new_date]

        if len(daily_visits_new) >= 3:
            bot.reply_to(message, f"❌ Kuota visit tanggal {new_date} sudah penuh (Maks 3).")
            return

        if any(str(v.get('Jam', '')).strip() == new_time for v in daily_visits_new):
            bot.reply_to(message, f"❌ Jadwal jam {new_time} pada {new_date} sudah terisi. Jam tidak boleh bentrok!")
            return

        visit_ws.update_cell(row_to_edit, 1, new_date)
        visit_ws.update_cell(row_to_edit, 2, new_time)
        visit_ws.update_cell(row_to_edit, 3, new_resto)

        bot.reply_to(message, f"✅ Jadwal visit berhasil diubah!\n\nJadwal Baru:\n📅 {new_date}\n⏰ {new_time}\n🎥 {new_resto}")

    except ValueError:
        bot.reply_to(message, "⚠️ Format tanggal/jam salah. Pastikan menggunakan DD/MM/YYYY dan HH:MM.")
    except Exception as e:
        bot.reply_to(message, f"Terjadi kesalahan sistem: {str(e)}")

@bot.message_handler(commands=['editposting'])
def edit_posting(message):
    try:
        parts = message.text.split(maxsplit=2)
        if len(parts) < 3:
            bot.reply_to(message, "⚠️ Format salah. Gunakan:\n/editposting TglPosting Nama Resto Baru")
            return

        post_date = parts[1].replace('-', '/')
        new_resto = parts[2]

        datetime.strptime(post_date, "%d/%m/%Y")

        posts = post_ws.get_all_records()
        
        row_to_edit = None
        for idx, p in enumerate(posts, start=2):
            if str(p.get('TanggalPosting', '')).strip() == post_date:
                row_to_edit = idx
                break
        
        if not row_to_edit:
            bot.reply_to(message, f"❌ Jadwal posting pada tanggal {post_date} tidak ditemukan.")
            return

        post_ws.update_cell(row_to_edit, 2, new_resto)
        bot.reply_to(message, f"✅ Jadwal posting tanggal {post_date} berhasil diubah menjadi: 🎥 {new_resto}")

    except ValueError:
        bot.reply_to(message, "⚠️ Format tanggal salah. Pastikan menggunakan DD/MM/YYYY.")
    except Exception as e:
        bot.reply_to(message, f"Terjadi kesalahan sistem: {str(e)}")

@bot.message_handler(commands=['batalvisit'])
def cancel_visit(message):
    try:
        parts = message.text.split(maxsplit=2)
        if len(parts) < 3:
            bot.reply_to(message, "⚠️ Format salah. Gunakan:\n/batalvisit DD/MM/YYYY HH:MM")
            return

        date_str = parts[1].replace('-', '/')
        time_str = parts[2]

        datetime.strptime(date_str, "%d/%m/%Y")
        datetime.strptime(time_str, "%H:%M")

        visits = visit_ws.get_all_records()
        row_to_delete = None
        resto_name = ""

        for idx, v in enumerate(visits, start=2):
            if str(v.get('Tanggal', '')).strip() == date_str and str(v.get('Jam', '')).strip() == time_str:
                row_to_delete = idx
                resto_name = v.get('Resto', '')
                break

        if not row_to_delete:
            bot.reply_to(message, f"❌ Jadwal visit pada {date_str} jam {time_str} tidak ditemukan.")
            return

        visit_ws.delete_rows(row_to_delete)
        bot.reply_to(message, f"🗑 Jadwal visit ke {resto_name} pada {date_str} jam {time_str} berhasil dibatalkan.")

    except ValueError:
        bot.reply_to(message, "⚠️ Format tanggal/jam salah. Pastikan menggunakan DD/MM/YYYY dan HH:MM.")
    except Exception as e:
        bot.reply_to(message, f"Terjadi kesalahan sistem: {str(e)}")

@bot.message_handler(commands=['batalposting'])
def cancel_posting(message):
    try:
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2:
            bot.reply_to(message, "⚠️ Format salah. Gunakan:\n/batalposting DD/MM/YYYY")
            return

        post_date = parts[1].replace('-', '/')
        datetime.strptime(post_date, "%d/%m/%Y")

        posts = post_ws.get_all_records()
        row_to_delete = None
        resto_name = ""

        for idx, p in enumerate(posts, start=2):
            if str(p.get('TanggalPosting', '')).strip() == post_date:
                row_to_delete = idx
                resto_name = p.get('Resto', '')
                break

        if not row_to_delete:
            bot.reply_to(message, f"❌ Jadwal posting pada tanggal {post_date} tidak ditemukan.")
            return

        post_ws.delete_rows(row_to_delete)
        bot.reply_to(message, f"🗑 Jadwal posting untuk {resto_name} pada tanggal {post_date} berhasil dibatalkan.")

    except ValueError:
        bot.reply_to(message, "⚠️ Format tanggal salah. Pastikan menggunakan DD/MM/YYYY.")
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
