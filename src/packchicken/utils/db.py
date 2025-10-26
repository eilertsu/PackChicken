import sqlite3, json, time
from pathlib import Path

# Filen packchicken.db vil ligge i rotmappen til prosjektet
DB_PATH = Path(__file__).resolve().parents[2] / "packchicken.db"

def init_db():
    """Opprett tabellen jobs hvis den ikke finnes"""
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id TEXT,
            status TEXT DEFAULT 'pending',
            payload TEXT,
            created_at REAL,
            updated_at REAL
        )
        """)
        conn.commit()

def add_job(order_dict):
    """Legg til en ny jobb basert på en ordre"""
    payload = json.dumps(order_dict)
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            "INSERT INTO jobs (order_id, payload, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (order_dict.get("id"), payload, time.time(), time.time()),
        )
        conn.commit()

def get_next_job():
    """Hent neste jobb med status pending"""
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT id, payload FROM jobs WHERE status='pending' ORDER BY id LIMIT 1")
        row = c.fetchone()
    if not row:
        return None
    job_id, payload = row
    return job_id, json.loads(payload)

def update_status(job_id, status):
    """Oppdater statusen til en jobb"""
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("UPDATE jobs SET status=?, updated_at=? WHERE id=?", (status, time.time(), job_id))
        conn.commit()
