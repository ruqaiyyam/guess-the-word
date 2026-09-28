import sqlite3
from datetime import date, timedelta

import pytest

from app import MAX_GAMES_PER_DAY, create_app, score, validate_credentials


@pytest.fixture
def client(tmp_path):
    app = create_app(str(tmp_path / "t.db"))
    app.config["TESTING"] = True
    return app.test_client()


def register_login(c, name="Player", pw="pass1$"):
    c.post("/register", data={"username": name, "password": pw})
    return c.post("/login", data={"username": name, "password": pw})


def answer_of(c, game_id):
    db = sqlite3.connect(c.application.config["DATABASE"])
    w = db.execute("SELECT w.word FROM games g JOIN words w ON w.id=g.word_id WHERE g.id=?",
                   (game_id,)).fetchone()[0]
    db.close()
    return w


def start(c):
    r = c.post("/play")
    loc = r.headers["Location"]
    return int(loc.rsplit("/", 1)[1]) if "/game/" in loc else None


def test_score_basic_and_duplicates():
    assert score("APPLE", "APPLE") == ["green"] * 5
    assert score("STONE", "APPLE") == ["grey", "grey", "grey", "grey", "green"]
    assert score("LLAMA", "APPLE") == ["orange", "grey", "orange", "grey", "grey"]
    # only one E in answer: second E must be grey
    assert score("EERIE", "RIVER") == ["orange", "grey", "orange", "orange", "grey"]


@pytest.mark.parametrize("u,p,ok", [
    ("abcd", "abc1$", False), ("abcde", "abc1$", True), ("ab1cde", "abc1$", False),
    ("abcde", "ab1$", False), ("abcde", "abcde$", False), ("abcde", "abc12", False),
    ("abcde", "abc1%", True), ("AbCdE", "a1*bc", True), ("abcde", "abc1#", False)])
def test_credentials(u, p, ok):
    assert (validate_credentials(u, p) is None) is ok


def test_twenty_words_seeded(client):
    db = sqlite3.connect(client.application.config["DATABASE"])
    words = [r[0] for r in db.execute("SELECT word FROM words")]
    assert len(words) == 20 and all(len(w) == 5 and w.isupper() for w in words)


def test_duplicate_username_rejected(client):
    register_login(client)
    r = client.post("/register", data={"username": "player", "password": "pass1$"}, follow_redirects=True)
    assert b"already taken" in r.data


def test_win_flow(client):
    register_login(client)
    gid = start(client)
    r = client.post(f"/game/{gid}/guess", json={"guess": answer_of(client, gid)})
    assert r.json["status"] == "won" and r.json["colors"] == ["green"] * 5
    assert client.post(f"/game/{gid}/guess", json={"guess": "APPLE"}).status_code == 400


def test_lose_after_five_and_input_validation(client):
    register_login(client)
    gid = start(client)
    ans = answer_of(client, gid)
    assert client.post(f"/game/{gid}/guess", json={"guess": "abcde"}).status_code == 400
    assert client.post(f"/game/{gid}/guess", json={"guess": "ABCD"}).status_code == 400
    for _ in range(5):
        r = client.post(f"/game/{gid}/guess", json={"guess": "ZZZZZ"})
    assert r.json["status"] == "lost" and r.json["answer"] == ans
    assert client.post(f"/game/{gid}/guess", json={"guess": "ZZZZZ"}).status_code == 400


def test_history_shown_in_order(client):
    register_login(client)
    gid = start(client)
    for g in ("ZZZZA", "ZZZZB"):
        client.post(f"/game/{gid}/guess", json={"guess": g})
    html = client.get(f"/game/{gid}").get_data(as_text=True)
    assert html.index(">A<") < html.index(">B<")


def test_daily_limit(client):
    register_login(client)
    for _ in range(MAX_GAMES_PER_DAY):
        gid = start(client)
        client.post(f"/game/{gid}/guess", json={"guess": answer_of(client, gid)})
    r = client.post("/play", follow_redirects=True)
    assert b"Daily limit reached" in r.data


def test_unfinished_game_is_resumed(client):
    register_login(client)
    assert start(client) == start(client)


def test_admin_reports_and_access_control(client):
    register_login(client, "Alphaa")
    gid = start(client)
    client.post(f"/game/{gid}/guess", json={"guess": answer_of(client, gid)})
    assert client.get("/admin").status_code == 302  # players can't see admin
    client.get("/logout")
    client.post("/login", data={"username": "Administrator", "password": "Admin$123"})
    today = date.today().isoformat()
    html = client.get(f"/admin?date={today}&username=Alphaa").get_data(as_text=True)
    assert f"<td>{today}</td><td>1</td><td>1</td>" in html
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    assert "<td>0</td><td>0</td>" in client.get(f"/admin?date={yesterday}").get_data(as_text=True)
