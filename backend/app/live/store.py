"""Transactional local storage for real candles and reproducible decisions."""
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

class Store:
    def __init__(self, path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS candles (
                    timeframe TEXT NOT NULL, time INTEGER NOT NULL,
                    payload TEXT NOT NULL, PRIMARY KEY(timeframe, time));
                CREATE TABLE IF NOT EXISTS analyses (
                    id TEXT PRIMARY KEY, candle_time INTEGER NOT NULL,
                    payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS paper (
                    id TEXT PRIMARY KEY, analysis_id TEXT NOT NULL UNIQUE,
                    payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS backtests (
                    id TEXT PRIMARY KEY, created_at TEXT NOT NULL, payload TEXT NOT NULL);
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        try:
            with db:
                yield db
        finally:
            db.close()

    def save_candles(self, frames):
        with self.connect() as db:
            for tf, rows in frames.items():
                db.executemany('INSERT OR REPLACE INTO candles VALUES (?,?,?)',
                    [(tf, c['time'], json.dumps(c, allow_nan=False)) for c in rows])

    def candles(self, tf, limit=10000):
        with self.connect() as db:
            rows = db.execute('SELECT payload FROM candles WHERE timeframe=? ORDER BY time DESC LIMIT ?', (tf, limit)).fetchall()
        return [json.loads(r[0]) for r in reversed(rows)]

    def save_analysis(self, data):
        with self.connect() as db:
            db.execute('INSERT OR IGNORE INTO analyses VALUES (?,?,?)',
                (data['id'], data['candle_time'], json.dumps(data, allow_nan=False)))

    def history(self, limit=30):
        with self.connect() as db:
            rows = db.execute('SELECT payload FROM analyses ORDER BY candle_time DESC, rowid DESC LIMIT ?', (limit,)).fetchall()
        return [json.loads(r[0]) for r in rows]

    def analysis(self, ident):
        with self.connect() as db:
            row = db.execute('SELECT payload FROM analyses WHERE id=?', (ident,)).fetchone()
        return json.loads(row[0]) if row else None

    def paper(self):
        with self.connect() as db:
            rows = db.execute('SELECT payload FROM paper ORDER BY rowid DESC').fetchall()
        return [json.loads(r[0]) for r in rows]

    def save_paper(self, data, create=False):
        with self.connect() as db:
            if create:
                # One position at a time, including concurrent requests.
                db.execute('BEGIN IMMEDIATE')
                if any(json.loads(r[0])['status'] in ('open', 'pending') for r in db.execute('SELECT payload FROM paper')):
                    raise ValueError('Já existe uma simulação aberta.')
                db.execute('INSERT INTO paper VALUES (?,?,?)', (data['id'], data['analysis_id'], json.dumps(data, allow_nan=False)))
            else:
                db.execute('UPDATE paper SET payload=? WHERE id=?', (json.dumps(data, allow_nan=False), data['id']))

    def save_backtest(self, data):
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO backtests VALUES (?,?,?)', (data['id'], data['created_at'], json.dumps(data, allow_nan=False)))

    def latest_backtest(self):
        with self.connect() as db:
            row = db.execute('SELECT payload FROM backtests ORDER BY created_at DESC LIMIT 1').fetchone()
        return json.loads(row[0]) if row else None
