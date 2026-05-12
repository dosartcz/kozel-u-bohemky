from flask import Flask, render_template, request, redirect, url_for, session, send_file, Response
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
import os
import io
import json
import smtplib
import ssl
import hmac as _hmac
import hashlib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import date, datetime

app = Flask(__name__)

# ─── Logging ─────────────────────────────────────────────────────────────────
_log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'app-error.log')
logging.basicConfig(
    filename=_log_path,
    level=logging.ERROR,
    format='%(asctime)s %(levelname)s %(message)s'
)
app.logger.setLevel(logging.ERROR)
app.secret_key = os.environ.get('SECRET_KEY')

ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD')

SMTP_HOST = 'smtp.hosting90.cz'
SMTP_PORT = 465
SMTP_USER = 'rezervace@kozelubohemky.cz'
SMTP_PASS = os.environ.get('SMTP_PASS')
NOTIFY_TO = 'rezervace@kozelubohemky.cz'

DB_PATH    = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'restaurant.db')
FONTS_DIR  = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fonts')

# ─── Fonty ────────────────────────────────────────────────────────────────────

def _ensure_fonts():
    """Ověří přítomnost fontů Exo 2 ve složce fonts/."""
    for fname in ('Exo2-Regular.ttf', 'Exo2-Black.ttf'):
        if not os.path.exists(os.path.join(FONTS_DIR, fname)):
            print(f'Varování: chybí font {fname} ve složce fonts/ – export PDF/JPG nebude fungovat.')


def _font_path(bold=False):
    fname = 'Exo2-Black.ttf' if bold else 'Exo2-Regular.ttf'
    return os.path.join(FONTS_DIR, fname)


# ─── Databáze ────────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    return conn


def init_db():
    conn = get_db()
    c = conn.cursor()

    c.execute('''
        CREATE TABLE IF NOT EXISTS daily_menu (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            date       TEXT    UNIQUE NOT NULL,
            promo_text TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS menu_sections (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            menu_id  INTEGER NOT NULL,
            title    TEXT    NOT NULL,
            position INTEGER DEFAULT 0,
            FOREIGN KEY (menu_id) REFERENCES daily_menu(id) ON DELETE CASCADE
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS menu_items (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            section_id INTEGER NOT NULL,
            portion    TEXT,
            name       TEXT    NOT NULL,
            price      TEXT,
            position   INTEGER DEFAULT 0,
            FOREIGN KEY (section_id) REFERENCES menu_sections(id) ON DELETE CASCADE
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS restaurant_info (
            key   TEXT PRIMARY KEY,
            value TEXT
        )
    ''')

    defaults = [
        ('name',    'Kozel u Bohemky'),
        ('address', 'Vaše ulice 123, Praha'),
        ('phone',   '+420 000 000 000'),
        ('email',   'info@restaurace.cz'),
        ('hours',   'Po–Pá: 11:00 – 14:30'),
    ]
    for key, value in defaults:
        c.execute('INSERT OR IGNORE INTO restaurant_info (key, value) VALUES (?, ?)', (key, value))

    cols = [row[1] for row in c.execute('PRAGMA table_info(daily_menu)').fetchall()]
    if 'promo_text' not in cols:
        c.execute('ALTER TABLE daily_menu ADD COLUMN promo_text TEXT')
    if 'updated_by' not in cols:
        c.execute('ALTER TABLE daily_menu ADD COLUMN updated_by TEXT')

    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            username      TEXT    UNIQUE NOT NULL,
            password_hash TEXT    NOT NULL,
            created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS reservations (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            datum      TEXT    NOT NULL,
            cas        TEXT    NOT NULL,
            pocet      INTEGER NOT NULL,
            jmeno      TEXT    NOT NULL,
            email      TEXT    NOT NULL,
            telefon    TEXT    NOT NULL,
            zprava     TEXT,
            status     TEXT    DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    # Migrace: přidej sloupce pokud chybí (pro existující DB)
    res_cols = [row[1] for row in c.execute('PRAGMA table_info(reservations)').fetchall()]
    if 'status' not in res_cols:
        c.execute("ALTER TABLE reservations ADD COLUMN status TEXT DEFAULT 'pending'")
    if 'lang' not in res_cols:
        c.execute("ALTER TABLE reservations ADD COLUMN lang TEXT DEFAULT 'cs'")
    c.execute('''
        CREATE TABLE IF NOT EXISTS popups (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            title      TEXT    NOT NULL,
            body       TEXT,
            starts_at  TEXT,
            expires_at TEXT    NOT NULL,
            image      TEXT,
            is_active  INTEGER DEFAULT 1,
            created_by TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    # Migrace: přidej sloupce pokud chybí (pro existující DB)
    popup_cols = [row[1] for row in c.execute('PRAGMA table_info(popups)').fetchall()]
    if 'starts_at' not in popup_cols:
        c.execute('ALTER TABLE popups ADD COLUMN starts_at TEXT')
    if 'created_by' not in popup_cols:
        c.execute('ALTER TABLE popups ADD COLUMN created_by TEXT')
    c.execute('''
        CREATE TABLE IF NOT EXISTS popup_items (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            popup_id  INTEGER NOT NULL,
            portion   TEXT,
            name      TEXT    NOT NULL,
            price     TEXT,
            position  INTEGER DEFAULT 0,
            FOREIGN KEY (popup_id) REFERENCES popups(id) ON DELETE CASCADE
        )
    ''')

    # Oprav starý nesprávný název restaurace
    c.execute("UPDATE restaurant_info SET value = 'Kozel u Bohemky' WHERE key = 'name' AND value = 'Kozlovna u Bohemky'")

    # Seed výchozího admina, pokud tabulka uživatelů je prázdná
    if not c.execute('SELECT 1 FROM users LIMIT 1').fetchone():
        c.execute(
            'INSERT INTO users (username, password_hash) VALUES (?, ?)',
            ('admin', generate_password_hash(ADMIN_PASSWORD))
        )

    conn.commit()
    conn.close()


def get_info():
    conn = get_db()
    rows = conn.execute('SELECT key, value FROM restaurant_info').fetchall()
    conn.close()
    return {r['key']: r['value'] for r in rows}


def get_active_popup():
    """Vrátí aktivní, nevypršelý a již spuštěný popup (nebo None) + jeho položky."""
    now = datetime.now().strftime('%Y-%m-%d %H:%M')
    conn = get_db()
    popup = conn.execute(
        '''SELECT * FROM popups
           WHERE is_active = 1
             AND expires_at >= ?
             AND (starts_at IS NULL OR starts_at <= ?)
           ORDER BY starts_at DESC, created_at DESC LIMIT 1''',
        (now, now)
    ).fetchone()
    items = []
    if popup:
        items = conn.execute(
            'SELECT * FROM popup_items WHERE popup_id = ? ORDER BY position',
            (popup['id'],)
        ).fetchall()
    conn.close()
    return popup, items


# ─── Email helpers ────────────────────────────────────────────────────────────

def _confirm_token(rid):
    """Vygeneruje HMAC token pro jednoklikové potvrzení rezervace."""
    key = app.secret_key.encode() if isinstance(app.secret_key, str) else app.secret_key
    return _hmac.new(key, f'rez-confirm-{rid}'.encode(), hashlib.sha256).hexdigest()[:40]

def _verify_confirm_token(rid, token):
    return _hmac.compare_digest(_confirm_token(rid), token)

def _fmt_datum(datum):
    try:
        d = date.fromisoformat(datum)
        return f'{d.day}. {d.month}. {d.year}'
    except Exception:
        return datum

def _fmt_created_at(raw):
    """Formátuje SQLite timestamp 'YYYY-MM-DD HH:MM:SS' na 'D. M. YYYY HH:MM'."""
    try:
        dt_part = str(raw or '')[:16]
        d_part, t_part = dt_part.split(' ')
        y, m, day = d_part.split('-')
        return f'{int(day)}. {int(m)}. {y} {t_part}'
    except Exception:
        return str(raw or '')

def _send_email(to, subject, body_html, body_text, reply_to=None):
    """Interní helper – odešle email přes SMTP."""
    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From']    = f'Kozel u Bohemky <{SMTP_USER}>'
    msg['To']      = to
    if reply_to:
        msg['Reply-To'] = reply_to
    msg.attach(MIMEText(body_text, 'plain', 'utf-8'))
    msg.attach(MIMEText(body_html, 'html', 'utf-8'))
    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ctx) as srv:
        srv.login(SMTP_USER, SMTP_PASS)
        srv.sendmail(SMTP_USER, [to], msg.as_bytes())

_FONT  = "'Exo 2', Arial, sans-serif"
_GOLD  = '#9f854d'
_LINK  = f'<link href="https://fonts.googleapis.com/css2?family=Exo+2:wght@400;600;700&display=swap" rel="stylesheet">'

def _email_head():
    return f'<head><meta charset="UTF-8">{_LINK}<style>body{{font-family:{_FONT}}}</style></head>'

def _osob(pocet, lang='cs'):
    p = str(pocet)
    if lang == 'en':
        return f'{p} {"guest" if p == "1" else "guests"}'
    return f'{p} {"osobu" if p == "1" else "osoby" if p in ("2","3","4") else "osob"}'

def _guest_footer_html(created_at_fmt, lang='cs'):
    if lang == 'en':
        hours   = 'Monday to Sunday 11:00 – 23:00'
        cr_line = f'Reservation submitted {created_at_fmt}'
    else:
        hours   = 'Pondělí až Neděle 11:00 – 23:00'
        cr_line = f'Rezervace vytvořena {created_at_fmt}'
    try:
        logo_url = url_for('static', filename='logo-email.png', _external=True)
    except Exception:
        logo_url = 'https://kozelubohemky.cz/static/logo-email.png'
    return f"""
    <table cellpadding="0" cellspacing="0" style="width:100%;margin-top:32px;border-top:2px solid #e8e8e8;padding-top:20px">
      <tr><td style="font-family:{_FONT};text-align:left">
        <img src="{logo_url}" alt="Kozel u Bohemky" style="height:44px;margin-bottom:10px;display:block" />
        <span style="font-size:12px;color:#888">
          Sportovní 848/24, 101 00 Praha 10 – Vršovice &nbsp;|&nbsp; {hours}
        </span><br>
        <span style="font-size:12px;color:#888">
          <a href="https://kozelubohemky.cz" style="color:{_GOLD};text-decoration:none">kozelubohemky.cz</a>
          &nbsp;|&nbsp;
          <a href="mailto:info@kozelubohemky.cz" style="color:{_GOLD};text-decoration:none">info@kozelubohemky.cz</a>
          &nbsp;|&nbsp;
          <a href="tel:+420777710712" style="color:{_GOLD};text-decoration:none">(+420) 777 710 712</a>
        </span>
      </td></tr>
    </table>
    <p style="font-size:11px;color:#bbb;text-align:left;margin-top:12px;font-family:{_FONT}">
      {cr_line}
    </p>"""

def _guest_detail_html(datum_fmt, cas, pocet, jmeno, lang='cs'):
    if lang == 'en':
        rows = [
            ('Date &amp; time', f'{datum_fmt} at {cas}'),
            ('Guests',          _osob(pocet, lang='en')),
            ('Name',            jmeno),
        ]
    else:
        rows = [
            ('Datum a čas', f'{datum_fmt} od {cas}'),
            ('Počet hostů', _osob(pocet)),
            ('Na jméno',    jmeno),
        ]
    html = '<table cellpadding="8" cellspacing="0" style="width:100%;border-collapse:collapse;margin-top:16px;margin-bottom:16px">'
    for i, (label, value) in enumerate(rows):
        bg = '#f9f6f0' if i % 2 == 0 else '#fff'
        html += (f'<tr style="background:{bg}">'
                 f'<td style="color:#666;font-family:{_FONT};width:160px;font-size:14px">{label}</td>'
                 f'<td style="font-family:{_FONT};font-size:14px"><strong>{value}</strong></td>'
                 f'</tr>')
    html += '</table>'
    return html


# ─── Email restauraci – nová rezervace ────────────────────────────────────────

def _send_reservation_email(form, rid, created_at_fmt):
    """Odešle emailové oznámení o nové rezervaci na NOTIFY_TO."""
    try:
        datum   = form.get('datum', '')
        cas     = form.get('cas', '')
        pocet   = form.get('pocet', '')
        jmeno   = form.get('jmeno', '')
        email   = form.get('email', '')
        telefon = form.get('telefon', '')
        zprava  = (form.get('zprava', '') or '').strip()

        datum_fmt   = _fmt_datum(datum)
        subject     = 'Nová rezervace do Kozla'

        confirm_url = url_for('confirm_reservation', rid=rid,
                              token=_confirm_token(rid), _external=True)
        admin_url   = url_for('admin_rezervace', _external=True)

        zprava_block = (
            f'<p style="font-family:{_FONT};font-size:15px;color:#555;margin:12px 0 0">'
            f'<em>„{zprava}"</em></p>'
        ) if zprava else ''

        body_html = f"""
        <html>{_email_head()}<body style="font-family:{_FONT};color:#333;max-width:600px;margin:0 auto;padding:24px;text-align:left">

          <h2 style="color:{_GOLD};font-family:{_FONT};margin:0 0 20px">Nová rezervace</h2>

          <p style="font-family:{_FONT};font-size:16px;margin:0 0 6px">
            Na <strong>{datum_fmt}</strong> od <strong>{cas}</strong> pro <strong>{_osob(pocet)}</strong>
          </p>
          <p style="font-family:{_FONT};font-size:16px;margin:0 0 6px">
            Na jméno <strong>{jmeno}</strong>
          </p>
          {zprava_block}

          <p style="font-family:{_FONT};font-size:14px;margin:16px 0 0">
            📞 <a href="tel:{telefon}" style="color:{_GOLD};text-decoration:none">{telefon}</a>
            &nbsp;&nbsp;
            ✉️ <a href="mailto:{email}" style="color:{_GOLD};text-decoration:none">{email}</a>
          </p>

          <hr style="border:none;border-top:2px solid #e8e8e8;margin:20px 0">

          <table cellpadding="0" cellspacing="0"><tr>
            <td style="padding-right:10px">
              <a href="{confirm_url}"
                 style="display:inline-block;background:{_GOLD};color:#fff;text-decoration:none;
                        padding:11px 24px;border-radius:6px;font-family:{_FONT};font-weight:700;font-size:15px">
                ✓ Potvrdit rezervaci
              </a>
            </td>
            <td>
              <a href="{admin_url}"
                 style="display:inline-block;background:#f3f3f3;color:#333;text-decoration:none;
                        padding:11px 24px;border-radius:6px;font-family:{_FONT};font-weight:600;font-size:15px">
                Zobrazit rezervaci
              </a>
            </td>
          </tr></table>

          <p style="font-size:11px;color:#bbb;margin-top:28px;font-family:{_FONT}">
            Rezervace vytvořena {created_at_fmt}
          </p>
        </body></html>"""

        body_text = (
            f"Nová rezervace do Kozla na {datum_fmt} od {cas}\n\n"
            f"Na {datum_fmt} od {cas} pro {_osob(pocet)}\n"
            f"Na jméno {jmeno}\n"
            + (f"Zpráva: {zprava}\n" if zprava else "")
            + f"\n📞 {telefon}  ✉️ {email}\n\n"
            f"Potvrdit rezervaci: {confirm_url}\n"
            f"Zobrazit v adminu:  {admin_url}\n\n"
            f"Rezervace vytvořena {created_at_fmt}"
        )

        _send_email(NOTIFY_TO, subject, body_html, body_text, reply_to=email)

    except Exception:
        logging.exception('[EMAIL] Chyba při odesílání notifikace restauraci')


# ─── Email hostovi – čeká na potvrzení ────────────────────────────────────────

def _send_guest_pending_email(form, created_at_fmt):
    try:
        datum_fmt = _fmt_datum(form.get('datum', ''))
        cas       = form.get('cas', '')
        pocet     = form.get('pocet', '')
        jmeno     = form.get('jmeno', '')
        email     = form.get('email', '')
        lang      = form.get('lang', 'cs')

        if lang == 'en':
            subject    = 'Your reservation at Kozel u Bohemky'
            greeting   = f'Dear {jmeno},'
            body_p1    = 'thank you for your reservation, which is currently <strong>awaiting confirmation</strong>.<br>Give us a moment to check if we can confirm it for you.'
            detail_lbl = 'Your reservation details:'
        else:
            subject    = 'Vaše rezervace do Kozla u Bohemky'
            greeting   = f'Dobrý den, {jmeno},'
            body_p1    = 'děkujeme za Vaši rezervaci, která zatím <strong>čeká na potvrzení</strong>.<br>Dejte nám okamžik, ať zkontrolujeme, jestli Vám ji můžeme potvrdit.'
            detail_lbl = 'Detail Vaší rezervace:'

        body_html = f"""
        <html>{_email_head()}<body style="font-family:{_FONT};color:#333;max-width:600px;margin:0 auto;padding:24px;text-align:left">
          <p style="font-size:15px;line-height:1.6;margin:0 0 12px">{greeting}</p>
          <p style="font-size:15px;line-height:1.6;margin:0 0 12px">{body_p1}</p>
          <p style="font-size:14px;color:#555;margin:20px 0 4px"><strong>{detail_lbl}</strong></p>
          {_guest_detail_html(datum_fmt, cas, pocet, jmeno, lang=lang)}
          {_guest_footer_html(created_at_fmt, lang=lang)}
        </body></html>"""

        if lang == 'en':
            body_text = (
                f"Dear {jmeno},\n\n"
                f"thank you for your reservation, which is currently awaiting confirmation.\n"
                f"Give us a moment to check if we can confirm it for you.\n\n"
                f"Your reservation details:\n"
                f"Date & time: {datum_fmt} at {cas}\n"
                f"Guests: {_osob(pocet, lang='en')}\n"
                f"Name: {jmeno}\n\n"
                f"Kozel u Bohemky | Sportovní 848/24, 101 00 Prague 10 – Vršovice\n"
                f"kozelubohemky.cz | info@kozelubohemky.cz | (+420) 777 710 712\n\n"
                f"Reservation submitted {created_at_fmt}"
            )
        else:
            body_text = (
                f"Dobrý den, {jmeno},\n\n"
                f"děkujeme za Vaši rezervaci, která zatím čeká na potvrzení.\n"
                f"Dejte nám okamžik, ať zkontrolujeme, jestli Vám ji můžeme potvrdit.\n\n"
                f"Detail Vaší rezervace:\n"
                f"Datum a čas: {datum_fmt} od {cas}\n"
                f"Počet hostů: {_osob(pocet)}\n"
                f"Na jméno: {jmeno}\n\n"
                f"Kozel u Bohemky | Sportovní 848/24, 101 00 Praha 10 – Vršovice\n"
                f"kozelubohemky.cz | info@kozelubohemky.cz | (+420) 777 710 712\n\n"
                f"Rezervace vytvořena {created_at_fmt}"
            )

        _send_email(email, subject, body_html, body_text)

    except Exception:
        logging.exception('[EMAIL] Chyba při odesílání potvrzení hostu (pending)')


# ─── Email hostovi – potvrzení rezervace ──────────────────────────────────────

def _send_guest_confirmed_email(r):
    try:
        datum_fmt      = _fmt_datum(r['datum'])
        cas            = r['cas']
        pocet          = str(r['pocet'])
        jmeno          = r['jmeno']
        email          = r['email']
        lang           = r['lang'] if r['lang'] in ('cs', 'en') else 'cs'
        created_at_fmt = _fmt_created_at(r['created_at'])

        if lang == 'en':
            subject    = 'We confirm your reservation at Kozel u Bohemky'
            greeting   = f'Dear {jmeno},'
            body_p1    = 'thank you for your reservation, which we hereby <strong>confirm</strong>.<br>We look forward to your visit.'
            body_p2    = 'We kindly ask that if you find you cannot make it, or will be significantly delayed, please let us know.'
            detail_lbl = 'Your reservation details:'
        else:
            subject    = 'Potvrzujeme Vaši rezervaci do Kozla u Bohemky'
            greeting   = f'Dobrý den, {jmeno},'
            body_p1    = 'děkujeme za Vaši rezervaci, kterou tímto <strong>potvrzujeme</strong>.<br>Budeme se těšit na Vaši návštěvu.'
            body_p2    = 'Současně Vás žádáme, pokud zjistíte, že nebudete moci dorazit či budete mít výraznější zpoždění, abyste nás o tom informovali.'
            detail_lbl = 'Detail Vaší rezervace:'

        body_html = f"""
        <html>{_email_head()}<body style="font-family:{_FONT};color:#333;max-width:600px;margin:0 auto;padding:24px;text-align:left">
          <p style="font-size:15px;line-height:1.6;margin:0 0 12px">{greeting}</p>
          <p style="font-size:15px;line-height:1.6;margin:0 0 12px">{body_p1}</p>
          <p style="font-size:15px;line-height:1.6;margin:0 0 12px">{body_p2}</p>
          <p style="font-size:14px;color:#555;margin:20px 0 4px"><strong>{detail_lbl}</strong></p>
          {_guest_detail_html(datum_fmt, cas, pocet, jmeno, lang=lang)}
          {_guest_footer_html(created_at_fmt, lang=lang)}
        </body></html>"""

        if lang == 'en':
            body_text = (
                f"Dear {jmeno},\n\n"
                f"thank you for your reservation, which we hereby confirm.\n"
                f"We look forward to your visit.\n\n"
                f"We kindly ask that if you find you cannot make it, or will be significantly delayed, please let us know.\n\n"
                f"Your reservation details:\n"
                f"Date & time: {datum_fmt} at {cas}\n"
                f"Guests: {_osob(pocet, lang='en')}\n"
                f"Name: {jmeno}\n\n"
                f"Kozel u Bohemky | Sportovní 848/24, 101 00 Prague 10 – Vršovice\n"
                f"kozelubohemky.cz | info@kozelubohemky.cz | (+420) 777 710 712\n\n"
                f"Reservation submitted {created_at_fmt}"
            )
        else:
            body_text = (
                f"Dobrý den, {jmeno},\n\n"
                f"děkujeme za Vaši rezervaci, kterou tímto potvrzujeme.\n"
                f"Budeme se těšit na Vaši návštěvu.\n\n"
                f"Současně Vás žádáme, pokud zjistíte, že nebudete moci dorazit\n"
                f"či budete mít výraznější zpoždění, abyste nás o tom informovali.\n\n"
                f"Detail Vaší rezervace:\n"
                f"Datum a čas: {datum_fmt} od {cas}\n"
                f"Počet hostů: {_osob(pocet)}\n"
                f"Na jméno: {jmeno}\n\n"
                f"Kozel u Bohemky | Sportovní 848/24, 101 00 Praha 10 – Vršovice\n"
                f"kozelubohemky.cz | info@kozelubohemky.cz | (+420) 777 710 712\n\n"
                f"Rezervace vytvořena {created_at_fmt}"
            )

        _send_email(email, subject, body_html, body_text)

    except Exception:
        logging.exception('[EMAIL] Chyba při odesílání potvrzení hostu (confirmed)')


# ─── Email hostovi – zamítnutí rezervace ──────────────────────────────────────

def _send_guest_cancelled_email(r):
    try:
        datum_fmt      = _fmt_datum(r['datum'])
        cas            = r['cas']
        pocet          = str(r['pocet'])
        jmeno          = r['jmeno']
        email          = r['email']
        lang           = r['lang'] if r['lang'] in ('cs', 'en') else 'cs'
        created_at_fmt = _fmt_created_at(r['created_at'])

        if lang == 'en':
            subject    = 'Your reservation at Kozel u Bohemky has been declined'
            greeting   = f'Dear {jmeno},'
            body_p1    = 'thank you for your interest in making a reservation. Unfortunately, we are unable to accommodate you at the requested time due to capacity constraints.'
            body_p2    = 'We hope to welcome you on another occasion.'
            detail_lbl = 'Your reservation details:'
        else:
            subject    = 'Vaše rezervace do Kozla u Bohemky byla zamítnuta'
            greeting   = f'Dobrý den, {jmeno},'
            body_p1    = 'děkujeme za zájem o rezervaci. Bohužel Vám v požadovaném termínu z kapacitních důvodů <strong>nemůžeme vyhovět</strong>.'
            body_p2    = 'Věříme, že i přesto nám v budoucnu zachováte přízeň.'
            detail_lbl = 'Detail Vaší rezervace:'

        body_html = f"""
        <html>{_email_head()}<body style="font-family:{_FONT};color:#333;max-width:600px;margin:0 auto;padding:24px;text-align:left">
          <p style="font-size:15px;line-height:1.6;margin:0 0 12px">{greeting}</p>
          <p style="font-size:15px;line-height:1.6;margin:0 0 12px">{body_p1}</p>
          <p style="font-size:15px;line-height:1.6;margin:0 0 12px">{body_p2}</p>
          <p style="font-size:14px;color:#555;margin:20px 0 4px"><strong>{detail_lbl}</strong></p>
          {_guest_detail_html(datum_fmt, cas, pocet, jmeno, lang=lang)}
          {_guest_footer_html(created_at_fmt, lang=lang)}
        </body></html>"""

        if lang == 'en':
            body_text = (
                f"Dear {jmeno},\n\n"
                f"thank you for your interest in making a reservation. Unfortunately,\n"
                f"we are unable to accommodate you at the requested time due to capacity constraints.\n\n"
                f"We hope to welcome you on another occasion.\n\n"
                f"Your reservation details:\n"
                f"Date & time: {datum_fmt} at {cas}\n"
                f"Guests: {_osob(pocet, lang='en')}\n"
                f"Name: {jmeno}\n\n"
                f"Kozel u Bohemky | Sportovní 848/24, 101 00 Prague 10 – Vršovice\n"
                f"kozelubohemky.cz | info@kozelubohemky.cz | (+420) 777 710 712\n\n"
                f"Reservation submitted {created_at_fmt}"
            )
        else:
            body_text = (
                f"Dobrý den, {jmeno},\n\n"
                f"děkujeme za zájem o rezervaci. Bohužel Vám v požadovaném termínu\n"
                f"z kapacitních důvodů nemůžeme vyhovět.\n\n"
                f"Věříme, že i přesto nám v budoucnu zachováte přízeň.\n\n"
                f"Detail Vaší rezervace:\n"
                f"Datum a čas: {datum_fmt} od {cas}\n"
                f"Počet hostů: {_osob(pocet)}\n"
                f"Na jméno: {jmeno}\n\n"
                f"Kozel u Bohemky | Sportovní 848/24, 101 00 Praha 10 – Vršovice\n"
                f"kozelubohemky.cz | info@kozelubohemky.cz | (+420) 777 710 712\n\n"
                f"Rezervace vytvořena {created_at_fmt}"
            )

        _send_email(email, subject, body_html, body_text)

    except Exception:
        logging.exception('[EMAIL] Chyba při odesílání zamítnutí hostu')


@app.template_filter('fmt_dt')
def fmt_dt_filter(value):
    """Formátuje 'YYYY-MM-DD HH:MM' na 'D. M. YYYY HH:MM'."""
    if not value:
        return ''
    try:
        parts = str(value).strip().split(' ')
        d_part = parts[0].split('-')
        t_part = parts[1] if len(parts) > 1 else ''
        result = f'{int(d_part[2])}. {int(d_part[1])}. {d_part[0]}'
        if t_part:
            result += f' {t_part}'
        return result
    except Exception:
        return value




def _load_sections(conn, menu):
    sections = []
    if menu:
        sec_rows = conn.execute(
            'SELECT * FROM menu_sections WHERE menu_id = ? ORDER BY position',
            (menu['id'],)
        ).fetchall()
        for sec in sec_rows:
            dishes = conn.execute(
                'SELECT * FROM menu_items WHERE section_id = ? ORDER BY position',
                (sec['id'],)
            ).fetchall()
            sections.append({'id': sec['id'], 'title': sec['title'], 'dishes': dishes})
    return sections


def get_menu_for_date(d):
    conn = get_db()
    menu = conn.execute('SELECT * FROM daily_menu WHERE date = ?', (d,)).fetchone()
    sections = _load_sections(conn, menu)
    conn.close()
    return menu, sections


def get_latest_menu():
    """Vrátí naposledy uloženou nabídku (podle created_at), která má aspoň jednu sekci."""
    conn = get_db()
    menu = conn.execute('''
        SELECT dm.* FROM daily_menu dm
        WHERE EXISTS (SELECT 1 FROM menu_sections ms WHERE ms.menu_id = dm.id)
        ORDER BY dm.created_at DESC LIMIT 1
    ''').fetchone()
    sections = _load_sections(conn, menu)
    conn.close()
    return menu, sections


def _day_cs(iso_date=None):
    days = ['Pondělí', 'Úterý', 'Středa', 'Čtvrtek', 'Pátek', 'Sobota', 'Neděle']
    d = date.fromisoformat(iso_date) if iso_date else date.today()
    return days[d.weekday()]

def _fmt_date(iso_date):
    """Převede YYYY-MM-DD na český formát, např. 5. 5."""
    try:
        d = date.fromisoformat(iso_date)
        return f'{d.day}. {d.month}.'
    except Exception:
        return iso_date


# ─── Veřejná stránka ─────────────────────────────────────────────────────────

@app.route('/jidelni-listek')
def jidelni_listek():
    info = get_info()
    return render_template('jidelni_listek.html', info=info)


@app.route('/napojovy-listek')
def napojovy_listek():
    info = get_info()
    return render_template('napojovy_listek.html', info=info)


@app.route('/kontakt')
def kontakt():
    info = get_info()
    return render_template('kontakt.html', info=info)


@app.route('/rezervace', methods=['GET', 'POST'])
def rezervace():
    info = get_info()
    # Časy od 11:00 do 22:00, po 30 minutách
    times = []
    for h in range(11, 22):
        times.append(f'{h:02d}:00')
        times.append(f'{h:02d}:30')
    times.append('22:00')

    from datetime import date as _date
    min_date = _date.today().isoformat()
    success = False
    form = {}
    error = None

    if request.method == 'POST':
        lang = request.form.get('lang', 'cs')
        if lang not in ('cs', 'en'):
            lang = 'cs'
        form = {
            'datum':   request.form.get('datum', '').strip(),
            'cas':     request.form.get('cas', '').strip(),
            'pocet':   request.form.get('pocet', '').strip(),
            'jmeno':   request.form.get('jmeno', '').strip(),
            'email':   request.form.get('email', '').strip(),
            'telefon': request.form.get('telefon', '').strip(),
            'zprava':  request.form.get('zprava', '').strip(),
            'lang':    lang,
        }
        required = ['datum', 'cas', 'pocet', 'jmeno', 'email', 'telefon']
        if all(form.get(k) for k in required):
            try:
                conn = get_db()
                try:
                    cur = conn.execute(
                        '''INSERT INTO reservations (datum, cas, pocet, jmeno, email, telefon, zprava, lang)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                        (form['datum'], form['cas'], int(form['pocet']),
                         form['jmeno'], form['email'], form['telefon'], form['zprava'] or None, lang)
                    )
                except Exception:
                    # Fallback: lang sloupec ještě neexistuje – zkus bez něj
                    logging.exception('INSERT s lang selhal, zkouším bez lang')
                    cur = conn.execute(
                        '''INSERT INTO reservations (datum, cas, pocet, jmeno, email, telefon, zprava)
                           VALUES (?, ?, ?, ?, ?, ?, ?)''',
                        (form['datum'], form['cas'], int(form['pocet']),
                         form['jmeno'], form['email'], form['telefon'], form['zprava'] or None)
                    )
                new_rid = cur.lastrowid
                conn.commit()
                conn.close()
                created_at_fmt = datetime.now().strftime('%-d. %-m. %Y %H:%M')
                _send_reservation_email(form, new_rid, created_at_fmt)
                _send_guest_pending_email(form, created_at_fmt)
                success = True
                form = {}
            except Exception:
                logging.exception('Chyba při ukládání rezervace')
                error = 'Omlouváme se, nastala technická chyba. Zkuste to prosím znovu.'
        else:
            error = 'Vyplňte prosím všechna povinná pole.'

    return render_template('rezervace.html', info=info, times=times,
                           min_date=min_date, success=success, form=form, error=error)


@app.route('/fotogalerie')
def fotogalerie():
    import glob as glob_module
    info = get_info()
    static = os.path.join(app.root_path, 'static', 'fotogalerie')
    EXCLUDE = {'MENU_KOZEL U BOHEMKY_DUBEN 2025_15.webp'}
    def get_photos(folder):
        files = sorted(glob_module.glob(os.path.join(static, folder, '*.webp')))
        return [f'fotogalerie/{folder}/{os.path.basename(f)}' for f in files
                if os.path.basename(f) not in EXCLUDE]
    interier = get_photos('interier')
    jidla    = get_photos('jidla')
    return render_template('fotogalerie.html', info=info, interier=interier, jidla=jidla)


@app.route('/')
def index():
    today = date.today().isoformat()
    menu, sections = get_latest_menu()
    info = get_info()
    popup, popup_items = get_active_popup()
    display_date = menu['date'] if menu else today
    return render_template('index.html',
                           menu=menu, sections=sections, info=info,
                           today=today, today_fmt=_fmt_date(display_date),
                           day_cs=_day_cs(display_date),
                           active_popup=popup, active_popup_items=popup_items)


# ─── Admin – přihlášení ───────────────────────────────────────────────────────

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        conn = get_db()
        user = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        conn.close()
        if user and check_password_hash(user['password_hash'], password):
            session['admin'] = True
            session['admin_username'] = user['username']
            return redirect(url_for('admin'))
        error = 'Špatné uživatelské jméno nebo heslo.'
    return render_template('admin_login.html', error=error)


@app.route('/admin/logout')
def admin_logout():
    session.pop('admin', None)
    session.pop('admin_username', None)
    return redirect(url_for('index'))


# ─── Admin – nabídka ─────────────────────────────────────────────────────────

@app.route('/admin', methods=['GET', 'POST'])
def admin():
    if not session.get('admin'):
        return redirect(url_for('admin_login'))

    today = date.today().isoformat()
    info = get_info()
    message = None

    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'save_menu':
            menu_date     = request.form.get('menu_date', today)
            menu_data_raw = request.form.get('menu_data', '{}')
            try:
                menu_data_obj = json.loads(menu_data_raw)
            except Exception:
                menu_data_obj = {}
            sections_data = menu_data_obj.get('sections', [])
            promo_items   = [p.strip() for p in menu_data_obj.get('promo_items', []) if p.strip()]
            promo_text    = '\n'.join(promo_items)

            saved_by = session.get('admin_username', 'admin')
            saved_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            conn = get_db()
            conn.execute('DELETE FROM daily_menu WHERE date = ?', (menu_date,))
            cur = conn.execute(
                'INSERT INTO daily_menu (date, promo_text, updated_by, created_at) VALUES (?, ?, ?, ?)',
                (menu_date, promo_text, saved_by, saved_at)
            )
            menu_id = cur.lastrowid

            for si, section in enumerate(sections_data):
                title = section.get('title', '').strip()
                items = section.get('items', [])
                if not title and not items:
                    continue
                cur2 = conn.execute(
                    'INSERT INTO menu_sections (menu_id, title, position) VALUES (?, ?, ?)',
                    (menu_id, title, si)
                )
                section_id = cur2.lastrowid
                for ii, item in enumerate(items):
                    name = item.get('name', '').strip()
                    if not name:
                        continue
                    conn.execute(
                        'INSERT INTO menu_items (section_id, portion, name, price, position) VALUES (?, ?, ?, ?, ?)',
                        (section_id, item.get('portion', '').strip(), name,
                         item.get('price', '').strip(), ii)
                    )
            conn.commit()
            conn.close()
            session['admin_msg'] = 'ok:Nabídka byla uložena ✓'
            return redirect(url_for('admin'))

    # Přečti a smaž flash zprávu
    raw_msg = session.pop('admin_msg', None)
    message = tuple(raw_msg.split(':', 1)) if raw_msg else None

    menu, sections = get_menu_for_date(today)

    # Pokud pro dnešek nebyla zadána nabídka, předvyplň formulář
    # z naposledy uložené nabídky (zachová data bez ohledu na datum).
    if menu:
        prefill_src, prefill_secs = menu, sections
    else:
        prefill_src, prefill_secs = get_latest_menu()

    prefill_sections = [
        {'title': s['title'],
         'items': [{'portion': i['portion'] or '', 'name': i['name'], 'price': i['price'] or ''}
                   for i in s['dishes']]}
        for s in prefill_secs
    ]
    prefill_promo = (prefill_src['promo_text'] or '').split('\n') if prefill_src and prefill_src['promo_text'] else []

    # Info o poslední změně (z naposledy uložené nabídky)
    last_menu, _ = get_latest_menu()
    last_change = None
    if last_menu and last_menu['updated_by']:
        raw_dt = last_menu['created_at'] or ''
        # Formát z SQLite: "2026-05-06 14:23:01"
        try:
            dt_part = raw_dt[:16]  # "2026-05-06 14:23"
            d_part, t_part = dt_part.split(' ')
            y, m, day = d_part.split('-')
            last_change = {
                'by': last_menu['updated_by'],
                'at': f'{int(day)}. {int(m)}. {y} {t_part}',
            }
        except Exception:
            pass

    conn2 = get_db()
    pending_count = conn2.execute(
        "SELECT COUNT(*) FROM reservations WHERE status = 'pending' OR status IS NULL"
    ).fetchone()[0]
    conn2.close()

    return render_template('admin.html',
                           menu=menu, sections=sections,
                           prefill_json=json.dumps(prefill_sections, ensure_ascii=False),
                           prefill_promo_json=json.dumps(prefill_promo, ensure_ascii=False),
                           info=info, today=today, message=message,
                           last_change=last_change,
                           pending_count=pending_count)


# ─── Admin – správa uživatelů ────────────────────────────────────────────────

@app.route('/admin/users', methods=['GET', 'POST'])
def admin_users():
    if not session.get('admin'):
        return redirect(url_for('admin_login'))

    message = None

    if request.method == 'POST' and request.form.get('action') == 'change_password':
        current_pw  = request.form.get('current_password', '')
        new_pw      = request.form.get('new_password', '')
        confirm_pw  = request.form.get('confirm_password', '')
        username    = session.get('admin_username', '')

        conn = get_db()
        row  = conn.execute('SELECT id, password_hash FROM users WHERE username = ?', (username,)).fetchone()

        if not row or not check_password_hash(row['password_hash'], current_pw):
            message = ('error', 'Současné heslo není správné.')
        elif len(new_pw) < 6:
            message = ('error', 'Nové heslo musí mít aspoň 6 znaků.')
        elif new_pw != confirm_pw:
            message = ('error', 'Hesla se neshodují.')
        else:
            conn.execute('UPDATE users SET password_hash = ? WHERE id = ?',
                         (generate_password_hash(new_pw), row['id']))
            conn.commit()
            message = ('ok', 'Heslo bylo úspěšně změněno.')

        conn.close()

    return render_template('admin_users.html',
                           message=message,
                           current_username=session.get('admin_username', ''))


# ─── Admin – popupy ──────────────────────────────────────────────────────────

POPUP_IMG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'popup_images')

def _save_popup_image(file_storage):
    """Uloží nahraný soubor do static/popup_images/ a vrátí název souboru."""
    import uuid
    from werkzeug.utils import secure_filename
    ext = os.path.splitext(secure_filename(file_storage.filename))[1].lower()
    if ext not in ('.jpg', '.jpeg', '.png', '.webp', '.gif'):
        return None
    fname = f'{uuid.uuid4().hex}{ext}'
    os.makedirs(POPUP_IMG_DIR, exist_ok=True)
    file_storage.save(os.path.join(POPUP_IMG_DIR, fname))
    return fname


def _load_popup_items(conn, popup_id):
    return conn.execute(
        'SELECT * FROM popup_items WHERE popup_id = ? ORDER BY position',
        (popup_id,)
    ).fetchall()


@app.route('/admin/popup', methods=['GET', 'POST'])
def admin_popup():
    if not session.get('admin'):
        return redirect(url_for('admin_login'))

    message = None

    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'create_popup':
            title      = request.form.get('title', '').strip()
            body       = request.form.get('body', '').strip()
            expires_d  = request.form.get('expires_date', '').strip()
            expires_t  = request.form.get('expires_time', '').strip()
            expires_at = f'{expires_d} {expires_t}' if expires_d and expires_t else ''
            starts_d   = request.form.get('starts_date', '').strip()
            starts_t   = request.form.get('starts_time', '').strip()
            starts_at  = f'{starts_d} {starts_t}' if starts_d and starts_t else None
            items_raw  = request.form.get('items_json', '[]')
            try:
                items_data = json.loads(items_raw)
            except Exception:
                items_data = []

            if not title or not expires_at:
                message = ('error', 'Vyplňte název a datum platnosti.')
            else:
                image = None
                f = request.files.get('image')
                if f and f.filename:
                    image = _save_popup_image(f)

                created_by = session.get('admin_username', 'admin')
                conn = get_db()
                cur = conn.execute(
                    'INSERT INTO popups (title, body, starts_at, expires_at, image, is_active, created_by) VALUES (?, ?, ?, ?, ?, 1, ?)',
                    (title, body or None, starts_at, expires_at, image, created_by)
                )
                popup_id = cur.lastrowid
                for i, item in enumerate(items_data):
                    name = item.get('name', '').strip()
                    if not name:
                        continue
                    conn.execute(
                        'INSERT INTO popup_items (popup_id, portion, name, price, position) VALUES (?, ?, ?, ?, ?)',
                        (popup_id, item.get('portion', '').strip() or None,
                         name, item.get('price', '').strip() or None, i)
                    )
                conn.commit()
                conn.close()
                message = ('ok', 'Popup byl uložen.')

        elif action == 'toggle_popup':
            pid = request.form.get('popup_id')
            conn = get_db()
            conn.execute('UPDATE popups SET is_active = 1 - is_active WHERE id = ?', (pid,))
            conn.commit()
            conn.close()
            return redirect(url_for('admin_popup'))

        elif action == 'delete_popup':
            pid = request.form.get('popup_id')
            conn = get_db()
            # Smaž obrázek pokud existuje
            row = conn.execute('SELECT image FROM popups WHERE id = ?', (pid,)).fetchone()
            if row and row['image']:
                try:
                    os.remove(os.path.join(POPUP_IMG_DIR, row['image']))
                except Exception:
                    pass
            conn.execute('DELETE FROM popups WHERE id = ?', (pid,))
            conn.commit()
            conn.close()
            return redirect(url_for('admin_popup'))

    conn = get_db()
    popups = conn.execute('SELECT * FROM popups ORDER BY created_at DESC').fetchall()
    popup_list = []
    for p in popups:
        items = _load_popup_items(conn, p['id'])
        popup_list.append({'popup': p, 'dishes': items})
    conn.close()

    now_str = datetime.now().strftime('%Y-%m-%d %H:%M')
    return render_template('admin_popup.html', popup_list=popup_list,
                           message=message, now_str=now_str)


@app.route('/admin/popup/<int:popup_id>/edit', methods=['GET', 'POST'])
def admin_popup_edit(popup_id):
    if not session.get('admin'):
        return redirect(url_for('admin_login'))

    conn = get_db()
    popup = conn.execute('SELECT * FROM popups WHERE id = ?', (popup_id,)).fetchone()
    if not popup:
        conn.close()
        return redirect(url_for('admin_popup'))

    message = None

    if request.method == 'POST':
        title      = request.form.get('title', '').strip()
        body       = request.form.get('body', '').strip()
        expires_d  = request.form.get('expires_date', '').strip()
        expires_t  = request.form.get('expires_time', '').strip()
        expires_at = f'{expires_d} {expires_t}' if expires_d and expires_t else ''
        starts_d   = request.form.get('starts_date', '').strip()
        starts_t   = request.form.get('starts_time', '').strip()
        starts_at  = f'{starts_d} {starts_t}' if starts_d and starts_t else None
        items_raw  = request.form.get('items_json', '[]')
        try:
            items_data = json.loads(items_raw)
        except Exception:
            items_data = []

        if not title or not expires_at:
            message = ('error', 'Vyplňte název a datum platnosti.')
        else:
            image = popup['image']
            f = request.files.get('image')
            if f and f.filename:
                # Smaž starý
                if image:
                    try:
                        os.remove(os.path.join(POPUP_IMG_DIR, image))
                    except Exception:
                        pass
                image = _save_popup_image(f)

            conn.execute(
                'UPDATE popups SET title=?, body=?, starts_at=?, expires_at=?, image=? WHERE id=?',
                (title, body or None, starts_at, expires_at, image, popup_id)
            )
            conn.execute('DELETE FROM popup_items WHERE popup_id = ?', (popup_id,))
            for i, item in enumerate(items_data):
                name = item.get('name', '').strip()
                if not name:
                    continue
                conn.execute(
                    'INSERT INTO popup_items (popup_id, portion, name, price, position) VALUES (?, ?, ?, ?, ?)',
                    (popup_id, item.get('portion', '').strip() or None,
                     name, item.get('price', '').strip() or None, i)
                )
            conn.commit()
            popup = conn.execute('SELECT * FROM popups WHERE id = ?', (popup_id,)).fetchone()
            message = ('ok', 'Popup byl upraven.')

    items = _load_popup_items(conn, popup_id)
    conn.close()
    items_json = json.dumps(
        [{'portion': i['portion'] or '', 'name': i['name'], 'price': i['price'] or ''}
         for i in items],
        ensure_ascii=False
    )
    return render_template('admin_popup_edit.html', popup=popup, items=items,
                           items_json=items_json, message=message)


# ─── Admin – rezervace ───────────────────────────────────────────────────────

@app.route('/admin/rezervace', methods=['GET', 'POST'])
def admin_rezervace():
    if not session.get('admin'):
        return redirect(url_for('admin_login'))

    message = None

    if request.method == 'POST':
        action = request.form.get('action')
        rid    = request.form.get('reservation_id')
        conn   = get_db()

        if action == 'set_status':
            new_status = request.form.get('status', 'pending')
            if new_status in ('pending', 'confirmed', 'cancelled'):
                r = conn.execute('SELECT * FROM reservations WHERE id = ?', (rid,)).fetchone()
                conn.execute('UPDATE reservations SET status = ? WHERE id = ?', (new_status, rid))
                conn.commit()
                if r and r['status'] != new_status:
                    if new_status == 'confirmed':
                        _send_guest_confirmed_email(r)
                    elif new_status == 'cancelled':
                        _send_guest_cancelled_email(r)
        elif action == 'delete_reservation':
            conn.execute('DELETE FROM reservations WHERE id = ?', (rid,))
            conn.commit()
            message = ('ok', 'Rezervace byla smazána.')

        conn.close()
        if not message:
            return redirect(url_for('admin_rezervace'))

    filter_status = request.args.get('status', '')
    conn = get_db()
    if filter_status:
        rows = conn.execute(
            'SELECT * FROM reservations WHERE status = ? ORDER BY datum DESC, cas DESC',
            (filter_status,)
        ).fetchall()
    else:
        rows = conn.execute(
            'SELECT * FROM reservations ORDER BY datum DESC, cas DESC'
        ).fetchall()
    conn.close()

    return render_template('admin_rezervace.html',
                           reservations=rows, message=message,
                           filter_status=filter_status)


# ─── One-click potvrzení rezervace z emailu ───────────────────────────────────

@app.route('/r/confirm/<int:rid>/<token>')
def confirm_reservation(rid, token):
    if not _verify_confirm_token(rid, token):
        return '<p style="font-family:Arial;text-align:center;margin-top:60px;color:#c00">Neplatný nebo vypršelý odkaz.</p>', 403

    conn = get_db()
    r = conn.execute('SELECT * FROM reservations WHERE id = ?', (rid,)).fetchone()
    if not r:
        conn.close()
        return '<p style="font-family:Arial;text-align:center;margin-top:60px;color:#c00">Rezervace nenalezena.</p>', 404

    if r['status'] != 'confirmed':
        conn.execute("UPDATE reservations SET status = 'confirmed' WHERE id = ?", (rid,))
        conn.commit()
        _send_guest_confirmed_email(r)

    already = r['status'] == 'confirmed'
    conn.close()
    datum_fmt = _fmt_datum(r['datum'])
    admin_url = url_for('admin_rezervace')
    already_note = '<p class="already-note">Tato rezervace již byla potvrzena dříve.</p>' if already else ''
    return f"""
    <html><head>
      <meta charset="UTF-8">
      <meta name="viewport" content="width=device-width,initial-scale=1">
      <title>Rezervace potvrzena</title>
      <link href="https://fonts.googleapis.com/css2?family=Exo+2:wght@400;600;700&display=swap" rel="stylesheet">
      <script>
        (function(){{
          var stored = localStorage.getItem('admin_theme');
          var prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
          if (stored === 'dark' || (!stored && prefersDark)) {{
            document.documentElement.setAttribute('data-theme', 'dark');
          }}
        }})();
      </script>
      <style>
        *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
        :root {{
          --bg-card: #ffffff;
          --color-text: #333333;
          --color-muted: #888888;
          --color-detail-bg: #f9f6f0;
          --color-border: #e8e8e8;
          --shadow: 0 4px 32px rgba(0,0,0,.10);
        }}
        [data-theme="dark"] {{
          --bg-card: #1e1e1e;
          --color-text: #e5e5e5;
          --color-muted: #999999;
          --color-detail-bg: #2a2a2a;
          --color-border: #3a3a3a;
          --shadow: 0 4px 32px rgba(0,0,0,.4);
        }}
        body {{
          font-family: 'Exo 2', Arial, sans-serif;
          background: url('/static/admin-bg.webp') center/cover no-repeat fixed;
          min-height: 100vh;
          display: flex;
          align-items: center;
          justify-content: center;
          padding: 24px;
          color: var(--color-text);
        }}
        .card {{
          background: var(--bg-card);
          border-radius: 14px;
          box-shadow: var(--shadow);
          padding: 48px 40px;
          max-width: 460px;
          width: 100%;
          text-align: center;
        }}
        .icon {{
          font-size: 48px;
          font-weight: 700;
          color: var(--color-text);
          margin-bottom: 16px;
          line-height: 1;
        }}
        h1 {{
          font-size: 1.45rem;
          font-weight: 700;
          color: #9f854d;
          margin-bottom: 20px;
        }}
        .already-note {{
          font-size: 13px;
          color: var(--color-muted);
          margin-bottom: 12px;
        }}
        .detail {{
          background: var(--color-detail-bg);
          border: 1px solid var(--color-border);
          border-radius: 8px;
          padding: 16px 20px;
          margin: 20px 0 28px;
          text-align: center;
          font-size: 14px;
          line-height: 1;
        }}
        .detail-row {{
          padding: 10px 0;
          border-bottom: 1px solid var(--color-border);
        }}
        .detail-row:last-child {{ border-bottom: none; }}
        .detail-label {{
          display: block;
          color: var(--color-muted);
          font-size: 11px;
          text-transform: uppercase;
          letter-spacing: .06em;
          margin-bottom: 3px;
        }}
        .detail-val {{ display: block; font-weight: 600; font-size: 15px; }}
        .btn {{
          display: inline-block;
          background: #9f854d;
          color: #fff;
          text-decoration: none;
          padding: 12px 28px;
          border-radius: 8px;
          font-family: 'Exo 2', Arial, sans-serif;
          font-weight: 700;
          font-size: 15px;
          transition: opacity .15s;
        }}
        .btn:hover {{ opacity: .85; }}
        .note {{ font-size: 13px; color: var(--color-muted); margin-top: 20px; }}
      </style>
    </head>
    <body>
      <div class="card">
        <div class="icon">✓</div>
        <h1>Rezervace potvrzena</h1>
        {already_note}
        <div class="detail">
          <div class="detail-row">
            <div class="detail-label">Datum a čas</div>
            <div class="detail-val">{datum_fmt} od {r['cas']}</div>
          </div>
          <div class="detail-row">
            <div class="detail-label">Pro</div>
            <div class="detail-val">{_osob(r['pocet'])}</div>
          </div>
          <div class="detail-row">
            <div class="detail-label">Na jméno</div>
            <div class="detail-val">{r['jmeno']}</div>
          </div>
        </div>
        <a href="{admin_url}" class="btn">Správa rezervací</a>
        <p class="note">Host byl informován potvrzovacím e-mailem.</p>
      </div>
    </body></html>"""


# ─── Export PDF ───────────────────────────────────────────────────────────────

@app.route('/admin/export/pdf')
def export_pdf():
    if not session.get('admin'):
        return redirect(url_for('admin_login'))
    menu, sections = get_latest_menu()
    if not sections:
        return '<p>Není zadaná žádná nabídka.</p>', 404
    info = get_info()
    d = menu['date']
    pdf_bytes = _make_pdf(menu, sections, info, _fmt_date(d), _day_cs(d))
    return send_file(
        io.BytesIO(pdf_bytes), mimetype='application/pdf',
        as_attachment=True, download_name=f'nabidka_{d}.pdf'
    )


# ─── Export JPG ───────────────────────────────────────────────────────────────

@app.route('/admin/export/jpg')
def export_jpg():
    if not session.get('admin'):
        return redirect(url_for('admin_login'))
    menu, sections = get_latest_menu()
    if not sections:
        return '<p>Není zadaná žádná nabídka.</p>', 404
    info = get_info()
    d = menu['date']
    jpg_bytes = _make_jpg(menu, sections, info, _fmt_date(d), _day_cs(d))
    return send_file(
        io.BytesIO(jpg_bytes), mimetype='image/jpeg',
        as_attachment=True, download_name=f'nabidka_{d}.jpg'
    )


# ─── Footer border → PIL Image ───────────────────────────────────────────────

def _footer_border_pil(variant='jpg'):
    """Načte border-jpg.png nebo border-pdf.png a vrátí PIL Image (RGBA)."""
    try:
        from PIL import Image as PILImage
        fname = 'border-jpg.png' if variant == 'jpg' else 'border-pdf.png'
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', fname)
        return PILImage.open(path).convert('RGBA')
    except Exception as e:
        print(f'Footer border load error: {e}')
        return None


# ─── Logo → PIL Image ────────────────────────────────────────────────────────

def _logo_pil(width_px):
    """Načte logo.png a vrátí PIL Image o dané šířce px. Vrátí None při chybě."""
    try:
        from PIL import Image as PILImage
        png_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'logo.png')
        logo = PILImage.open(png_path).convert('RGBA')
        ratio = width_px / logo.width
        new_h = int(logo.height * ratio)
        return logo.resize((width_px, new_h), PILImage.LANCZOS)
    except Exception as e:
        print(f'Logo load error: {e}')
        return None


# ─── Generování PDF ──────────────────────────────────────────────────────────

def _make_pdf(menu, sections, info, today, day_cs):
    from fpdf import FPDF
    from PIL import Image as PILImage

    ACCENT = (159, 133, 77)
    MUTED  = (107, 114, 128)
    DARK   = (51, 51, 51)

    pdf = FPDF(orientation='P', unit='mm', format='A4')
    pdf.set_margins(20, 20, 20)
    pdf.add_page()
    pdf.add_font('DV',  fname=_font_path(bold=False))
    pdf.add_font('DVB', fname=_font_path(bold=True))

    W = pdf.w - 40  # využitelná šířka

    # ── Logo ──
    logo_w_mm = W * 0.5
    logo = _logo_pil(width_px=int(800 * 0.5))
    if logo:
        logo_bg = PILImage.new('RGB', logo.size, (255, 255, 255))
        logo_bg.paste(logo, mask=logo.split()[3])
        buf = io.BytesIO()
        logo_bg.save(buf, 'PNG')
        buf.seek(0)
        logo_h_mm = logo_w_mm * logo.height / logo.width
        logo_x = 20 + (W - logo_w_mm) / 2
        pdf.image(buf, x=logo_x, y=pdf.get_y(), w=logo_w_mm, h=logo_h_mm)
        pdf.ln(logo_h_mm + 12)
    else:
        pdf.set_font('DVB', size=20)
        pdf.set_text_color(*DARK)
        pdf.cell(W, 10, info.get('name', 'Restaurace'), new_x='LMARGIN', new_y='NEXT', align='C')
        pdf.ln(2)

    # ── Podtitulek ──
    header_line = f'POLEDNÍ NABÍDKA {day_cs.upper()} {today}'
    pdf.set_font('DVB', size=13)
    pdf.set_text_color(*DARK)
    pdf.cell(W, 8, header_line, new_x='LMARGIN', new_y='NEXT', align='C')

    pdf.ln(6)

    # ── Sekce ──
    for section in sections:
        pdf.set_font('DVB', size=11)
        pdf.set_text_color(*DARK)
        pdf.cell(W, 6, section['title'].upper(), new_x='LMARGIN', new_y='NEXT')
        pdf.ln(1)

        for item in section['dishes']:
            portion   = item['portion'] or ''
            name      = item['name'] or ''
            price_str = f"{item['price']} Kč" if item['price'] else ''

            pdf.set_font('DV', size=10)
            pdf.set_text_color(*MUTED)
            pdf.cell(14, 6, portion)

            pdf.set_font('DV', size=11)
            pdf.set_text_color(*DARK)
            name_w = W - 14 - 28
            pdf.multi_cell(name_w, 6, name, align='L', new_x='RIGHT', new_y='LAST')

            pdf.set_font('DV', size=11)
            pdf.set_text_color(*DARK)
            pdf.cell(28, 6, price_str, align='R', new_x='LMARGIN', new_y='NEXT')

        pdf.ln(6)

    # ── Promo text ──
    if menu and menu['promo_text']:
        pdf.ln(3)
        pdf.set_font('DV', size=10)
        pdf.set_text_color(*MUTED)
        PORTION_W = 14
        pdf.cell(PORTION_W, 6, '')  # prázdná buňka jako odsazení (šířka gramáže)
        pdf.multi_cell(W - PORTION_W, 6, menu['promo_text'], align='L',
                       new_x='LMARGIN', new_y='NEXT')

    # ── Footer bordura ──
    border = _footer_border_pil(variant='pdf')
    if border:
        border_h_mm = round(border.height / border.width * W, 1)
        border_bg = PILImage.new('RGB', border.size, (255, 255, 255))
        border_bg.paste(border, mask=border.split()[3])
        buf_b = io.BytesIO()
        border_bg.save(buf_b, 'PNG')
        buf_b.seek(0)
        pdf.image(buf_b, x=20, y=pdf.h - border_h_mm - 10, w=W, h=border_h_mm)

    return bytes(pdf.output())


# ─── Generování JPG ──────────────────────────────────────────────────────────

def _make_jpg(menu, sections, info, today, day_cs):
    from PIL import Image, ImageDraw, ImageFont

    SIZE   = 1080
    PAD    = 58
    ACCENT = (159, 133, 77)
    BG     = (255, 255, 255)
    DARK   = (51, 51, 51)
    MUTED  = (107, 114, 128)
    BORDER = (232, 232, 232)

    def fnt(size, bold=False):
        try:
            return ImageFont.truetype(_font_path(bold=bold), size)
        except Exception:
            return ImageFont.load_default()

    img  = Image.new('RGB', (SIZE, SIZE), BG)
    draw = ImageDraw.Draw(img)

    y = PAD

    # ── Logo ──
    logo_w = int((SIZE - 2 * PAD) * 0.5)
    logo = _logo_pil(width_px=logo_w)
    if logo:
        logo_bg = Image.new('RGB', logo.size, BG)
        logo_bg.paste(logo, mask=logo.split()[3])
        logo_x = (SIZE - logo_w) // 2
        img.paste(logo_bg, (logo_x, y))
        y += logo.height + 60
    else:
        draw.text((SIZE // 2, y), info.get('name', 'Restaurace'),
                  font=fnt(46, bold=True), fill=DARK, anchor='mt')
        y += 60

    # ── Podtitulek ──
    header_line = f'POLEDNÍ NABÍDKA {day_cs.upper()} {today}'
    f_header = fnt(32, bold=True)
    draw.text((SIZE // 2, y), header_line, font=f_header, fill=DARK, anchor='mt')
    y += 80

    # Dynamická velikost písma podle počtu položek
    total = sum(len(s['dishes']) for s in sections)
    if total <= 7:
        fs_item, fs_sec, fs_por = 26, 24, 20
    elif total <= 11:
        fs_item, fs_sec, fs_por = 22, 20, 17
    else:
        fs_item, fs_sec, fs_por = 18, 17, 14

    line_h  = fs_item + 12
    sec_gap = 10

    f_sec   = fnt(fs_sec, bold=True)
    f_por   = fnt(fs_por)
    f_item  = fnt(fs_item)
    f_price = fnt(fs_item)   # normální tloušťka

    for section in sections:
        if y > SIZE - 120:
            break

        draw.text((PAD, y), section['title'].upper(), font=f_sec, fill=DARK)
        y += fs_sec + 10

        dishes = section['dishes']
        for idx, item in enumerate(dishes):
            if y > SIZE - 110:
                break

            portion   = item['portion'] or ''
            name      = item['name']    or ''
            price_str = f"{item['price']} Kč" if item['price'] else ''

            draw.text((PAD, y), portion, font=f_por, fill=MUTED)

            x_name = PAD + 75
            max_w  = SIZE - x_name - PAD - 160
            display = name
            while display and draw.textlength(display, font=f_item) > max_w:
                display = display[:-1]
            if display != name:
                display = display[:-2] + '…'
            draw.text((x_name, y), display, font=f_item, fill=DARK)

            if price_str:
                draw.text((SIZE - PAD, y), price_str,
                          font=f_price, fill=DARK, anchor='ra')

            y += line_h
            if idx < len(dishes) - 1:
                # tečkovaná čára
                x0, x1, ly = PAD + 95, SIZE - PAD, y - 4
                dash, gap = 4, 4
                xx = x0
                while xx < x1:
                    draw.line([(xx, ly), (min(xx + dash, x1), ly)], fill=BORDER, width=1)
                    xx += dash + gap

        y += sec_gap

    # ── Promo text ──
    if menu and menu['promo_text'] and y < SIZE - 150:
        f_promo = fnt(18)
        x_name  = PAD + 75
        y += 10
        for line in menu['promo_text'].split('\n'):
            line = line.strip()
            if not line:
                continue
            draw.text((x_name, y), line, font=f_promo, fill=MUTED)
            y += 32

    # ── Footer bordura ──
    try:
        border_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'kozel-border-md.png')
        border = Image.open(border_path).convert('RGBA')
        border_bg = Image.new('RGB', border.size, BG)
        border_bg.paste(border, mask=border.split()[3])
        img.paste(border_bg, (PAD, SIZE - border.height - PAD // 2))
    except Exception as e:
        print(f'Footer border error: {e}')

    buf = io.BytesIO()
    img.save(buf, 'JPEG', quality=93)
    return buf.getvalue()


# ─── Chybové stránky ─────────────────────────────────────────────────────────

@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_error(e):
    logging.exception('500 Internal Server Error')
    return render_template('500.html'), 500


# ─── SEO – robots.txt a sitemap.xml ──────────────────────────────────────────

@app.route('/robots.txt')
def robots_txt():
    content = (
        'User-agent: *\n'
        'Allow: /\n'
        'Disallow: /admin\n'
        'Disallow: /admin/\n'
        'Disallow: /r/\n'
        '\n'
        'Sitemap: https://kozelubohemky.cz/sitemap.xml\n'
    )
    return Response(content, mimetype='text/plain')

@app.route('/sitemap.xml')
def sitemap_xml():
    pages = [
        ('https://kozelubohemky.cz/',                  '1.0',  'daily'),
        ('https://kozelubohemky.cz/rezervace',          '0.9',  'weekly'),
        ('https://kozelubohemky.cz/jidelni-listek',     '0.8',  'weekly'),
        ('https://kozelubohemky.cz/napojovy-listek',    '0.7',  'monthly'),
        ('https://kozelubohemky.cz/fotogalerie',        '0.6',  'monthly'),
        ('https://kozelubohemky.cz/kontakt',            '0.6',  'monthly'),
    ]
    today = date.today().isoformat()
    xml = '<?xml version="1.0" encoding="UTF-8"?>\n'
    xml += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    for loc, priority, freq in pages:
        xml += (f'  <url>\n'
                f'    <loc>{loc}</loc>\n'
                f'    <lastmod>{today}</lastmod>\n'
                f'    <changefreq>{freq}</changefreq>\n'
                f'    <priority>{priority}</priority>\n'
                f'  </url>\n')
    xml += '</urlset>'
    return Response(xml, mimetype='application/xml')


# ─── Spuštění ─────────────────────────────────────────────────────────────────

init_db()
_ensure_fonts()

if __name__ == '__main__':
    app.run(debug=True)
