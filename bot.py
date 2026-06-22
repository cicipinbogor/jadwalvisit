import telebot
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, timedelta
import os
import json
import re
from fpdf import FPDF
from apscheduler.schedulers.background import BackgroundScheduler
from pydub import AudioSegment
import speech_recognition as sr

# Ambil kredensial dari Environment Variables Railway
BOT_TOKEN = os.environ.get('BOT_TOKEN')
SHEET_ID = os.environ.get('SHEET_ID')
CREDS_JSON = os.environ.get('GOOGLE_CREDENTIALS')
MY_CHAT_IDS_STR = os.environ.get('MY_CHAT_ID', '') 

# Ekstrak daftar Chat ID menjadi list
CHAT_ID_LIST = [cid.strip() for cid in MY_CHAT_IDS_STR.split(',') if cid.strip()]

bot = telebot.TeleBot(BOT_TOKEN)

# Setup koneksi ke Google Workspace (Hanya Sheets)
creds_dict = json.loads(CREDS_JSON)
scopes = ["https://www.googleapis.com/auth/spreadsheets"]
creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
client = gspread.authorize(creds)

sheet = client.open_by_key(SHEET_ID)
visit_ws = sheet.worksheet('Visit')
post_ws = sheet.worksheet('Posting')

# Cek dan buat otomatis sheet 'Keuangan' jika belum ada
try:
    keuangan_ws = sheet.worksheet('Keuangan')
except gspread.exceptions.WorksheetNotFound:
    keuangan_ws = sheet.add_worksheet(title="Keuangan", rows="1000", cols="4")
    keuangan_ws.append_row(["Tanggal", "Jenis", "Nominal", "Keterangan"])

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

# Cek dan buat otomatis sheet 'Pengaturan' jika belum ada
try:
    settings_ws = sheet.worksheet('Pengaturan')
except gspread.exceptions.WorksheetNotFound:
    settings_ws = sheet.add_worksheet(title="Pengaturan", rows="10", cols="2")
    settings_ws.append_row(["Key", "Value"])
    settings_ws.append_row(["ratecard", DEFAULT_RATECARD])
    settings_ws.append_row(["ratecardumkm", DEFAULT_RATECARDUMKM])
    settings_ws.append_row(["sk", DEFAULT_SK])

# Fungsi Helper Update Pengaturan
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
    try:
        return datetime.strptime(str(date_str).strip(), "%d/%m/%Y")
    except:
        return datetime.min

# Daftar hari & Bulan Indonesia
HARI_INDO = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
BULAN_INDO = ["Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September", "Oktober", "November", "Desember"]

# --- FUNGSI NLP PENGURAI TANGGAL & JAM ---
def parse_tanggal_jam(teks):
    teks_lower = teks.lower()
    now = datetime.now()
    date_str = None
    time_str = None

    if "hari ini" in teks_lower:
        date_str = now.strftime("%d/%m/%Y")
    elif "besok" in teks_lower:
        date_str = (now + timedelta(days=1)).strftime("%d/%m/%Y")
    elif "lusa" in teks_lower:
        date_str = (now + timedelta(days=2)).strftime("%d/%m/%Y")
    else:
        bulan_dict = {"januari": "01", "februari": "02", "maret": "03", "april": "04", "mei": "05", "juni": "06", 
                      "juli": "07", "agustus": "08", "september": "09", "oktober": "10", "november": "11", "desember": "12"}
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
                tgl = m.group(1).zfill(2)
                bln = m.group(2).zfill(2)
                thn = m.group(3) if m.group(3) else str(now.year)
                date_str = f"{tgl}/{bln}/{thn}"

    match_jam = re.search(r'jam\s+(\d{1,2})(?:[\.\:\s]([0-5]\d))?\s*(pagi|siang|sore|malam)?', teks_lower)
    if match_jam:
        h = int(match_jam.group(1))
        m = match_jam.group(2) if match_jam.group(2) else "00"
        keterangan = match_jam.group(3)
        
        if keterangan in ['siang', 'sore'] and h < 12:
            h += 12
        if keterangan == 'malam' and h < 12:
            h += 12
        if keterangan == 'malam' and h == 12: 
            h = 12
            
        time_str = f"{str(h).zfill(2)}:{m}"

    return date_str, time_str

# --- FUNGSI NLP PENGURAI ANGKA PINTAR ---
def extract_nominal(teks):
    teks_angka = teks.lower().replace("seribu", "1000").replace("sejuta", "1000000")
    teks_angka = teks_angka.replace(" ribu", "000").replace("ribu", "000")
    teks_angka = teks_angka.replace(" juta", "000000").replace("juta", "000000")
    teks_angka = teks_angka.replace(".", "").replace("rupiah", "").replace(",", "")
    angka_matches = re.findall(r'\d+', teks_angka)
    if angka_matches:
        return max([int(x) for x in angka_matches])
    return None

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
        "3. /centangvisit Nama Resto (Tandai selesai)\n"
        "4. /tambahposting DD/MM/YYYY Nama Konten\n"
        "5. /editposting TglPosting NamaRestoBaru\n"
        "6. /batalvisit DD/MM/YYYY HH:MM\n"
        "7. /batalposting DD/MM/YYYY\n"
        "8. /jadwalvisit - Lihat jadwal visit\n"
        "9. /jadwalposting - Lihat antrean konten\n"
        "10. /ratecard (atau /rc)\n"
        "11. /ratecardumkm (atau /rcumkm)\n"
        "12. /sk\n"
        "    *(Untuk edit ketik: /editrc, /editrcumkm, /editsk)*\n"
        "13. /invoice Nama - Item1=Harga; Item2=Harga (DP)\n"
        "14. /invoicefull Nama - Item1=Harga; Item2=Harga (Lunas)\n"
        "15. /kwitansi Nama Resto - Nominal - Keterangan\n"
        "16. /catatmasuk Nominal Keterangan\n"
        "17. /catatkeluar Nominal Keterangan\n"
        "18. /rekapbulan MM/YYYY (atau ketik /rekapbulan)\n"
        "19. /spk Nama Resto - Nama Paket\n"
        "20. /helpvoice - Tutorial lengkap Voice Command\n\n"
        "🎙️ *SUPER VOICE COMMAND:* Kirim Voice Note untuk memerintah bot mencatat jadwal, centang visit, bikin invoice, SPK, hingga mencatat pengeluaran tanpa ngetik!"
    )
    bot.reply_to(message, teks, parse_mode='Markdown')

@bot.message_handler(commands=['helpvoice'])
def send_help_voice(message):
    teks = (
        "🎙️ *PANDUAN PERINTAH SUARA (VOICE COMMAND)*\n\n"
        "Agar bot mengerti 100%, ikuti pola kalimat di bawah ini:\n\n"
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
        "• *Buat Kwitansi:* _\"Bot, bikin kwitansi resto Sate Maranggi nominal 400 ribu untuk pelunasan\"_\n"
        "• *Tampilkan Menu:* _\"Bot, kirim rate card\"_ atau _\"Bot, tampilkan syarat dan ketentuan\"_\n\n"
        "💰 *3. KEUANGAN*\n"
        "• *Pemasukan (Terima uang, Cair, DP, Pelunasan):* _\"Bot, catat ada pemasukan pelunasan dari cafe senja sebesar 300 ribu\"_\n"
        "• *Pengeluaran (Beli, Bayar, Bensin, Parkir, Jajan):* _\"Bot, catat pengeluaran beli bensin 50 ribu\"_\n"
        "• *Rekap Bulanan:* _\"Bot, tolong rekap keuangan bulan ini\"_\n\n"
        "💡 *Tips:* Jangan gabungkan 2 perintah dalam 1 Voice Note. Sebutkan angka dengan natural (misal: 'lima ratus ribu').\n"
        "*(Note: Untuk mengedit jadwal, gunakan perintah teks karena rawan kesalahan via suara).* "
    )
    bot.reply_to(message, teks, parse_mode='Markdown')

# --- VOICE COMMAND ROUTER (OTAK UTAMA) ---
@bot.message_handler(content_types=['voice'])
def handle_voice_global(message):
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

        # 0. ROUTER: BANTUAN SUARA (Paling atas)
        if any(kata in teks_lower for kata in ["help voice", "bantuan suara", "tutorial perintah suara", "cara perintah suara"]):
            message.text = "/helpvoice"
            return send_help_voice(message)

        # 1. ROUTER: CEK JADWAL & REKAP
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

        # 2. ROUTER: CENTANG VISIT
        elif any(kata in teks_lower for kata in ["centang", "selesai", "tandai"]) and ("visit" in teks_lower or "kunjungan" in teks_lower):
            match_resto = re.search(r'(?:resto|di|ke|namanya)\s+([a-zA-Z0-9\s]+)', teks_lower)
            resto = match_resto.group(1).strip() if match_resto else ""
            
            if not resto:
                resto = teks_lower.replace("bot", "").replace("centang", "").replace("selesai", "").replace("tandai", "").replace("visit", "").replace("kunjungan", "").replace("resto", "").replace("sudah", "").replace("di", "").strip()
                
            message.text = f"/centangvisit {resto}"
            return mark_done_visit(message)

        # 3. ROUTER: BATAL VISIT & POSTING
        elif any(kata in teks_lower for kata in ["batal", "hapus", "cancel"]) and ("visit" in teks_lower or "kunjungan" in teks_lower):
            date_str, time_str = parse_tanggal_jam(teks_lower)
            if not date_str:
                bot.send_message(message.chat.id, "⚠️ Sebutkan tanggal dan jam visit yang mau dibatalkan. (Contoh: 'Batal visit besok jam 2 siang')")
                return
            if not time_str:
                bot.send_message(message.chat.id, "⚠️ Sebutkan jam visit yang mau dibatalkan juga ya biar nggak salah hapus.")
                return
            message.text = f"/batalvisit {date_str} {time_str}"
            return cancel_visit(message)

        elif any(kata in teks_lower for kata in ["batal", "hapus", "cancel"]) and ("posting" in teks_lower or "konten" in teks_lower):
            date_str, _ = parse_tanggal_jam(teks_lower)
            if not date_str:
                bot.send_message(message.chat.id, "⚠️ Sebutkan tanggal posting yang mau dibatalkan. (Contoh: 'Batal posting tanggal 15 Juni')")
                return
            message.text = f"/batalposting {date_str}"
            return cancel_posting(message)

        # 4. ROUTER: TAMBAH VISIT
        elif any(kata in teks_lower for kata in ["visit", "kunjungan", "masukin jadwal", "tambah jadwal"]):
            date_str, time_str = parse_tanggal_jam(teks_lower)
            match_resto = re.search(r'(?:di\s+resto|di|resto|ke|namanya)\s+([a-zA-Z0-9\s]+)', teks_lower)
            resto = match_resto.group(1).strip().title() if match_resto else "Resto Baru"
            
            if not date_str: date_str = datetime.now().strftime("%d/%m/%Y")
            if not time_str: time_str = "12:00"
            
            message.text = f"/tambahvisit {date_str} {time_str} {resto}"
            return add_visit(message)

        # 5. ROUTER: TAMBAH POSTING
        elif any(kata in teks_lower for kata in ["posting", "konten"]):
            date_str, _ = parse_tanggal_jam(teks_lower)
            match_resto = re.search(r'(?:konten|resto|untuk|tentang)\s+([a-zA-Z0-9\s]+)', teks_lower)
            resto = match_resto.group(1).strip().title() if match_resto else "Konten Baru"
            
            if not date_str: date_str = datetime.now().strftime("%d/%m/%Y")
            
            message.text = f"/tambahposting {date_str} {resto}"
            return add_posting(message)
            
        # 6. ROUTER: RATECARD & SK
        elif any(kata in teks_lower for kata in ["rate card umkm", "ratecard umkm", "paket umkm", "harga umkm"]):
            message.text = "/ratecardumkm"
            return send_ratecard_umkm(message)
            
        elif any(kata in teks_lower for kata in ["rate card", "ratecard", "harga paket", "price list", "pricelist"]):
            message.text = "/ratecard"
            return send_ratecard(message)
            
        elif any(kata in teks_lower for kata in ["syarat dan ketentuan", "aturan main", "kirim sk", "aturan kerja sama"]):
            message.text = "/sk"
            return send_sk(message)

        # 7. ROUTER: INVOICE 
        elif "invoice" in teks_lower:
            is_full = "full" in teks_lower or "lunas" in teks_lower
            nominal_inv = extract_nominal(teks_lower)
            
            if nominal_inv:
                resto = "Klien"
                item_name = "Paket Konten"
                
                match_all = re.search(r'resto\s+(.+?)\s+(?:paket|item)\s+(.+?)\s+(?:harga|nominal|sebesar|lunas|full|\d)', teks_lower)
                
                if match_all:
                    resto = match_all.group(1).strip().title()
                    item_name = match_all.group(2).strip().title()
                else:
                    match_resto = re.search(r'resto\s+(.+?)\s+(?:harga|nominal|sebesar|lunas|full|\d)', teks_lower)
                    if match_resto:
                        resto = match_resto.group(1).strip().title()
                
                if is_full:
                    message.text = f"/invoicefull {resto} - {item_name}={nominal_inv}"
                    return generate_invoice_full(message)
                else:
                    message.text = f"/invoice {resto} - {item_name}={nominal_inv}"
                    return generate_invoice(message)
            else:
                bot.send_message(message.chat.id, "⚠️ Format invoice suara kurang jelas. Pastikan sebutkan nama resto dan nominal harganya.")
                return

        # 8. ROUTER: KWITANSI
        elif "kwitansi" in teks_lower:
            match_kwt = re.search(r'(?:kwitansi|resto)\s+(.+?)\s+(?:sebesar|nominal|harga)\s+(.+?)\s+(?:untuk|buat)\s+(.+)', teks_lower)
            if match_kwt:
                resto = match_kwt.group(1).title()
                nom_str = match_kwt.group(2)
                ket = match_kwt.group(3).capitalize()
                nominal_kwt = extract_nominal(nom_str)
                
                if nominal_kwt:
                    message.text = f"/kwitansi {resto} - {nominal_kwt} - {ket}"
                    return generate_kwitansi(message)
            bot.send_message(message.chat.id, "⚠️ Format kwitansi suara salah. Coba:\n_'Bikin kwitansi resto [Nama] nominal [Angka] untuk [Keterangan]'_")
            return

        # 9. ROUTER: SPK
        elif "spk" in teks_lower:
            match_spk = re.search(r'(?:spk|resto)\s+(.+?)\s+(?:dengan\s+)?(?:paket)\s+(.+)', teks_lower)
            if match_spk:
                resto = match_spk.group(1).title()
                paket = "Paket " + match_spk.group(2).title()
                message.text = f"/spk {resto} - {paket}"
                return generate_spk(message)
            bot.send_message(message.chat.id, "⚠️ Format SPK suara salah. Coba:\n_'Bikin SPK resto [Nama] paket [Nama Paket]'_")
            return

        # 10. ROUTER: KEUANGAN (Fallback)
        else:
            nominal = extract_nominal(teks_lower)
            if not nominal:
                bot.send_message(message.chat.id, "⚠️ Maaf, instruksi suara tidak dikenali. Pastikan menyebut kata kunci seperti 'Visit', 'Posting', 'Kwitansi', 'Invoice', atau nominal uang untuk dicatat.\n\nKetik /helpvoice untuk melihat panduan.")
                return
                
            tgl_sekarang = datetime.now().strftime("%d/%m/%Y")
            
            if any(kata in teks_lower for kata in ["pemasukan", "terima uang", "terima dp", "pelunasan", "bayaran", "cair", "uang masuk"]):
                jenis = "Pemasukan"
                keuangan_ws.append_row([tgl_sekarang, jenis, nominal, teks_hasil.capitalize()])
                bot.send_message(message.chat.id, f"✅ *Pemasukan Dicatat via Suara!*\n\n📅 Tanggal: {tgl_sekarang}\n💰 Nominal: Rp {nominal:,.0f}\n📝 Ket: {teks_hasil.capitalize()}", parse_mode="Markdown")
            
            elif any(kata in teks_lower for kata in ["keluar", "pengeluaran", "beli", "bayar", "bensin", "parkir", "makan", "jajan", "tol", "uang keluar"]):
                jenis = "Pengeluaran"
                keuangan_ws.append_row([tgl_sekarang, jenis, nominal, teks_hasil.capitalize()])
                bot.send_message(message.chat.id, f"📉 *Pengeluaran Dicatat via Suara!*\n\n📅 Tanggal: {tgl_sekarang}\n💸 Nominal: Rp {nominal:,.0f}\n📝 Ket: {teks_hasil.capitalize()}", parse_mode="Markdown")
            
            else:
                bot.send_message(message.chat.id, "⚠️ Bot menemukan angka, tapi bingung ini uang masuk atau keluar. Tolong sebutkan kata 'Terima Uang', 'Pengeluaran', atau 'Bayar'.")

    except sr.UnknownValueError:
        bot.reply_to(message, "⚠️ Bot tidak bisa mendengar suara dengan jelas. Coba ulangi pelan-pelan ya.")
    except sr.RequestError as e:
        bot.reply_to(message, f"⚠️ Layanan pengenalan suara sedang gangguan: {e}")
    except Exception as e:
        bot.reply_to(message, f"⚠️ Terjadi kesalahan sistem: {str(e)}")

# --- FUNGSI STANDAR (COMMAND TEXT & EDIT TEMPLATE) ---

@bot.message_handler(commands=['editratecard', 'editrc'])
def edit_ratecard(message):
    try:
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2:
            records = settings_ws.get_all_records()
            current_text = next((str(r['Value']) for r in records if str(r.get('Key', '')).strip().lower() == 'ratecard'), DEFAULT_RATECARD)
            reply_text = (
                "📋 *Template Rate Card saat ini:*\n"
                "_Ketuk teks di bawah untuk menyalin otomatis._\n\n"
                f"`{current_text}`\n\n"
                "💡 *Cara Edit:* Salin teks di atas, edit harga/paketnya, lalu kirim kembali dengan format:\n"
                "`/editrc [Teks Baru yang sudah kamu edit]`"
            )
            bot.reply_to(message, reply_text, parse_mode='Markdown')
            return
            
        new_text = parts[1].strip()
        update_pengaturan('ratecard', new_text)
        bot.reply_to(message, "✅ Teks Rate Card berhasil diperbarui!")
    except Exception as e:
        bot.reply_to(message, f"⚠️ Terjadi kesalahan: {str(e)}")

@bot.message_handler(commands=['editratecardumkm', 'editrcumkm'])
def edit_ratecard_umkm(message):
    try:
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2:
            records = settings_ws.get_all_records()
            current_text = next((str(r['Value']) for r in records if str(r.get('Key', '')).strip().lower() == 'ratecardumkm'), DEFAULT_RATECARDUMKM)
            reply_text = (
                "📋 *Template Rate Card UMKM saat ini:*\n"
                "_Ketuk teks di bawah untuk menyalin otomatis._\n\n"
                f"`{current_text}`\n\n"
                "💡 *Cara Edit:* Salin teks di atas, edit ketentuannya, lalu kirim kembali dengan format:\n"
                "`/editrcumkm [Teks Baru]`"
            )
            bot.reply_to(message, reply_text, parse_mode='Markdown')
            return
            
        new_text = parts[1].strip()
        update_pengaturan('ratecardumkm', new_text)
        bot.reply_to(message, "✅ Teks Rate Card UMKM berhasil diperbarui!")
    except Exception as e:
        bot.reply_to(message, f"⚠️ Terjadi kesalahan: {str(e)}")

@bot.message_handler(commands=['editsk'])
def edit_sk(message):
    try:
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2:
            records = settings_ws.get_all_records()
            current_text = next((str(r['Value']) for r in records if str(r.get('Key', '')).strip().lower() == 'sk'), DEFAULT_SK)
            reply_text = (
                "📋 *Template Syarat & Ketentuan saat ini:*\n"
                "_Ketuk teks di bawah untuk menyalin otomatis._\n\n"
                f"`{current_text}`\n\n"
                "💡 *Cara Edit:* Salin teks di atas, sesuaikan aturannya, lalu kirim kembali dengan format:\n"
                "`/editsk [Teks Baru]`"
            )
            bot.reply_to(message, reply_text, parse_mode='Markdown')
            return
            
        new_text = parts[1].strip()
        update_pengaturan('sk', new_text)
        bot.reply_to(message, "✅ Teks Syarat & Ketentuan berhasil diperbarui!")
    except Exception as e:
        bot.reply_to(message, f"⚠️ Terjadi kesalahan: {str(e)}")

@bot.message_handler(commands=['centangvisit'])
def mark_done_visit(message):
    try:
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2:
            bot.reply_to(message, "⚠️ Format salah. Gunakan:\n/centangvisit Nama Resto")
            return
            
        target_resto = parts[1].strip().lower().replace("selesai", "").replace("sudah", "").replace("centang", "").strip()
        visits = visit_ws.get_all_records()
        row_to_edit = None
        resto_asli = ""
        
        for idx, v in enumerate(visits, start=2):
            resto_sheet = str(v.get('Resto', '')).strip()
            if (target_resto in resto_sheet.lower() or resto_sheet.lower() in target_resto) and "✅" not in resto_sheet:
                row_to_edit = idx
                resto_asli = resto_sheet
                break
                
        if row_to_edit:
            visit_ws.update_cell(row_to_edit, 3, f"{resto_asli} ✅")
            bot.send_message(message.chat.id, f"✅ *Sip!* Jadwal visit ke *{resto_asli}* sudah ditandai selesai.", parse_mode='Markdown')
        else:
            bot.send_message(message.chat.id, f"❌ Jadwal visit ke '{parts[1]}' tidak ditemukan atau sudah dicentang sebelumnya.")
            
    except Exception as e:
        bot.reply_to(message, f"Terjadi kesalahan sistem: {str(e)}")

@bot.message_handler(commands=['spk'])
def generate_spk(message):
    try:
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2 or '-' not in parts[1]:
            bot.reply_to(message, "⚠️ Format salah. Gunakan:\n/spk Nama Resto - Nama Paket\n\nContoh:\n/spk Brano Pizzeria - Paket Gacor")
            return

        subparts = parts[1].split('-', 1)
        resto = subparts[0].strip()
        paket = subparts[1].strip()

        tgl_sekarang = datetime.now().strftime("%d/%m/%Y")
        pdf_filename = f"SPK_{resto.replace(' ', '_')}.pdf"

        pdf = FPDF()
        pdf.add_page()

        if os.path.exists("logo.png"):
            pdf.image("logo.png", x=10, y=2, w=32)
            pdf.set_xy(45, 10)
        else:
            pdf.set_xy(10, 10)

        pdf.set_font("helvetica", "B", 24)
        pdf.set_text_color(0, 0, 0)
        pdf.cell(0, 8, "Cicipin Bogor", ln=True)

        if os.path.exists("logo.png"):
            pdf.set_x(45)

        pdf.set_font("helvetica", "", 10)
        pdf.set_text_color(100, 100, 100)
        pdf.cell(0, 5, "Instagram Food Vlogger & Digital Content Creator", ln=True)

        if os.path.exists("logo.png"):
            pdf.set_x(45)
        pdf.set_font("helvetica", "I", 9)
        pdf.set_text_color(120, 120, 120)
        pdf.cell(0, 5, "WhatsApp: 085173134492 | Email: cicipinbogor@gmail.com", ln=True)

        pdf.ln(3)
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
        pdf.cell(35, 6, "Pihak Pertama", 0, 0)
        pdf.set_font("helvetica", "", 11)
        pdf.cell(0, 6, ": Cicipin Bogor (Kreator Konten)", ln=True)

        pdf.set_font("helvetica", "B", 11)
        pdf.cell(35, 6, "Pihak Kedua", 0, 0)
        pdf.set_font("helvetica", "", 11)
        pdf.cell(0, 6, f": {resto} (Klien / Resto)", ln=True)
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

        ttd_file = None
        for ext in ["ttd.png", "ttd.jpg", "TTD.png"]:
            if os.path.exists(ext):
                ttd_file = ext
                break

        if ttd_file:
            pdf.image(ttd_file, x=45, y=y_ttd + 2, w=25)

        pdf.ln(25) 

        pdf.set_font("helvetica", "BU", 11)
        pdf.cell(95, 6, "Cicipin Bogor", 0, 0, "C")
        pdf.cell(95, 6, f"{resto}", 0, 1, "C")

        pdf.output(pdf_filename)

        bot.send_message(message.chat.id, "⏳ Sedang menyusun Surat Perjanjian Kerja Sama (SPK)...")

        caption_text = f"✅ *SPK Sukses Dibuat!*\n\n📄 Klien: {resto}\n📦 Paket: {paket}\n\n_File PDF SPK di atas bisa langsung kamu forward ke pihak resto agar mereka paham aturan main & hak cipta video Cicipin Bogor._"

        with open(pdf_filename, 'rb') as pdf_file:
            bot.send_document(message.chat.id, pdf_file, caption=caption_text, parse_mode='Markdown')

        if os.path.exists(pdf_filename):
            os.remove(pdf_filename)

    except Exception as e:
        bot.reply_to(message, f"Terjadi kesalahan sistem: {str(e)}")

@bot.message_handler(commands=['catatmasuk'])
def catat_masuk(message):
    try:
        parts = message.text.split(maxsplit=2)
        if len(parts) < 3:
            bot.reply_to(message, "⚠️ Format salah. Gunakan:\n/catatmasuk Nominal Keterangan")
            return
            
        nominal = int(parts[1].replace('.', '').replace('Rp', '').strip())
        keterangan = parts[2]
        tgl_sekarang = datetime.now().strftime("%d/%m/%Y")
        
        keuangan_ws.append_row([tgl_sekarang, "Pemasukan", nominal, keterangan])
        
        bot.reply_to(message, f"✅ *Pemasukan Dicatat!*\n\n📅 Tanggal: {tgl_sekarang}\n💰 Nominal: Rp {nominal:,.0f}\n📝 Ket: {keterangan}", parse_mode='Markdown')
    except ValueError:
        bot.reply_to(message, "⚠️ Nominal harus berupa angka.")
    except Exception as e:
        bot.reply_to(message, f"Terjadi kesalahan: {str(e)}")

@bot.message_handler(commands=['catatkeluar'])
def catat_keluar(message):
    try:
        parts = message.text.split(maxsplit=2)
        if len(parts) < 3:
            bot.reply_to(message, "⚠️ Format salah. Gunakan:\n/catatkeluar Nominal Keterangan")
            return
            
        nominal = int(parts[1].replace('.', '').replace('Rp', '').strip())
        keterangan = parts[2]
        tgl_sekarang = datetime.now().strftime("%d/%m/%Y")
        
        keuangan_ws.append_row([tgl_sekarang, "Pengeluaran", nominal, keterangan])
        
        bot.reply_to(message, f"📉 *Pengeluaran Dicatat!*\n\n📅 Tanggal: {tgl_sekarang}\n💸 Nominal: Rp {nominal:,.0f}\n📝 Ket: {keterangan}", parse_mode='Markdown')
    except ValueError:
        bot.reply_to(message, "⚠️ Nominal harus berupa angka.")
    except Exception as e:
        bot.reply_to(message, f"Terjadi kesalahan: {str(e)}")

@bot.message_handler(commands=['rekapbulan'])
def rekap_bulan(message):
    try:
        parts = message.text.split(maxsplit=1)
        if len(parts) > 1:
            target_month_str = parts[1].strip()
            target_date = datetime.strptime(target_month_str, "%m/%Y")
        else:
            target_date = datetime.now()
            target_month_str = target_date.strftime("%m/%Y")
            
        target_month = target_date.month
        target_year = target_date.year
        
        records = keuangan_ws.get_all_records()
        
        pemasukan_list = []
        pengeluaran_list = []
        total_masuk = 0
        total_keluar = 0
        
        for row in records:
            tgl = str(row.get('Tanggal', '')).strip()
            if not tgl: continue
            
            try:
                dt = datetime.strptime(tgl, "%d/%m/%Y")
                if dt.month == target_month and dt.year == target_year:
                    jenis = str(row.get('Jenis', '')).lower()
                    nominal = int(row.get('Nominal', 0))
                    ket = str(row.get('Keterangan', ''))
                    
                    if jenis == 'pemasukan':
                        pemasukan_list.append(f"• {tgl}: Rp {nominal:,.0f} ({ket})")
                        total_masuk += nominal
                    elif jenis == 'pengeluaran':
                        pengeluaran_list.append(f"• {tgl}: Rp {nominal:,.0f} ({ket})")
                        total_keluar += nominal
            except ValueError:
                continue
                
        profit = total_masuk - total_keluar
        
        reply = f"📊 *REKAP KEUANGAN BULAN {target_month_str}*\n\n"
        reply += f"🟢 *Total Pemasukan:* Rp {total_masuk:,.0f}\n"
        reply += f"🔴 *Total Pengeluaran:* Rp {total_keluar:,.0f}\n"
        reply += f"⭐ *Profit Bersih:* Rp {profit:,.0f}\n\n"
        
        if pemasukan_list or pengeluaran_list:
            reply += "📝 *RINCIAN TRANSAKSI:*\n"
            reply += "*PEMASUKAN:*\n" + ("\n".join(pemasukan_list) if pemasukan_list else "- Tidak ada") + "\n\n"
            reply += "*PENGELUARAN:*\n" + ("\n".join(pengeluaran_list) if pengeluaran_list else "- Tidak ada")
        else:
            reply += "_Belum ada catatan keuangan untuk bulan ini._"
            
        bot.send_message(message.chat.id, reply, parse_mode='Markdown')
        
    except ValueError:
        bot.reply_to(message, "⚠️ Format bulan salah. Gunakan MM/YYYY (contoh: /rekapbulan 06/2026)")
    except Exception as e:
        bot.reply_to(message, f"Terjadi kesalahan sistem: {str(e)}")

@bot.message_handler(commands=['kwitansi'])
def generate_kwitansi(message):
    try:
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2 or '-' not in parts[1]:
            bot.reply_to(message, "⚠️ Format salah. Gunakan:\n/kwitansi Nama Resto - Nominal - Keterangan")
            return
            
        subparts = parts[1].split('-')
        if len(subparts) < 3:
            bot.reply_to(message, "⚠️ Detail kurang lengkap. Pastikan memasukkan Nama, Nominal, dan Keterangan dipisah tanda strip (-).")
            return
            
        resto = subparts[0].strip()
        nominal_str = subparts[1].strip().replace('.', '').replace('Rp', '').strip()
        keterangan = subparts[2].strip()
        
        nominal = int(nominal_str)
        tgl_sekarang = datetime.now().strftime("%d/%m/%Y")
        no_kwt = f"KWT/CCPN/{datetime.now().strftime('%Y%m%d')}/{str(message.message_id)[-4:]}"
        
        pdf_filename = f"Kwitansi_{resto.replace(' ', '_')}.pdf"
        
        pdf = FPDF()
        pdf.add_page()
        
        if os.path.exists("logo.png"):
            pdf.image("logo.png", x=10, y=2, w=32)
            pdf.set_xy(45, 10)
        else:
            pdf.set_xy(10, 10)
            
        pdf.set_font("helvetica", "B", 24)
        pdf.set_text_color(0, 0, 0)
        pdf.cell(0, 8, "Cicipin Bogor", ln=True)
        
        if os.path.exists("logo.png"):
            pdf.set_x(45)
            
        pdf.set_font("helvetica", "", 10)
        pdf.set_text_color(100, 100, 100)
        pdf.cell(0, 5, "Instagram Food Vlogger & Digital Content Creator", ln=True)
        
        if os.path.exists("logo.png"):
            pdf.set_x(45)
        pdf.set_font("helvetica", "I", 9)
        pdf.set_text_color(120, 120, 120)
        pdf.cell(0, 5, "WhatsApp: 085173134492 | Email: cicipinbogor@gmail.com", ln=True)
        
        pdf.ln(3)
        pdf.set_draw_color(200, 200, 200)
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(12)
        
        pdf.set_text_color(0, 0, 0)
        pdf.set_font("helvetica", "B", 18)
        pdf.cell(0, 10, "KWITANSI PEMBAYARAN", ln=True, align="C")
        pdf.ln(8)
        
        pdf.set_font("helvetica", "B", 11)
        pdf.cell(45, 8, "No. Kwitansi", 0, 0)
        pdf.set_font("helvetica", "", 11)
        pdf.cell(0, 8, f": {no_kwt}", ln=True)
        
        pdf.set_font("helvetica", "B", 11)
        pdf.cell(45, 8, "Telah Terima Dari", 0, 0)
        pdf.set_font("helvetica", "", 11)
        pdf.cell(0, 8, f": {resto}", ln=True)
        
        pdf.set_font("helvetica", "B", 11)
        pdf.cell(45, 8, "Uang Sejumlah", 0, 0)
        pdf.set_font("helvetica", "B", 14)
        pdf.set_text_color(0, 100, 0) 
        pdf.cell(0, 8, f": Rp {nominal:,.0f}", ln=True)
        
        pdf.set_text_color(0, 0, 0)
        pdf.set_font("helvetica", "B", 11)
        pdf.cell(45, 8, "Untuk Pembayaran", 0, 0)
        pdf.set_font("helvetica", "", 11)
        pdf.multi_cell(0, 8, f": {keterangan}")
        pdf.ln(15)
        
        pdf.set_font("helvetica", "", 11)
        pdf.cell(120, 6, "", 0, 0)
        pdf.cell(70, 6, f"Bogor, {tgl_sekarang}", 0, 1, "C")
        
        y_ttd = pdf.get_y()
        
        lunas_file = None
        for ext in ["lunas.jpg", "lunas.jpeg", "lunas.png", "LUNAS.jpg", "LUNAS.png"]:
            if os.path.exists(ext):
                lunas_file = ext
                break
                
        if lunas_file:
            pdf.image(lunas_file, x=20, y=y_ttd - 8, w=55)
            
        ttd_file = None
        for ext in ["ttd.png", "ttd.jpg", "TTD.png"]:
            if os.path.exists(ext):
                ttd_file = ext
                break
                
        if ttd_file:
            pdf.image(ttd_file, x=152.5, y=y_ttd + 2, w=25)
        
        pdf.ln(30)
        
        pdf.set_font("helvetica", "BU", 11)
        pdf.cell(120, 6, "", 0, 0)
        pdf.cell(70, 6, "Cicipin Bogor", 0, 1, "C")
        pdf.set_font("helvetica", "I", 9)
        pdf.set_text_color(150, 150, 150)
        pdf.cell(120, 6, "", 0, 0)
        pdf.cell(70, 4, "Verified Official Receipt", 0, 1, "C")
        
        pdf.output(pdf_filename)
        
        bot.send_message(message.chat.id, "⏳ Sedang mencetak Kwitansi Resmi dengan Stempel LUNAS...")
        
        caption_text = f"✅ *Kwitansi Sukses Dibuat!*\n\n📄 Klien: {resto}\n💰 Nominal: Rp {nominal:,.0f}\n📝 Ket: {keterangan}\n\n_File PDF Kwitansi di atas siap di-forward ke klien sebagai bukti lunas._"
        
        with open(pdf_filename, 'rb') as pdf_file:
            bot.send_document(message.chat.id, pdf_file, caption=caption_text, parse_mode='Markdown')
        
        if os.path.exists(pdf_filename):
            os.remove(pdf_filename)
            
    except ValueError:
        bot.reply_to(message, "⚠️ Nominal harga harus angka tanpa titik atau Rp.")
    except Exception as e:
        bot.reply_to(message, f"Terjadi kesalahan sistem: {str(e)}")

@bot.message_handler(commands=['ratecard', 'rc'])
def send_ratecard(message):
    try:
        records = settings_ws.get_all_records()
        teks = next((str(r['Value']) for r in records if str(r.get('Key', '')).strip().lower() == 'ratecard'), DEFAULT_RATECARD)
        bot.reply_to(message, teks, parse_mode='Markdown')
    except Exception as e:
        bot.reply_to(message, f"⚠️ Terjadi kesalahan saat membaca Google Sheets: {e}")

@bot.message_handler(commands=['ratecardumkm', 'rcumkm'])
def send_ratecard_umkm(message):
    try:
        records = settings_ws.get_all_records()
        teks = next((str(r['Value']) for r in records if str(r.get('Key', '')).strip().lower() == 'ratecardumkm'), DEFAULT_RATECARDUMKM)
        bot.reply_to(message, teks, parse_mode='Markdown')
    except Exception as e:
        bot.reply_to(message, f"⚠️ Terjadi kesalahan saat membaca Google Sheets: {e}")

@bot.message_handler(commands=['sk'])
def send_sk(message):
    try:
        records = settings_ws.get_all_records()
        teks = next((str(r['Value']) for r in records if str(r.get('Key', '')).strip().lower() == 'sk'), DEFAULT_SK)
        bot.reply_to(message, teks, parse_mode='Markdown')
    except Exception as e:
        bot.reply_to(message, f"⚠️ Terjadi kesalahan saat membaca Google Sheets: {e}")

def build_invoice_pdf(resto, parsed_items, total_harga, no_inv, tgl_sekarang, is_full_payment=False):
    pdf = FPDF()
    pdf.add_page()
    
    if os.path.exists("logo.png"):
        pdf.image("logo.png", x=10, y=2, w=32)
        pdf.set_xy(45, 10)
    else:
        pdf.set_xy(10, 10)
        
    pdf.set_font("helvetica", "B", 24)
    pdf.set_text_color(0, 0, 0)
    pdf.cell(0, 8, "Cicipin Bogor", ln=True)
    
    if os.path.exists("logo.png"):
        pdf.set_x(45)
        
    pdf.set_font("helvetica", "", 10)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 5, "Instagram Food Vlogger & Digital Content Creator", ln=True)
    
    if os.path.exists("logo.png"):
        pdf.set_x(45)
    pdf.set_font("helvetica", "I", 9)
    pdf.set_text_color(120, 120, 120)
    pdf.cell(0, 5, "WhatsApp: 085173134492 | Email: cicipinbogor@gmail.com", ln=True)
    
    pdf.ln(3)
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
    
    pdf.set_font("helvetica", "B", 11)
    pdf.set_fill_color(240, 240, 240) 
    pdf.set_draw_color(180, 180, 180)
    pdf.cell(120, 10, "Deskripsi Item", border=1, align="C", fill=True)
    pdf.cell(70, 10, "Biaya (IDR)", border=1, ln=True, align="C", fill=True)
    
    pdf.set_font("helvetica", "", 11)
    for item in parsed_items:
        pdf.cell(120, 10, f" {item['name']}", border=1, align="L")
        pdf.cell(70, 10, f"Rp {item['price']:,.0f}", border=1, ln=True, align="R")
    
    if not is_full_payment:
        pdf.set_font("helvetica", "B", 11)
        pdf.cell(120, 10, "Total Keseluruhan", border=1, align="R", fill=True)
        pdf.cell(70, 10, f"Rp {total_harga:,.0f}", border=1, ln=True, align="R", fill=True)
        
        dp_harga = int(total_harga * 0.5)
        pdf.cell(120, 10, "Down Payment (DP 50% untuk Kunci Jadwal)", border=1, align="R")
        pdf.cell(70, 10, f"Rp {dp_harga:,.0f}", border=1, ln=True, align="R")
    else:
        pdf.set_font("helvetica", "B", 11)
        pdf.cell(120, 10, "Total Tagihan (Pembayaran Penuh / Full)", border=1, align="R", fill=True)
        pdf.cell(70, 10, f"Rp {total_harga:,.0f}", border=1, ln=True, align="R", fill=True)
        
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
    if not is_full_payment:
        pdf.cell(0, 5, "*Mohon kirimkan bukti transfer jika pembayaran DP telah dilakukan.", ln=True, align="C")
    else:
        pdf.cell(0, 5, "*Mohon kirimkan bukti transfer jika proses pembayaran pelunasan telah dilakukan.", ln=True, align="C")
        
    pdf.cell(0, 5, "Terima kasih atas kepercayaan Anda bekerja sama dengan Cicipin Bogor!", ln=True, align="C")
    
    return pdf

@bot.message_handler(commands=['invoice'])
def generate_invoice(message):
    try:
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2 or '-' not in parts[1]:
            bot.reply_to(message, "⚠️ Format salah. Gunakan:\n/invoice Nama Resto - Item1=Harga1; Item2=Harga2")
            return
        
        main_parts = parts[1].split('-', 1)
        resto = main_parts[0].strip()
        
        items_raw = main_parts[1].split(';')
        
        parsed_items = []
        total_harga = 0
        
        for item in items_raw:
            if not item.strip():
                continue
            if '=' not in item:
                bot.reply_to(message, f"⚠️ Format salah pada item: '{item.strip()}'. Pastikan pakai tanda '=' untuk memisahkan nama item dan harganya.")
                return
            
            i_name, i_price = item.split('=', 1)
            clean_price = int(i_price.replace('.', '').replace('Rp', '').strip())
            parsed_items.append({"name": i_name.strip(), "price": clean_price})
            total_harga += clean_price
            
        dp_harga = int(total_harga * 0.5)
        tgl_sekarang = datetime.now().strftime("%d/%m/%Y")
        no_inv = f"INV/CCPN/{datetime.now().strftime('%Y%m%d')}/{str(message.message_id)[-4:]}"
        
        pdf_filename = f"Invoice_{resto.replace(' ', '_')}.pdf"
        
        pdf = build_invoice_pdf(resto, parsed_items, total_harga, no_inv, tgl_sekarang, is_full_payment=False)
        pdf.output(pdf_filename)
        
        bot.reply_to(message, "⏳ Sedang menyusun Invoice Rincian DP...")
        
        caption_text = f"✅ *Invoice DP Sukses Dibuat!*\n\n📄 Klien: {resto}\n📋 *Rincian Item:*\n"
        for item in parsed_items:
            caption_text += f" • {item['name']}: Rp {item['price']:,.0f}\n"
            
        caption_text += f"\n💰 *Total Keseluruhan:* Rp {total_harga:,.0f}\n📉 *Tagihan DP (50%):* Rp {dp_harga:,.0f}\n\n_File PDF Cicipin Bogor di atas siap di-forward ke klien._"
        
        with open(pdf_filename, 'rb') as pdf_file:
            bot.send_document(message.chat.id, pdf_file, caption=caption_text, parse_mode='Markdown')
        
        if os.path.exists(pdf_filename):
            os.remove(pdf_filename)

    except ValueError:
        bot.reply_to(message, "⚠️ Kesalahan pada angka. Pastikan nominal harga hanya berupa angka saja (tanpa titik atau Rp).")
    except Exception as e:
        bot.reply_to(message, f"Terjadi kesalahan sistem: {str(e)}")

@bot.message_handler(commands=['invoicefull'])
def generate_invoice_full(message):
    try:
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2 or '-' not in parts[1]:
            bot.reply_to(message, "⚠️ Format salah. Gunakan:\n/invoicefull Nama Resto - Item1=Harga1; Item2=Harga2")
            return
        
        main_parts = parts[1].split('-', 1)
        resto = main_parts[0].strip()
        
        items_raw = main_parts[1].split(';')
        
        parsed_items = []
        total_harga = 0
        
        for item in items_raw:
            if not item.strip():
                continue
            if '=' not in item:
                bot.reply_to(message, f"⚠️ Format salah pada item: '{item.strip()}'. Pastikan pakai tanda '=' untuk memisahkan nama item dan harganya.")
                return
            
            i_name, i_price = item.split('=', 1)
            clean_price = int(i_price.replace('.', '').replace('Rp', '').strip())
            parsed_items.append({"name": i_name.strip(), "price": clean_price})
            total_harga += clean_price
            
        tgl_sekarang = datetime.now().strftime("%d/%m/%Y")
        no_inv = f"INV/CCPN/{datetime.now().strftime('%Y%m%d')}/{str(message.message_id)[-4:]}"
        
        pdf_filename = f"Invoice_Full_{resto.replace(' ', '_')}.pdf"
        
        pdf = build_invoice_pdf(resto, parsed_items, total_harga, no_inv, tgl_sekarang, is_full_payment=True)
        pdf.output(pdf_filename)
        
        bot.reply_to(message, "⏳ Sedang menyusun Invoice Full Payment...")
        
        caption_text = f"✅ *Invoice Pembayaran Penuh Sukses Dibuat!*\n\n📄 Klien: {resto}\n📋 *Rincian Item:*\n"
        for item in parsed_items:
            caption_text += f" • {item['name']}: Rp {item['price']:,.0f}\n"
            
        caption_text += f"\n💰 *Total Pembayaran Lunas:* Rp {total_harga:,.0f}\n\n_File PDF Cicipin Bogor di atas siap di-forward ke klien._"
        
        with open(pdf_filename, 'rb') as pdf_file:
            bot.send_document(message.chat.id, pdf_file, caption=caption_text, parse_mode='Markdown')
        
        if os.path.exists(pdf_filename):
            os.remove(pdf_filename)

    except ValueError:
        bot.reply_to(message, "⚠️ Kesalahan pada angka. Pastikan nominal harga hanya berupa angka saja (tanpa titik atau Rp).")
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

        bot.send_message(message.chat.id, f"✅ Berhasil!\n\n🎥 Visit {resto_name} dijadwalkan pada {date_str} {time_str}.\n🗓 Jadwal posting otomatis masuk antrean tanggal {post_date_str}.")

    except ValueError:
        bot.send_message(message.chat.id, "⚠️ Format tanggal/jam salah. Pastikan menggunakan DD/MM/YYYY dan HH:MM.")
    except Exception as e:
        bot.send_message(message.chat.id, f"Terjadi kesalahan sistem: {str(e)}")

@bot.message_handler(commands=['tambahposting'])
def add_posting(message):
    try:
        parts = message.text.split(maxsplit=2)
        if len(parts) < 3:
            bot.reply_to(message, "⚠️ Format salah. Gunakan:\n/tambahposting DD/MM/YYYY Nama Konten")
            return

        date_str = parts[1].replace('-', '/')
        resto_name = parts[2]

        datetime.strptime(date_str, "%d/%m/%Y")

        posts = post_ws.get_all_records()
        
        for p in posts:
            if str(p.get('TanggalPosting', '')).strip() == date_str:
                bot.reply_to(message, f"❌ Slot posting tanggal {date_str} sudah penuh (Maksimal 1 konten per hari).\n\n🎥 Konten yang sudah terjadwal: {p.get('Resto', '')}")
                return

        post_ws.append_row([date_str, resto_name])
        bot.send_message(message.chat.id, f"✅ Berhasil!\n\n🚀 Jadwal posting konten {resto_name} ditambahkan pada tanggal {date_str}.")

    except ValueError:
        bot.send_message(message.chat.id, "⚠️ Format tanggal salah. Pastikan menggunakan DD/MM/YYYY.")
    except Exception as e:
        bot.send_message(message.chat.id, f"Terjadi kesalahan sistem: {str(e)}")

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

        post_ws.update_cell(row_to_delete, 2, resto_name)
        post_ws.delete_rows(row_to_delete)
        bot.reply_to(message, f"🗑 Jadwal posting untuk {resto_name} pada tanggal {post_date} berhasil dibatalkan.")

    except ValueError:
        bot.reply_to(message, "⚠️ Format salah. Pastikan menggunakan DD/MM/YYYY.")
    except Exception as e:
        bot.reply_to(message, f"Terjadi kesalahan sistem: {str(e)}")

@bot.message_handler(commands=['jadwalvisit'])
def list_visit(message):
    try:
        visits = visit_ws.get_all_records()
        if not visits:
            bot.send_message(message.chat.id, "Belum ada jadwal visit yang terdaftar.")
            return
            
        reply = "📌 *List Jadwal Visit:*\n\n"
        current_date = ""
        
        for v in sorted(visits, key=lambda x: (safe_date_parse(x.get('Tanggal', '')), str(x.get('Jam', '')))):
            tgl_str = str(v.get('Tanggal', '')).strip()
            resto = str(v.get('Resto', '')).strip()
            jam = str(v.get('Jam', '')).strip()
            
            if tgl_str and resto.lower() != 'dummy':
                dt = safe_date_parse(tgl_str)
                if dt != datetime.min:
                    nama_hari = HARI_INDO[dt.weekday()]
                    nama_bulan = BULAN_INDO[dt.month - 1]
                    header_tanggal = f"{nama_hari} {dt.day} {nama_bulan}"
                    
                    if header_tanggal != current_date:
                        if current_date != "":
                            reply += "\n" 
                        reply += f"*{header_tanggal}*\n"
                        current_date = header_tanggal
                        
                    reply += f"• {resto} {jam}\n"
        
        if reply == "📌 *List Jadwal Visit:*\n\n":
            bot.send_message(message.chat.id, "Belum ada jadwal visit yang terdaftar.")
        else:
            bot.send_message(message.chat.id, reply, parse_mode='Markdown')
            
    except Exception as e:
        bot.send_message(message.chat.id, f"Terjadi kesalahan: {str(e)}")

@bot.message_handler(commands=['jadwalposting'])
def list_posting(message):
    try:
        posts = post_ws.get_all_records()
        if not posts:
            bot.reply_to(message, "Belum ada antrean jadwal posting.")
            return
        
        reply = "🚀 List Antrean Posting (1 Hari 1 Konten):\n\n"
        for p in sorted(posts, key=lambda x: safe_date_parse(x.get('TanggalPosting', ''))):
            tgl_str = str(p.get('TanggalPosting', '')).strip()
            resto = str(p.get('Resto', '')).strip()
            
            if tgl_str and resto.lower() != 'dummy':
                dt = safe_date_parse(tgl_str)
                nama_hari = HARI_INDO[dt.weekday()] if dt != datetime.min else ""
                reply += f"• {nama_hari}, {tgl_str} - Konten: {resto}\n"
        
        if reply == "🚀 List Antrean Posting (1 Hari 1 Konten):\n\n":
            bot.send_message(message.chat.id, "Belum ada antrean jadwal posting.")
        else:
            bot.send_message(message.chat.id, reply)
            
    except Exception as e:
        bot.reply_to(message, f"Terjadi kesalahan: {str(e)}")

bot.infinity_polling()
