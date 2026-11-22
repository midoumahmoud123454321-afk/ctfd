import os, sqlite3, secrets, hashlib, hmac, string, uuid
from functools import wraps
from flask import Flask, g, render_template, request, redirect, url_for, session, flash, jsonify, abort
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("DATABASE_PATH", os.path.join(APP_DIR, "treasure.db"))
app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY", "change-this-before-deployment-" + secrets.token_hex(16)),
    MAX_CONTENT_LENGTH=100 * 1024 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "0") == "1",
    PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 7,
)

CHARACTERS = [
    ("mahmoud", "Mahmoud Mansouri", "A member of the board with a story to tell", "♟"),
    ("amine_gdoura", "Amine Gdoura", "A member of the board with a story to tell", "⌁"),
    ("emna", "Emna Khlifi", "A member of the board with a story to tell", "◈"),
    ("omar", "Omar Belhaj Youssef", "A member of the board with a story to tell", "✦"),
]
HINTS = {
    "mahmoud": "The killer is a big fan of President Habib Bourguiba.",
    "amine_gdoura": "The killer comes from Monastir.",
    "emna": "The killer is the founder of a club.",
    "omar": "The killer studies electronics.",
}
FINAL_FLAG = "Securinets_fst{Omar_Monastir_Borguiba_Founder_Electronics}"


def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
        g.db.execute("PRAGMA busy_timeout = 5000")
    return g.db

@app.teardown_appcontext
def close_db(_error=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS users (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      username TEXT NOT NULL COLLATE NOCASE UNIQUE,
      email TEXT NOT NULL COLLATE NOCASE UNIQUE,
      password_hash TEXT NOT NULL,
      is_admin INTEGER NOT NULL DEFAULT 0,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS teams (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT NOT NULL COLLATE NOCASE UNIQUE,
      invite_code TEXT NOT NULL UNIQUE,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS team_members (
      user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
      team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
      joined_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS challenges (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      character_key TEXT NOT NULL,
      slot INTEGER NOT NULL CHECK(slot BETWEEN 1 AND 3),
      title TEXT NOT NULL,
      description TEXT NOT NULL DEFAULT '',
      points INTEGER NOT NULL DEFAULT 500,
      flag_hash TEXT,
      active INTEGER NOT NULL DEFAULT 0,
      UNIQUE(character_key, slot)
    );
    CREATE TABLE IF NOT EXISTS solves (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
      challenge_id INTEGER NOT NULL REFERENCES challenges(id) ON DELETE CASCADE,
      points INTEGER NOT NULL,
      solved_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      UNIQUE(team_id, challenge_id)
    );
    CREATE TABLE IF NOT EXISTS final_unlocks (
      team_id INTEGER PRIMARY KEY REFERENCES teams(id) ON DELETE CASCADE,
      unlocked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      final_solved_at TEXT
    );
    CREATE TABLE IF NOT EXISTS suspects (
      character_key TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      description TEXT NOT NULL DEFAULT '',
      icon TEXT NOT NULL DEFAULT '♟',
      hint TEXT NOT NULL DEFAULT ''
    );
    CREATE TABLE IF NOT EXISTS challenge_media (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      challenge_id INTEGER NOT NULL REFERENCES challenges(id) ON DELETE CASCADE,
      filename TEXT NOT NULL,
      media_type TEXT NOT NULL CHECK(media_type IN ('image','video')),
      original_name TEXT NOT NULL,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS game_settings (
      setting_key TEXT PRIMARY KEY,
      setting_value TEXT NOT NULL DEFAULT ''
    );
    """)
    # Upgrade databases created by earlier versions.
    user_columns = {row[1] for row in conn.execute("PRAGMA table_info(users)")}
    if "is_admin" not in user_columns:
        conn.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0")

    challenge_columns = {row[1] for row in conn.execute("PRAGMA table_info(challenges)")}
    if "points" not in challenge_columns:
        conn.execute("ALTER TABLE challenges ADD COLUMN points INTEGER NOT NULL DEFAULT 500")
    unlock_columns = {row[1] for row in conn.execute("PRAGMA table_info(final_unlocks)")}
    if "final_solved_at" not in unlock_columns:
        conn.execute("ALTER TABLE final_unlocks ADD COLUMN final_solved_at TEXT")
    suspect_columns = {row[1] for row in conn.execute("PRAGMA table_info(suspects)")}
    if "hint" not in suspect_columns:
        conn.execute("ALTER TABLE suspects ADD COLUMN hint TEXT NOT NULL DEFAULT ''")
    for key, name, desc, icon in CHARACTERS:
        conn.execute("INSERT OR IGNORE INTO suspects(character_key,name,description,icon,hint) VALUES(?,?,?,?,?)", (key, name, desc, icon, HINTS[key]))
        conn.execute("UPDATE suspects SET name=?, description=?, hint=? WHERE character_key=?", (name, desc, HINTS[key], key))
    conn.execute("INSERT OR IGNORE INTO game_settings(setting_key,setting_value) VALUES('final_flag_hash',?)", (hashlib.sha256(FINAL_FLAG.encode()).hexdigest(),))
    conn.execute("INSERT OR IGNORE INTO game_settings(setting_key,setting_value) VALUES('final_description',?)", ("Your team has solved all twelve suspect challenges. Review the four unlocked hints, identify the killer, and submit the final flag.",))

    # Optional first-run admin bootstrap. Set these environment variables before startup.
    admin_username = os.environ.get("ADMIN_USERNAME", "").strip()
    admin_email = os.environ.get("ADMIN_EMAIL", "").strip().lower()
    admin_password = os.environ.get("ADMIN_PASSWORD", "")
    if admin_username and admin_email and len(admin_password) >= 12:
        existing_admin = conn.execute("SELECT id FROM users WHERE username=? COLLATE NOCASE OR email=? COLLATE NOCASE",
                                      (admin_username, admin_email)).fetchone()
        if existing_admin:
            conn.execute("UPDATE users SET is_admin=1 WHERE id=?", (existing_admin[0],))
        else:
            conn.execute("INSERT INTO users(username,email,password_hash,is_admin) VALUES(?,?,?,1)",
                         (admin_username, admin_email, generate_password_hash(admin_password)))

    # Empty challenge slots are scaffolding only: no challenge content or flags are installed.
    for key, name, _desc, _icon in CHARACTERS:
        for slot in range(1, 4):
            conn.execute(
                "INSERT OR IGNORE INTO challenges(character_key,slot,title,description,active) VALUES(?,?,?,?,0)",
                (key, slot, f"Challenge {slot}", "Not published yet.")
            )
    conn.commit()
    conn.close()

def current_user():
    uid = session.get("user_id")
    if not uid:
        return None
    return db().execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()

def login_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not current_user():
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapped

def team_for_user(user_id):
    return db().execute("""
      SELECT t.* FROM teams t JOIN team_members m ON m.team_id=t.id WHERE m.user_id=?
    """, (user_id,)).fetchone()

def team_score(team_id):
    row = db().execute("SELECT COALESCE(SUM(points),0) AS score, COUNT(*) AS solves FROM solves WHERE team_id=?", (team_id,)).fetchone()
    return row["score"], row["solves"]

def solved_ids(team_id):
    return {r["challenge_id"] for r in db().execute("SELECT challenge_id FROM solves WHERE team_id=?", (team_id,))}

def challenge_state(team_id):
    rows = db().execute("SELECT * FROM challenges ORDER BY character_key,slot").fetchall()
    solved = solved_ids(team_id)
    output = []
    suspect_rows = db().execute("SELECT * FROM suspects ORDER BY character_key").fetchall()
    for suspect in suspect_rows:
        key, name, desc, icon = suspect["character_key"], suspect["name"], suspect["description"], suspect["icon"]
        group = []
        prior_solved = True
        for ch in [r for r in rows if r["character_key"] == key]:
            is_solved = ch["id"] in solved
            available = bool(ch["active"]) and prior_solved
            earlier_solves = db().execute("SELECT COUNT(*) FROM solves WHERE challenge_id=?", (ch["id"],)).fetchone()[0]
            current_points = max(100, ch["points"] - 50 * earlier_solves)
            group.append({"id": ch["id"], "slot": ch["slot"], "title": ch["title"],
                          "description": ch["description"], "points": ch["points"], "current_points": current_points, "solved": is_solved,
                          "available": available, "published": bool(ch["active"])})
            prior_solved = is_solved
        hint_unlocked = len(group) == 3 and all(ch["solved"] for ch in group)
        output.append({"key": key, "name": name, "description": desc, "icon": icon,
                       "hint": suspect["hint"], "hint_unlocked": hint_unlocked, "challenges": group})
    return output

def check_final_unlock(team_id):
    count = db().execute("SELECT COUNT(*) FROM solves s JOIN challenges c ON c.id=s.challenge_id").fetchone()[0]
    team_count = db().execute("""
      SELECT COUNT(*) FROM solves s JOIN challenges c ON c.id=s.challenge_id WHERE s.team_id=?
    """, (team_id,)).fetchone()[0]
    if team_count == 12 and db().execute("SELECT COUNT(*) FROM challenges").fetchone()[0] == 12:
        db().execute("INSERT OR IGNORE INTO final_unlocks(team_id) VALUES(?)", (team_id,))
        db().commit()
        return True
    return False

def csrf_token():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_urlsafe(32)
    return session["_csrf"]

@app.context_processor
def inject_globals():
    photos_dir = os.path.join(APP_DIR, "static", "stu_photos")
    photos = sorted([name for name in os.listdir(photos_dir) if name.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))]) if os.path.isdir(photos_dir) else []
    return {"me": current_user(), "csrf_token": csrf_token,
            "is_admin": bool(current_user() and current_user()["is_admin"]),
            "stu_photos": photos}

@app.before_request
def csrf_protect():
    if request.method == "POST":
        token = request.form.get("_csrf") or request.headers.get("X-CSRF-Token")
        if not token or not hmac.compare_digest(token, session.get("_csrf", "")):
            abort(400, "Invalid or missing security token. Refresh and try again.")

@app.route("/")
def index():
    return redirect(url_for("dashboard") if current_user() else url_for("login"))

@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user():
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        if len(username) < 3 or len(username) > 24 or not all(c.isalnum() or c in "_-" for c in username):
            flash("Username must be 3–24 characters (letters, numbers, _ or -).", "error")
        elif "@" not in email or len(email) > 120:
            flash("Enter a valid email address.", "error")
        elif len(password) < 10:
            flash("Use a password with at least 10 characters.", "error")
        else:
            try:
                cur = db().execute("INSERT INTO users(username,email,password_hash) VALUES(?,?,?)",
                                   (username, email, generate_password_hash(password)))
                db().commit()
                session.clear()
                session["user_id"] = cur.lastrowid
                session.permanent = True
                return redirect(url_for("team"))
            except sqlite3.IntegrityError:
                flash("That username or email is already registered.", "error")
    return render_template("auth.html", mode="register")

@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user():
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        identity = request.form.get("identity", "").strip()
        user = db().execute("SELECT * FROM users WHERE username=? COLLATE NOCASE OR email=? COLLATE NOCASE",
                            (identity, identity)).fetchone()
        if user and check_password_hash(user["password_hash"], request.form.get("password", "")):
            session.clear()
            session["user_id"] = user["id"]
            session.permanent = True
            return redirect(url_for("dashboard"))
        flash("Invalid username/email or password.", "error")
    return render_template("auth.html", mode="login")

@app.post("/logout")
@login_required
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/team", methods=["GET", "POST"])
@login_required
def team():
    user = current_user()
    existing = team_for_user(user["id"])
    if request.method == "POST":
        action = request.form.get("action")
        if existing:
            flash("You are already in a team. Leave it before joining another.", "error")
        elif action == "create":
            name = request.form.get("team_name", "").strip()
            if len(name) < 3 or len(name) > 32:
                flash("Team name must be 3–32 characters.", "error")
            else:
                code = "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(8))
                try:
                    cur = db().execute("INSERT INTO teams(name,invite_code) VALUES(?,?)", (name, code))
                    db().execute("INSERT INTO team_members(user_id,team_id) VALUES(?,?)", (user["id"], cur.lastrowid))
                    db().commit()
                    flash("Team created. Share the invite code with your teammates.", "success")
                    return redirect(url_for("team"))
                except sqlite3.IntegrityError:
                    flash("That team name is already taken.", "error")
        elif action == "join":
            code = request.form.get("invite_code", "").strip().upper()
            found = db().execute("SELECT * FROM teams WHERE invite_code=?", (code,)).fetchone()
            if not found:
                flash("Invite code not found.", "error")
            else:
                try:
                    db().execute("INSERT INTO team_members(user_id,team_id) VALUES(?,?)", (user["id"], found["id"]))
                    db().commit()
                    flash(f"You joined {found['name']}.", "success")
                    return redirect(url_for("team"))
                except sqlite3.IntegrityError:
                    flash("Could not join that team.", "error")
    members = []
    if existing:
        members = db().execute("""
          SELECT u.username,m.joined_at FROM team_members m JOIN users u ON u.id=m.user_id
          WHERE m.team_id=? ORDER BY m.joined_at
        """, (existing["id"],)).fetchall()
    return render_template("team.html", team=existing, members=members)

@app.post("/team/leave")
@login_required
def leave_team():
    user = current_user()
    db().execute("DELETE FROM team_members WHERE user_id=?", (user["id"],))
    db().commit()
    flash("You left your team. Your previous team's solves and points remain with that team.", "success")
    return redirect(url_for("team"))

@app.route("/dashboard")
@login_required
def dashboard():
    user = current_user()
    team = team_for_user(user["id"])
    if not team:
        return redirect(url_for("team"))
    score, solves = team_score(team["id"])
    progress = challenge_state(team["id"])
    unlocked = db().execute("SELECT 1 FROM final_unlocks WHERE team_id=?", (team["id"],)).fetchone() is not None
    return render_template("dashboard.html", team=team, score=score, solves=solves,
                           progress=progress, final_unlocked=unlocked)

@app.route("/la-collina-files")
@login_required
def collina_files():
    return render_template("collina_files.html")

@app.route("/leaderboard")
@login_required
def leaderboard():
    rows = db().execute("""
      SELECT t.id,t.name,COALESCE(SUM(s.points),0) score,COUNT(s.id) solves,
      (SELECT COUNT(*) FROM team_members m WHERE m.team_id=t.id) members
      FROM teams t LEFT JOIN solves s ON s.team_id=t.id
      GROUP BY t.id ORDER BY score DESC, solves DESC, t.name COLLATE NOCASE ASC
    """).fetchall()
    mine = team_for_user(current_user()["id"])
    return render_template("leaderboard.html", rows=rows, my_team_id=mine["id"] if mine else None)

@app.route("/challenges")
@login_required
def challenges():
    team = team_for_user(current_user()["id"])
    if not team:
        return redirect(url_for("team"))
    unlocked = db().execute("SELECT 1 FROM final_unlocks WHERE team_id=?", (team["id"],)).fetchone() is not None
    return render_template("challenges.html", groups=challenge_state(team["id"]), final_unlocked=unlocked)

@app.route("/challenge/<int:challenge_id>", methods=["GET", "POST"])
@login_required
def challenge(challenge_id):
    team = team_for_user(current_user()["id"])
    if not team:
        return redirect(url_for("team"))
    ch = db().execute("SELECT * FROM challenges WHERE id=?", (challenge_id,)).fetchone()
    if not ch:
        abort(404)
    state = next((x for group in challenge_state(team["id"]) for x in group["challenges"] if x["id"] == challenge_id), None)
    if not state or not state["available"]:
        flash("This challenge is locked or has not been published yet.", "error")
        return redirect(url_for("challenges"))
    media = db().execute("SELECT * FROM challenge_media WHERE challenge_id=? ORDER BY id", (challenge_id,)).fetchall()
    solves_before = db().execute("SELECT COUNT(*) FROM solves WHERE challenge_id=?", (challenge_id,)).fetchone()[0]
    available_points = max(100, ch["points"] - 50 * solves_before)
    if request.method == "POST":
        flag = request.form.get("flag", "").strip()
        if not ch["flag_hash"]:
            flash("This challenge has not been configured yet.", "error")
        elif hashlib.sha256(flag.encode()).hexdigest() != ch["flag_hash"]:
            flash("Incorrect flag. Keep investigating.", "error")
        else:
            conn = db()
            conn.execute("BEGIN IMMEDIATE")
            already = conn.execute("SELECT 1 FROM solves WHERE team_id=? AND challenge_id=?", (team["id"], challenge_id)).fetchone()
            if already:
                conn.rollback()
                flash("Your team has already solved this challenge.", "success")
            else:
                solves_before = conn.execute("SELECT COUNT(*) FROM solves WHERE challenge_id=?", (challenge_id,)).fetchone()[0]
                points = max(100, ch["points"] - 50 * solves_before)
                conn.execute("INSERT INTO solves(team_id,challenge_id,points) VALUES(?,?,?)", (team["id"], challenge_id, points))
                conn.commit()
                check_final_unlock(team["id"])
                flash(f"Correct flag! Your team earned {points} points.", "success")
                return redirect(url_for("challenges"))
    return render_template("challenge.html", challenge=ch, state=state, media=media, available_points=available_points)

@app.route("/final", methods=["GET", "POST"])
@login_required
def final_dossier():
    team = team_for_user(current_user()["id"])
    if not team:
        return redirect(url_for("team"))
    unlocked = db().execute("SELECT 1 FROM final_unlocks WHERE team_id=?", (team["id"],)).fetchone() is not None
    if not unlocked:
        flash("The final dossier is locked. Your team must solve all 12 challenges first.", "error")
        return redirect(url_for("challenges"))
    if request.method == "POST":
        submitted = request.form.get("flag", "").strip()
        expected = db().execute("SELECT setting_value FROM game_settings WHERE setting_key='final_flag_hash'").fetchone()
        if expected and hashlib.sha256(submitted.encode()).hexdigest() == expected["setting_value"]:
            db().execute("UPDATE final_unlocks SET final_solved_at=CURRENT_TIMESTAMP WHERE team_id=?", (team["id"],))
            db().commit()
            flash("Correct. Your team identified Stu's killer.", "success")
            return render_template("final.html", solved=True, final_description="")
        flash("That is not the correct final flag. Revisit the evidence and hints.", "error")
    description = db().execute("SELECT setting_value FROM game_settings WHERE setting_key='final_description'").fetchone()
    completed = db().execute("SELECT final_solved_at FROM final_unlocks WHERE team_id=?", (team["id"],)).fetchone()
    is_solved = bool(completed and completed["final_solved_at"])
    return render_template("final.html", solved=is_solved, final_description=description["setting_value"] if description else "")

@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    user = current_user()
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        old_password = request.form.get("old_password", "")
        new_password = request.form.get("new_password", "")
        if username and (len(username) < 3 or len(username) > 24 or not all(c.isalnum() or c in "_-" for c in username)):
            flash("Username must be 3–24 characters (letters, numbers, _ or -).", "error")
        elif new_password and (not check_password_hash(user["password_hash"], old_password) or len(new_password) < 10):
            flash("To change your password, enter your current password and a new password of at least 10 characters.", "error")
        else:
            try:
                if username:
                    db().execute("UPDATE users SET username=? WHERE id=?", (username, user["id"]))
                if new_password:
                    db().execute("UPDATE users SET password_hash=? WHERE id=?", (generate_password_hash(new_password), user["id"]))
                db().commit()
                flash("Account settings updated.", "success")
            except sqlite3.IntegrityError:
                flash("That username is already taken.", "error")
    return render_template("settings.html", user=current_user())

def admin_required(fn):
    @wraps(fn)
    @login_required
    def wrapped(*args, **kwargs):
        user = current_user()
        if not user or not user["is_admin"]:
            abort(403)
        return fn(*args, **kwargs)
    return wrapped

@app.route("/admin")
@admin_required
def admin_dashboard():
    conn = db()
    stats = {
        "users": conn.execute("SELECT COUNT(*) FROM users").fetchone()[0],
        "teams": conn.execute("SELECT COUNT(*) FROM teams").fetchone()[0],
        "challenges": conn.execute("SELECT COUNT(*) FROM challenges WHERE active=1").fetchone()[0],
        "solves": conn.execute("SELECT COUNT(*) FROM solves").fetchone()[0],
    }
    challenges = conn.execute("""SELECT c.*, su.name suspect_name, (SELECT COUNT(*) FROM solves s WHERE s.challenge_id=c.id) solve_count
                                FROM challenges c LEFT JOIN suspects su ON su.character_key=c.character_key ORDER BY c.character_key,c.slot""").fetchall()
    suspects = conn.execute("SELECT * FROM suspects ORDER BY character_key").fetchall()
    final_description_row = conn.execute("SELECT setting_value FROM game_settings WHERE setting_key='final_description'").fetchone()
    recent_solves = conn.execute("""SELECT s.solved_at,s.points,t.name team_name,c.title challenge_title
                                  FROM solves s JOIN teams t ON t.id=s.team_id
                                  JOIN challenges c ON c.id=s.challenge_id
                                  ORDER BY s.solved_at DESC LIMIT 12""").fetchall()
    users = conn.execute("""SELECT u.id,u.username,u.email,u.is_admin,u.created_at,t.name team_name
                           FROM users u LEFT JOIN team_members m ON m.user_id=u.id
                           LEFT JOIN teams t ON t.id=m.team_id ORDER BY u.created_at DESC LIMIT 100""").fetchall()
    teams = conn.execute("""SELECT t.id,t.name,t.invite_code,t.created_at,COUNT(DISTINCT m.user_id) members,
                           COALESCE(SUM(s.points),0) score,COUNT(DISTINCT s.id) solves
                           FROM teams t LEFT JOIN team_members m ON m.team_id=t.id
                           LEFT JOIN solves s ON s.team_id=t.id GROUP BY t.id ORDER BY score DESC""").fetchall()
    return render_template("admin.html", stats=stats, challenges=challenges, suspects=suspects,
                           recent_solves=recent_solves, users=users, teams=teams,
                           final_description=final_description_row["setting_value"] if final_description_row else "")

@app.route("/admin/suspects", methods=["POST"])
@admin_required
def admin_edit_suspects():
    for key, _name, _desc, _icon in CHARACTERS:
        name = request.form.get(f"name_{key}", "").strip()
        if not name or len(name) > 60:
            flash("Every suspect needs a name (maximum 60 characters).", "error")
            return redirect(url_for("admin_dashboard") + "#suspects")
        hint = request.form.get(f"hint_{key}", "").strip()
        if not hint or len(hint) > 240:
            flash("Every suspect needs a hint (maximum 240 characters).", "error")
            return redirect(url_for("admin_dashboard") + "#suspects")
        db().execute("UPDATE suspects SET name=?,hint=? WHERE character_key=?", (name, hint, key))
    db().commit()
    flash("Suspect names updated.", "success")
    return redirect(url_for("admin_dashboard") + "#suspects")

@app.route("/admin/challenges/<int:challenge_id>", methods=["GET", "POST"])
@admin_required
def admin_edit_challenge(challenge_id):
    ch = db().execute("SELECT * FROM challenges WHERE id=?", (challenge_id,)).fetchone()
    if not ch:
        abort(404)
    upload_dir = os.path.join(APP_DIR, "static", "uploads")
    os.makedirs(upload_dir, exist_ok=True)
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        flag = request.form.get("flag", "").strip()
        try:
            points = int(request.form.get("points", "500"))
        except ValueError:
            points = 0
        active = 1 if request.form.get("active") == "1" else 0
        if not title or len(title) > 100:
            flash("Challenge title is required and must be under 100 characters.", "error")
        elif points < 100 or points > 10000:
            flash("Base points must be between 100 and 10,000.", "error")
        elif active and not (flag or ch["flag_hash"]):
            flash("Set a flag before publishing this challenge.", "error")
        else:
            flag_hash = hashlib.sha256(flag.encode()).hexdigest() if flag else ch["flag_hash"]
            db().execute("UPDATE challenges SET title=?,description=?,points=?,flag_hash=?,active=? WHERE id=?",
                         (title, description, points, flag_hash, active, challenge_id))
            allowed_images = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
            allowed_videos = {".mp4", ".webm", ".ogg", ".mov"}
            for uploaded in request.files.getlist("media"):
                if not uploaded or not uploaded.filename:
                    continue
                original = uploaded.filename[:255]
                ext = os.path.splitext(secure_filename(original))[1].lower()
                if ext not in allowed_images | allowed_videos:
                    flash(f"Skipped unsupported file: {original}", "error")
                    continue
                filename = uuid.uuid4().hex + ext
                uploaded.save(os.path.join(upload_dir, filename))
                kind = "image" if ext in allowed_images else "video"
                db().execute("INSERT INTO challenge_media(challenge_id,filename,media_type,original_name) VALUES(?,?,?,?)",
                             (challenge_id, filename, kind, original))
            for media_id in request.form.getlist("delete_media"):
                row = db().execute("SELECT filename FROM challenge_media WHERE id=? AND challenge_id=?", (media_id, challenge_id)).fetchone()
                if row:
                    try:
                        os.remove(os.path.join(upload_dir, row["filename"]))
                    except FileNotFoundError:
                        pass
                    db().execute("DELETE FROM challenge_media WHERE id=? AND challenge_id=?", (media_id, challenge_id))
            db().commit()
            flash("Challenge saved.", "success")
            return redirect(url_for("admin_edit_challenge", challenge_id=challenge_id))
    media = db().execute("SELECT * FROM challenge_media WHERE challenge_id=? ORDER BY id", (challenge_id,)).fetchall()
    suspect = db().execute("SELECT name FROM suspects WHERE character_key=?", (ch["character_key"],)).fetchone()
    return render_template("admin_challenge.html", challenge=ch, media=media, suspect_name=suspect["name"] if suspect else ch["character_key"])

@app.route("/admin/final-settings", methods=["POST"])
@admin_required
def admin_final_settings():
    description = request.form.get("description", "").strip()
    flag = request.form.get("flag", "").strip()
    if not description:
        flash("Final challenge instructions cannot be empty.", "error")
    else:
        db().execute("UPDATE game_settings SET setting_value=? WHERE setting_key='final_description'", (description,))
        if flag:
            db().execute("UPDATE game_settings SET setting_value=? WHERE setting_key='final_flag_hash'", (hashlib.sha256(flag.encode()).hexdigest(),))
        db().commit()
        flash("Final challenge settings saved.", "success")
    return redirect(url_for("admin_dashboard") + "#final-settings")

@app.route("/admin/database")
@admin_required
def admin_database():
    conn = db()
    # Never expose password hashes or flag hashes in the admin browser.
    tables = {
        "users": conn.execute("SELECT id,username,email,is_admin,created_at FROM users ORDER BY id DESC").fetchall(),
        "teams": conn.execute("SELECT id,name,invite_code,created_at FROM teams ORDER BY id DESC").fetchall(),
        "team_members": conn.execute("SELECT user_id,team_id,joined_at FROM team_members ORDER BY joined_at DESC").fetchall(),
        "challenges": conn.execute("SELECT id,character_key,slot,title,description,points,active FROM challenges ORDER BY id").fetchall(),
        "solves": conn.execute("SELECT id,team_id,challenge_id,points,solved_at FROM solves ORDER BY id DESC").fetchall(),
        "final_unlocks": conn.execute("SELECT team_id,unlocked_at,final_solved_at FROM final_unlocks ORDER BY unlocked_at DESC").fetchall(),
        "suspects": conn.execute("SELECT character_key,name,description,hint,icon FROM suspects ORDER BY character_key").fetchall(),
    }
    return render_template("admin_database.html", tables=tables)

@app.errorhandler(403)
def forbidden(_err):
    return render_template("error.html", code=403, message="Administrator access is required."), 403

@app.errorhandler(400)
def bad_request(err):
    return render_template("error.html", code=400, message=getattr(err, "description", "Bad request")), 400

@app.errorhandler(404)
def not_found(_err):
    return render_template("error.html", code=404, message="This page does not exist."), 404

if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
