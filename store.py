import json
import sqlite3
from pathlib import Path
from threading import RLock


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = RLock()
        with self.connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, body TEXT NOT NULL)"
            )

    def connect(self):
        return sqlite3.connect(self.path, timeout=10)

    def save(self, run):
        with self.lock, self.connect() as db:
            db.execute(
                "INSERT INTO runs VALUES (?,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body",
                (run["id"], json.dumps(run)),
            )

    def get(self, run_id):
        with self.connect() as db:
            row = db.execute("SELECT body FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        return json.loads(row[0])

    def all(self):
        with self.connect() as db:
            return [
                json.loads(r[0])
                for r in db.execute(
                    "SELECT body FROM runs ORDER BY rowid DESC LIMIT 100"
                )
            ]

    def recover(self):
        for run in self.all():
            if run["status"] in ("queued", "running"):
                run.update(
                    status="interrupted",
                    error="Server restarted during execution. Start a new run; no patch was approved.",
                )
                self.save(run)
