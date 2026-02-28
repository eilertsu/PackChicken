import sqlite3, json, time
from pathlib import Path

# Filen packchicken.db vil ligge i rotmappen til prosjektet
DB_PATH = Path(__file__).resolve().parents[2] / "packchicken.db"


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    c = conn.cursor()
    c.execute(f"PRAGMA table_info({table})")
    existing = {row[1] for row in c.fetchall()}
    if column not in existing:
        c.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


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
            updated_at REAL,
            tracking_number TEXT,
            tracking_url TEXT,
            shopify_tracking_synced_at REAL,
            shopify_tracking_sync_error TEXT
        )
        """)
        # Migrer eldre DB-er med manglende felt.
        _ensure_column(conn, "jobs", "tracking_number", "tracking_number TEXT")
        _ensure_column(conn, "jobs", "tracking_url", "tracking_url TEXT")
        _ensure_column(conn, "jobs", "shopify_tracking_synced_at", "shopify_tracking_synced_at REAL")
        _ensure_column(conn, "jobs", "shopify_tracking_sync_error", "shopify_tracking_sync_error TEXT")
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


def save_tracking(job_id, tracking_number: str, tracking_url: str | None = None):
    """Lagre tracking-info fra Bring på jobben."""
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            """
            UPDATE jobs
            SET tracking_number=?,
                tracking_url=?,
                shopify_tracking_synced_at=NULL,
                shopify_tracking_sync_error=NULL,
                updated_at=?
            WHERE id=?
            """,
            (tracking_number, tracking_url, time.time(), job_id),
        )
        conn.commit()


def get_jobs_pending_tracking_sync(limit: int = 50):
    """
    Hent ferdige jobber med tracking som ikke er synket til Shopify ennå.
    """
    lim = max(1, min(int(limit), 500))
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            """
            SELECT id, order_id, payload, tracking_number, tracking_url, shopify_tracking_sync_error
            FROM jobs
            WHERE status='done'
              AND tracking_number IS NOT NULL
              AND tracking_number != ''
              AND shopify_tracking_synced_at IS NULL
            ORDER BY id ASC
            LIMIT ?
            """,
            (lim,),
        )
        rows = c.fetchall()
    return [dict(r) for r in rows]


def mark_tracking_synced(job_id: int):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            """
            UPDATE jobs
            SET shopify_tracking_synced_at=?,
                shopify_tracking_sync_error=NULL,
                updated_at=?
            WHERE id=?
            """,
            (time.time(), time.time(), job_id),
        )
        conn.commit()


def mark_tracking_sync_error(job_id: int, error_message: str):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            """
            UPDATE jobs
            SET shopify_tracking_sync_error=?,
                updated_at=?
            WHERE id=?
            """,
            (str(error_message)[:2000], time.time(), job_id),
        )
        conn.commit()
