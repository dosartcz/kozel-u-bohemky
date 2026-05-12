# Kozel u Bohemky — Restaurační webová aplikace

Webová aplikace pro restauraci Kozel u Bohemky. Zahrnuje veřejný web (jídelní a nápojový lístek, rezervace, fotogalerie) a administrátorský panel pro správu denního menu, rezervací a obsahu webu.

---

## Funkce

**Veřejná část**
- Jídelní a nápojový lístek (statické stránky)
- Denní menu s automatickým zobrazením aktuálního dne
- Online rezervační formulář s e-mailovým potvrzením
- Fotogalerie
- Kontaktní stránka s informacemi o restauraci
- Popup oznámení s nastavitelnou dobou platnosti
- `robots.txt` a `sitemap.xml`

**Administrace (`/admin`)**
- Přihlášení se jménem a heslem (Werkzeug hash)
- Správa denního menu — vytváření sekcí a položek, promo text
- Export menu jako **PDF** a **JPG** (fonty Exo 2, generování přes fpdf2 + Pillow/cairosvg)
- Správa rezervací — přehled, změna stavu (pending / confirmed / cancelled)
- Správa popupů — vytvoření, aktivace, nahrání obrázku, datum platnosti
- Správa uživatelů administrace
- Nastavení informací o restauraci (název, adresa, telefon, e-mail, otevírací hodiny)

---

## Tech stack

| Část             | Technologie                              |
| ---------------- | ---------------------------------------- |
| Backend          | Python 3 · Flask                         |
| Autentizace      | Werkzeug (password hashing)              |
| Databáze         | SQLite (`restaurant.db`)                 |
| PDF export       | fpdf2                                    |
| JPG export       | Pillow · cairosvg                        |
| E-mail           | smtplib (SSL, port 465)                  |
| Fonty            | Exo 2 Regular + Black (`.ttf` ve `fonts/`) |

---

## Databázové schéma

```sql
CREATE TABLE daily_menu (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    date       TEXT    UNIQUE NOT NULL,   -- YYYY-MM-DD
    promo_text TEXT,
    updated_by TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE menu_sections (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    menu_id  INTEGER NOT NULL REFERENCES daily_menu(id) ON DELETE CASCADE,
    title    TEXT    NOT NULL,
    position INTEGER DEFAULT 0
);
CREATE TABLE menu_items (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    section_id INTEGER NOT NULL REFERENCES menu_sections(id) ON DELETE CASCADE,
    portion    TEXT,
    name       TEXT    NOT NULL,
    price      TEXT,
    position   INTEGER DEFAULT 0
);
CREATE TABLE restaurant_info (
    key   TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT    UNIQUE NOT NULL,
    password_hash TEXT    NOT NULL,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE reservations (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    datum      TEXT    NOT NULL,
    cas        TEXT    NOT NULL,
    pocet      INTEGER NOT NULL,
    jmeno      TEXT    NOT NULL,
    email      TEXT    NOT NULL,
    telefon    TEXT    NOT NULL,
    zprava     TEXT,
    status     TEXT    DEFAULT 'pending',
    lang       TEXT    DEFAULT 'cs',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE popups (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    title      TEXT    NOT NULL,
    body       TEXT,
    starts_at  TEXT,
    expires_at TEXT    NOT NULL,
    image      TEXT,
    is_active  INTEGER DEFAULT 1,
    created_by TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

## Spuštění lokálně

```bash
git clone https://github.com/dosartcz/kozel-u-bohemky.git
cd kozel-u-bohemky/restaurant
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# Doplň hodnoty do .env (viz níže)
python app.py
```

Aplikace běží na <http://localhost:5000>.

Databáze `restaurant.db` se vytvoří automaticky při prvním spuštění. Administrátorský účet se zadá přes proměnnou prostředí `ADMIN_PASSWORD` (viz níže).

---

## Proměnné prostředí

Zkopíruj `.env.example` jako `.env` a doplň:

| Proměnná         | Popis                                                  |
| ---------------- | ------------------------------------------------------ |
| `SECRET_KEY`     | Tajný klíč Flask session (libovolný dlouhý náhodný řetězec) |
| `ADMIN_PASSWORD` | Heslo pro výchozí administrátorský účet                |
| `SMTP_PASS`      | Heslo k SMTP účtu `rezervace@kozelubohemky.cz`         |

SMTP host je `smtp.hosting90.cz`, port `465` (SSL). Notifikace o rezervacích se zasílají na `rezervace@kozelubohemky.cz`.

---

## Export menu (PDF / JPG)

Exporty vyžadují fonty **Exo 2** ve složce `fonts/`:

```
fonts/
  Exo2-Regular.ttf
  Exo2-Black.ttf
```

Fonty jsou dostupné zdarma na [Google Fonts](https://fonts.google.com/specimen/Exo+2). Bez nich export selže (aplikace na chybějící soubory upozorní při startu).

---

## Struktura projektu

```
restaurant/
├── app.py               # Hlavní Flask aplikace
├── restaurant.db        # SQLite databáze (gitignore)
├── requirements.txt     # Python závislosti
├── .env.example         # Vzor proměnných prostředí
├── .gitignore
├── fonts/               # Exo2-Regular.ttf, Exo2-Black.ttf
├── static/              # CSS, JS, obrázky
└── templates/           # Jinja2 šablony
```

---

## Licence

MIT.
