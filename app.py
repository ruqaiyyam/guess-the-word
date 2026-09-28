"""Guess the Word - a Wordle-style game (Flask + SQLite)."""
import os
import random
import re
import sqlite3
from collections import Counter
from datetime import date
from functools import wraps

from flask import (Flask, flash, g, jsonify, redirect, render_template,
                   request, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

WORDS = [
    "APPLE", "BRAIN", "CHAIR", "DREAM", "EARTH", "FLAME", "GRAPE", "HOUSE",
    "IMAGE", "JOKER", "KNIFE", "LEMON", "MANGO", "NIGHT", "OCEAN", "PLANT",
    "QUEEN", "RIVER", "STONE", "TIGER",
]
MAX_GUESSES = 5
MAX_GAMES_PER_DAY = 3
SPECIAL_CHARS = "$%*"
USERNAME_RE = re.compile(r"^[A-Za-z]{5,}$")
GUESS_RE = re.compile(r"^[A-Z]{5}$")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('admin', 'player'))
);
CREATE TABLE IF NOT EXISTS words (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    word TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS games (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    word_id INTEGER NOT NULL REFERENCES words(id),
    play_date TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'in_progress'
        CHECK (status IN ('in_progress', 'won', 'lost'))
);
CREATE TABLE IF NOT EXISTS guesses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id INTEGER NOT NULL REFERENCES games(id),
    guess TEXT NOT NULL,
    guess_no INTEGER NOT NULL
);
"""


def score(guess, answer):
    """Return a list of 'green' / 'orange' / 'grey' for each letter."""
    result = ["grey"] * len(guess)
    remaining = Counter()
    for i, (gc, ac) in enumerate(zip(guess, answer)):
        if gc == ac:
            result[i] = "green"
        else:
            remaining[ac] += 1
    for i, gc in enumerate(guess):
        if result[i] != "green" and remaining[gc] > 0:
            result[i] = "orange"
            remaining[gc] -= 1
    return result


def validate_credentials(username, password):
    """Return an error message, or None if valid."""
    if not USERNAME_RE.match(username):
        return "Username must be at least 5 letters (A-Z, a-z only)."
    if (len(password) < 5 or not any(c.isalpha() for c in password)
            or not any(c.isdigit() for c in password)
            or not any(c in SPECIAL_CHARS for c in password)):
        return ("Password must be at least 5 characters with a letter, "
                "a digit and one of $ % *.")
    return None


def create_app(db_path=None):
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-change-me")
    app.config["DATABASE"] = db_path or os.path.join(app.root_path, "game.db")

    def get_db():
        if "db" not in g:
            g.db = sqlite3.connect(app.config["DATABASE"])
            g.db.row_factory = sqlite3.Row
        return g.db

    @app.teardown_appcontext
    def close_db(_exc):
        db = g.pop("db", None)
        if db is not None:
            db.close()

    def init_db():
        db = sqlite3.connect(app.config["DATABASE"])
        db.executescript(SCHEMA)
        if db.execute("SELECT COUNT(*) FROM words").fetchone()[0] == 0:
            db.executemany("INSERT INTO words (word) VALUES (?)",
                           [(w,) for w in WORDS])
        if db.execute("SELECT COUNT(*) FROM users WHERE role='admin'").fetchone()[0] == 0:
            db.execute(
                "INSERT INTO users (username, password_hash, role) VALUES (?,?,'admin')",
                (os.environ.get("ADMIN_USER", "Administrator"),
                 generate_password_hash(os.environ.get("ADMIN_PASS", "Admin$123"))))
        db.commit()
        db.close()

    init_db()

    # ---------- auth helpers ----------
    def current_user():
        uid = session.get("user_id")
        if uid is None:
            return None
        return get_db().execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()

    def login_required(role=None):
        def deco(fn):
            @wraps(fn)
            def wrapper(*a, **kw):
                user = current_user()
                if user is None:
                    return redirect(url_for("login"))
                if role and user["role"] != role:
                    flash("You are not allowed to view that page.", "error")
                    return redirect(url_for("index"))
                g.user = user
                return fn(*a, **kw)
            return wrapper
        return deco

    @app.context_processor
    def inject_user():
        return {"user": current_user()}

    # ---------- routes ----------
    @app.route("/")
    def index():
        user = current_user()
        if user:
            return redirect(url_for("admin" if user["role"] == "admin" else "dashboard"))
        return redirect(url_for("login"))

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            error = validate_credentials(username, password)
            if error is None:
                db = get_db()
                if db.execute("SELECT 1 FROM users WHERE lower(username)=lower(?)",
                              (username,)).fetchone():
                    error = "That username is already taken."
                else:
                    db.execute("INSERT INTO users (username, password_hash, role) "
                               "VALUES (?,?,'player')",
                               (username, generate_password_hash(password)))
                    db.commit()
                    flash("Registered! Please log in.", "ok")
                    return redirect(url_for("login"))
            flash(error, "error")
        return render_template("register.html")

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            row = get_db().execute("SELECT * FROM users WHERE username=?",
                                   (request.form.get("username", "").strip(),)).fetchone()
            if row and check_password_hash(row["password_hash"], request.form.get("password", "")):
                session.clear()
                session["user_id"] = row["id"]
                return redirect(url_for("index"))
            flash("Invalid username or password.", "error")
        return render_template("login.html")

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    # ---------- player ----------
    def games_today(user_id):
        return get_db().execute("SELECT COUNT(*) FROM games WHERE user_id=? AND play_date=?",
                                (user_id, date.today().isoformat())).fetchone()[0]

    @app.route("/dashboard")
    @login_required("player")
    def dashboard():
        used = games_today(g.user["id"])
        return render_template("dashboard.html", used=used,
                               limit=MAX_GAMES_PER_DAY)

    @app.route("/play", methods=["POST"])
    @login_required("player")
    def play():
        db = get_db()
        open_game = db.execute("SELECT id FROM games WHERE user_id=? AND status='in_progress'",
                               (g.user["id"],)).fetchone()
        if open_game:
            return redirect(url_for("game", game_id=open_game["id"]))
        if games_today(g.user["id"]) >= MAX_GAMES_PER_DAY:
            flash(f"Daily limit reached: only {MAX_GAMES_PER_DAY} words per day. Come back tomorrow!", "error")
            return redirect(url_for("dashboard"))
        words = db.execute("SELECT id FROM words").fetchall()
        word_id = random.choice(words)["id"]
        cur = db.execute("INSERT INTO games (user_id, word_id, play_date) VALUES (?,?,?)",
                         (g.user["id"], word_id, date.today().isoformat()))
        db.commit()
        return redirect(url_for("game", game_id=cur.lastrowid))

    def load_game(game_id):
        db = get_db()
        row = db.execute("SELECT g.*, w.word FROM games g JOIN words w ON w.id=g.word_id "
                         "WHERE g.id=? AND g.user_id=?", (game_id, g.user["id"])).fetchone()
        return row

    @app.route("/game/<int:game_id>")
    @login_required("player")
    def game(game_id):
        row = load_game(game_id)
        if row is None:
            flash("Game not found.", "error")
            return redirect(url_for("dashboard"))
        if row["status"] != "in_progress":
            return redirect(url_for("dashboard"))
        rows = get_db().execute("SELECT guess FROM guesses WHERE game_id=? ORDER BY guess_no",
                                (game_id,)).fetchall()
        history = [{"letters": list(r["guess"]), "colors": score(r["guess"], row["word"])}
                   for r in rows]
        return render_template("game.html", game_id=game_id, history=history,
                               max_guesses=MAX_GUESSES)

    @app.route("/game/<int:game_id>/guess", methods=["POST"])
    @login_required("player")
    def guess(game_id):
        row = load_game(game_id)
        if row is None:
            return jsonify(error="Game not found."), 404
        if row["status"] != "in_progress":
            return jsonify(error="This game is already over."), 400
        text = (request.get_json(silent=True) or {}).get("guess", "")
        if not isinstance(text, str) or not GUESS_RE.match(text):
            return jsonify(error="Enter exactly 5 letters in upper case (A-Z)."), 400
        db = get_db()
        n = db.execute("SELECT COUNT(*) FROM guesses WHERE game_id=?", (game_id,)).fetchone()[0]
        db.execute("INSERT INTO guesses (game_id, guess, guess_no) VALUES (?,?,?)",
                   (game_id, text, n + 1))
        status = "in_progress"
        if text == row["word"]:
            status = "won"
        elif n + 1 >= MAX_GUESSES:
            status = "lost"
        db.execute("UPDATE games SET status=? WHERE id=?", (status, game_id))
        db.commit()
        out = {"colors": score(text, row["word"]), "status": status,
               "guesses_used": n + 1}
        if status == "lost":
            out["answer"] = row["word"]
        return jsonify(out)

    # ---------- admin ----------
    @app.route("/admin")
    @login_required("admin")
    def admin():
        db = get_db()
        day = request.args.get("date") or date.today().isoformat()
        day_report = db.execute(
            "SELECT COUNT(DISTINCT user_id) AS users, "
            "COALESCE(SUM(status='won'),0) AS correct FROM games WHERE play_date=?",
            (day,)).fetchone()
        players = db.execute("SELECT username FROM users WHERE role='player' ORDER BY username").fetchall()
        selected = request.args.get("username")
        user_report = None
        if selected:
            urow = db.execute("SELECT id FROM users WHERE username=? AND role='player'",
                              (selected,)).fetchone()
            if urow:
                user_report = db.execute(
                    "SELECT play_date, COUNT(*) AS tried, SUM(status='won') AS correct "
                    "FROM games WHERE user_id=? GROUP BY play_date ORDER BY play_date DESC",
                    (urow["id"],)).fetchall()
        return render_template("admin.html", day=day, day_report=day_report,
                               players=players, selected=selected,
                               user_report=user_report)

    return app


if __name__ == "__main__":
    create_app().run(debug=True)
