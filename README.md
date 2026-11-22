# STU // Case File — Treasure Hunt CTF

A responsive Flask + SQLite starter platform for a team-based CTF treasure hunt. It includes authentication, team creation/joining, a team leaderboard, challenge progression scaffolding, and diminishing flag rewards. **No challenge statements or flags are included.**

## Run locally

Requires Python 3.10+.

```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000

The SQLite database (`treasure.db`) is created automatically on first run. For a real deployment, set a long random `SECRET_KEY`, use HTTPS, and set `COOKIE_SECURE=1`. Example:

```bash
SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')" COOKIE_SECURE=1 python app.py
```

Use a production WSGI server such as Gunicorn behind HTTPS for deployment; do not expose Flask's development server directly to the internet.

## Included functionality

- Account registration/login, hashed passwords, session cookies, CSRF token validation.
- Create a team or join one using an 8-character invite code.
- Team roster, invite-code copy, leave-team action.
- Team leaderboard, ordered by score then solves.
- Four character tracks with three sequential challenge slots each.
- Challenge placeholders are inactive by default; no challenge content or flags are seeded.
- Backend flag verification and one solve per team per challenge.
- Per-challenge diminishing scoring: `max(100, 500 - 50 * number_of_prior_team_solves)`.
- Final dossier unlock is recorded when a team has solved all 12 challenge records.

## Adding challenge content later

The `challenges` table is seeded with 12 inactive placeholders. To publish a challenge, set its title/description, store a SHA-256 hash of the exact flag, and set `active=1`. Example Python snippet (run from the project directory):

```python
import sqlite3, hashlib
db = sqlite3.connect("treasure.db")
flag = "Securinets_fst{example_flag}"
db.execute("""
UPDATE challenges
SET title=?, description=?, flag_hash=?, active=1
WHERE character_key=? AND slot=?
""", (
    "The First Clue",
    "Your challenge statement goes here.",
    hashlib.sha256(flag.encode()).hexdigest(),
    "char_1", 1
))
db.commit()
db.close()
```

Character keys and slots:
- `char_1`, `char_2`, `char_3`, `char_4`
- Each has slots `1`, `2`, `3`.

A team can access slot 2 only after solving slot 1 for that character, and slot 3 only after solving slot 2. The first team to solve a given challenge earns 500 points; each subsequent team earns 50 fewer points, down to 100. A team cannot score twice on the same challenge.

## Important production notes

This is a solid functional starter, not a hardened public competition deployment. Before launch, add rate limiting, email verification/password reset, audit logging, backups, and a production database/server setup. The included admin panel is a starter management interface and should receive a security review before a public event. For larger events, PostgreSQL is preferable to SQLite.


## Visual themes
The interface includes three selectable themes. Use the CASE / PAPER / NEON controls in the navigation or login page. The selected theme is remembered in the current browser using local storage.
- **CASE SCENE**: warm evidence-board paper, caution yellow, investigation red, stamped/condensed headings.
- **PAPER FILE**: clean white editorial layout with restrained blue accents and serif headings.
- **NEON GRID**: cyberpunk violet, electric cyan and magenta with futuristic display headings.

## Administrator panel

The site now includes a protected admin console at `/admin`. It provides:
- Overview counts for accounts, teams, published challenges, and solves.
- A challenge editor for all 12 existing slots: title, player-facing description, flag, and publish/draft status.
- Recent solve activity and participant/team summaries.
- A read-only database viewer for users, teams, memberships, challenges, solves, and final unlocks. Password hashes and flag hashes are never displayed.

### Create the first administrator

On the first launch, set these environment variables before running the app. Use a password of at least 12 characters:

```bash
export ADMIN_USERNAME="your_admin_username"
export ADMIN_EMAIL="you@example.com"
read -s -p "Admin password: " ADMIN_PASSWORD; echo
export ADMIN_PASSWORD
python app.py
```

The app creates that account as an administrator. If the username or email already belongs to an account, that account is promoted to administrator; it does not reset its password. After the admin account has been created, you can unset the variables. Sign in normally and open **Admin** in the navigation, or visit `/admin`.

Challenge flags are hashed before storage. To change a flag, enter its new value in the editor; leaving the field blank preserves the existing flag. Publish only after the title, instructions, and flag are ready. The current game design contains 12 fixed challenge slots (4 characters × 3 stages); the admin panel lets you author and publish each slot.

## Stu photo-wall background

The supplied Stu photo archive is included under `static/stu_photos/`. A shared animated background uses a four-row photo wall with darkened, blurred images and red X overlays; it scrolls horizontally behind every page. The site respects reduced-motion browser preferences.


## La Collina case configuration

- Four suspect storylines, three sequential challenges each.
- A team-specific hint appears only after that team solves all three challenges for that suspect.
- The final challenge unlocks only after the team solves all twelve challenges.
- The La Collina Files page embeds the supplied 13-page PDF dossier.
- The admin panel can edit suspect names/hints, challenge content/media/flags/points, and final instructions/flag.
- The app listens on `0.0.0.0` for LAN testing. Use a production WSGI server and HTTPS for public deployment.


### Run locally (Fedora/Linux)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open `http://127.0.0.1:5000`. For devices on the same Wi-Fi, use the host machine's LAN IP and allow port 5000 through the firewall if needed.
