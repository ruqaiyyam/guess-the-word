# Guess the Word

Wordle-style game built with Python (Flask + SQLite).

## Run
```
pip install -r requirements.txt
python app.py          # http://127.0.0.1:5000
pytest                 # run tests
```
The database (`game.db`) is created on first run with 20 seeded 5-letter words and one admin account
(default `Administrator` / `Admin$123`; override with `ADMIN_USER`, `ADMIN_PASS`, `SECRET_KEY` env vars).

## Rules implemented
- Register/login. Username: 5+ letters only. Password: 5+ chars with a letter, a digit and one of `$ % *`.
- Players get a random word (max 3 words per day); 5 guesses per word, upper-case letters only.
- Green = right place, orange = wrong place, grey = absent (duplicate letters handled correctly).
- Win/lose pop-up with OK, which ends the game. Words and guesses are stored with the date.
- Admin: daily report (users, correct guesses) and per-user report (date, words tried, correct guesses).
