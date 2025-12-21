#!/usr/bin/env python3
from __future__ import annotations

import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template_string, request
from werkzeug.utils import secure_filename

CURRENT_FILE = Path(__file__).resolve()
REPO_ROOT = CURRENT_FILE.parents[3]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from packchicken.utils import db
from packchicken.utils.orders_csv import enqueue_orders_from_csv
from packchicken.workers.job_worker import process_all_pending_jobs

# Paths and env
for candidate in (REPO_ROOT / ".env", REPO_ROOT / "secrets.env"):
    if candidate.exists():
        load_dotenv(candidate, override=True)

ORDERS_DIR = Path(os.getenv("ORDERS_DIR", REPO_ROOT / "ORDERS")).resolve()
LABEL_DIR = Path(os.getenv("LABEL_DIR", REPO_ROOT / "LABELS")).resolve()
ORDERS_DIR.mkdir(parents=True, exist_ok=True)
LABEL_DIR.mkdir(parents=True, exist_ok=True)
db.init_db()

app = Flask(__name__)


def format_ts(value: float | None) -> str:
    if not value:
        return ""
    try:
        return datetime.fromtimestamp(float(value)).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(value)


def job_stats() -> Dict[str, int]:
    with sqlite3.connect(db.DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT status, COUNT(*) FROM jobs GROUP BY status")
        rows = c.fetchall()
    return {status or "unknown": count for status, count in rows}


def recent_jobs(limit: int = 20) -> list[Dict[str, Any]]:
    with sqlite3.connect(db.DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT id, order_id, status, created_at, updated_at FROM jobs ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        rows = c.fetchall()
    return [
        {
            "id": row["id"],
            "order_id": row["order_id"],
            "status": row["status"],
            "created_at": format_ts(row["created_at"]),
            "updated_at": format_ts(row["updated_at"]),
        }
        for row in rows
    ]


def json_error(message: str, status_code: int = 400):
    resp = jsonify({"ok": False, "error": message})
    resp.status_code = status_code
    return resp


@app.get("/")
def index():
    return render_template_string(
        INDEX_HTML,
        orders_dir=str(ORDERS_DIR),
        label_dir=str(LABEL_DIR),
    )


@app.get("/api/jobs")
def api_jobs():
    return jsonify(
        {
            "ok": True,
            "stats": job_stats(),
            "jobs": recent_jobs(),
            "orders_dir": str(ORDERS_DIR),
            "label_dir": str(LABEL_DIR),
        }
    )


@app.post("/api/upload")
def api_upload():
    if "file" not in request.files:
        return json_error("Fant ingen fil i forespørselen.")
    file = request.files["file"]
    if not file.filename:
        return json_error("Velg en CSV-fil først.")

    filename = secure_filename(file.filename)
    if not filename:
        return json_error("Ugyldig filnavn.")
    if not filename.lower().endswith(".csv"):
        return json_error("Bare CSV-filer støttes.")

    destination = ORDERS_DIR / filename
    try:
        file.save(destination)
        order_ids = enqueue_orders_from_csv(destination)
    except Exception as exc:
        return json_error(f"Klarte ikke å enqueue CSV: {exc}", status_code=500)

    return jsonify(
        {
            "ok": True,
            "orders_added": order_ids,
            "csv_path": str(destination),
        }
    )


@app.post("/api/process")
def api_process():
    summary = process_all_pending_jobs()
    summary["ok"] = True
    return jsonify(summary)


INDEX_HTML = """
<!doctype html>
<html lang="no">
<head>
  <meta charset="utf-8">
  <title>PackChicken GUI</title>
  <style>
    :root {
      --bg: #0f172a;
      --panel: #111827;
      --muted: #a5b4fc;
      --card: #0b1220;
      --accent: #a3e635;
      --accent-2: #22d3ee;
      --text: #e5e7eb;
      --success: #84cc16;
      --error: #f87171;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: radial-gradient(circle at 20% 20%, rgba(34,211,238,0.08), transparent 40%),
                  radial-gradient(circle at 80% 0%, rgba(163,230,53,0.06), transparent 35%),
                  var(--bg);
      color: var(--text);
      font-family: 'DM Sans', 'Helvetica Neue', sans-serif;
      min-height: 100vh;
    }
    .shell { max-width: 1100px; margin: 0 auto; padding: 32px 20px 60px; }
    header { margin-bottom: 24px; }
    h1 { margin: 0; font-size: 28px; letter-spacing: -0.5px; }
    p.lead { margin: 6px 0 0; color: var(--muted); }
    .grid { display: grid; gap: 16px; }
    .two { grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); }
    .panel {
      background: rgba(17, 24, 39, 0.7);
      border: 1px solid rgba(255,255,255,0.05);
      border-radius: 14px;
      padding: 18px;
      box-shadow: 0 20px 50px rgba(0,0,0,0.35);
    }
    .panel h3 { margin: 0 0 12px; letter-spacing: -0.2px; }
    .stat-row { display: flex; gap: 12px; flex-wrap: wrap; }
    .stat { background: var(--card); padding: 12px 14px; border-radius: 12px; border: 1px solid rgba(255,255,255,0.05); min-width: 140px; }
    .stat label { display: block; color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px; }
    .stat strong { font-size: 22px; }
    form { display: grid; gap: 10px; }
    input[type="file"] { padding: 10px; border-radius: 10px; border: 1px dashed rgba(255,255,255,0.15); background: rgba(255,255,255,0.02); color: var(--text); }
    button {
      background: linear-gradient(135deg, var(--accent), var(--accent-2));
      color: #0b1220;
      border: none;
      padding: 12px 14px;
      border-radius: 10px;
      font-weight: 700;
      cursor: pointer;
      transition: transform 120ms ease, box-shadow 120ms ease;
      box-shadow: 0 10px 25px rgba(34,211,238,0.25);
    }
    button:hover { transform: translateY(-1px); box-shadow: 0 16px 40px rgba(34,211,238,0.35); }
    button.secondary { background: #1f2937; color: var(--text); box-shadow: none; border: 1px solid rgba(255,255,255,0.08); }
    .card-text { color: var(--muted); font-size: 14px; }
    table { width: 100%; border-collapse: collapse; margin-top: 6px; }
    th, td { padding: 10px 8px; border-bottom: 1px solid rgba(255,255,255,0.05); text-align: left; }
    th { color: var(--muted); font-size: 12px; letter-spacing: 0.5px; text-transform: uppercase; }
    tr:hover td { background: rgba(255,255,255,0.02); }
    .badge {
      display: inline-flex; align-items: center; gap: 6px;
      padding: 6px 10px; border-radius: 999px; font-size: 12px; font-weight: 700;
      background: rgba(163,230,53,0.12); color: var(--accent);
    }
    .badge.fail { background: rgba(248,113,113,0.12); color: var(--error); }
    .badge.done { background: rgba(52,211,153,0.14); color: #34d399; }
    footer { margin-top: 22px; color: var(--muted); font-size: 13px; }
    #toast {
      position: fixed; right: 22px; bottom: 22px; padding: 12px 14px;
      background: #0b1220; border-radius: 10px; border: 1px solid rgba(255,255,255,0.08);
      box-shadow: 0 15px 40px rgba(0,0,0,0.35); min-width: 220px; display: none;
    }
    #toast.error { border-color: rgba(248,113,113,0.4); }
    @media (max-width: 640px) { .stat { min-width: 46%; } }
  </style>
</head>
<body>
  <div class="shell">
    <header>
      <h1>PackChicken Dashboard</h1>
      <p class="lead">Last opp ordre-CSV, legg i kø og kjør Bring-booking fra nettleseren.</p>
    </header>

    <section class="panel">
      <h3>Oversikt</h3>
      <div class="stat-row" id="stats">
        <div class="stat"><label>Pending</label><strong>0</strong></div>
        <div class="stat"><label>Done</label><strong>0</strong></div>
        <div class="stat"><label>Failed</label><strong>0</strong></div>
      </div>
    </section>

    <section class="panel grid two">
      <div>
        <h3>1. Last opp CSV</h3>
        <p class="card-text">Filen lagres i {{ orders_dir }} og legges umiddelbart i kø.</p>
        <form id="upload-form" enctype="multipart/form-data">
          <input type="file" name="file" accept=".csv,text/csv" required>
          <button type="submit">Legg i kø</button>
        </form>
      </div>
      <div>
        <h3>2. Kjør jobber</h3>
        <p class="card-text">Kjør Bring-booking for pending jobber og slå sammen etiketter til én PDF.</p>
        <div class="stat-row" style="margin-top:10px;">
          <button id="process-btn">Kjør pending nå</button>
        </div>
        <p class="card-text" style="margin-top:12px;">Etiketter lagres i {{ label_dir }}.</p>
      </div>
    </section>

    <section class="panel">
      <div style="display:flex; align-items:center; justify-content: space-between;">
        <h3>Siste jobber</h3>
        <div style="display:flex; align-items:center; gap:10px;">
          <span class="card-text" id="job-count"></span>
          <button id="refresh-btn" class="secondary" style="padding:8px 12px;">Oppdater</button>
        </div>
      </div>
      <table>
        <thead>
          <tr><th>ID</th><th>Ordre</th><th>Status</th><th>Opprettet</th><th>Oppdatert</th></tr>
        </thead>
        <tbody id="jobs-body">
          <tr><td colspan="5">Ingen jobber ennå.</td></tr>
        </tbody>
      </table>
    </section>

    <footer>
      <div>ORDERS: {{ orders_dir }}</div>
      <div>LABELS: {{ label_dir }}</div>
    </footer>
  </div>
  <div id="toast"></div>
  <script>
    const ordersDir = {{ orders_dir|tojson }};
    const labelDir = {{ label_dir|tojson }};

    const toastEl = document.getElementById('toast');
    function toast(msg, tone='info') {
      toastEl.textContent = msg;
      toastEl.classList.toggle('error', tone === 'error');
      toastEl.style.display = 'block';
      setTimeout(() => { toastEl.style.display = 'none'; }, 3200);
    }

    async function loadJobs() {
      try {
        const res = await fetch('/api/jobs');
        const data = await res.json();
        if (!data.ok) { throw new Error(data.error || 'Ukjent feil'); }
        renderStats(data.stats || {});
        renderJobs(data.jobs || []);
      } catch (err) {
        toast('Klarte ikke å hente jobber: ' + err.message, 'error');
      }
    }

    function renderStats(stats) {
      const statEl = document.getElementById('stats');
      const pending = stats.pending || stats.Pending || 0;
      const done = stats.done || stats.Done || 0;
      const failed = stats.failed || stats.Failed || 0;
      statEl.innerHTML = `
        <div class="stat"><label>Pending</label><strong>${pending}</strong></div>
        <div class="stat"><label>Done</label><strong>${done}</strong></div>
        <div class="stat"><label>Failed</label><strong>${failed}</strong></div>
      `;
    }

    function renderJobs(jobs) {
      const body = document.getElementById('jobs-body');
      const countEl = document.getElementById('job-count');
      countEl.textContent = jobs.length ? `${jobs.length} siste jobber` : 'Ingen jobber enda';
      if (!jobs.length) {
        body.innerHTML = '<tr><td colspan="5">Ingen jobber ennå.</td></tr>';
        return;
      }
      body.innerHTML = jobs.map(row => {
        const status = (row.status || '').toLowerCase();
        let badgeClass = 'badge';
        if (status === 'failed') badgeClass += ' fail';
        if (status === 'done') badgeClass += ' done';
        return `
          <tr>
            <td>${row.id}</td>
            <td>${row.order_id || ''}</td>
            <td><span class="${badgeClass}">${row.status || ''}</span></td>
            <td>${row.created_at || ''}</td>
            <td>${row.updated_at || ''}</td>
          </tr>
        `;
      }).join('');
    }

    document.getElementById('upload-form').addEventListener('submit', async (ev) => {
      ev.preventDefault();
      const formData = new FormData(ev.target);
      try {
        const res = await fetch('/api/upload', { method: 'POST', body: formData });
        const data = await res.json();
        if (!data.ok) throw new Error(data.error || 'Ukjent feil');
        const added = Array.isArray(data.orders_added) ? data.orders_added.length : 0;
        toast(`La til ${added} jobber`);
        ev.target.reset();
        loadJobs();
      } catch (err) {
        toast(err.message, 'error');
      }
    });

    document.getElementById('process-btn').addEventListener('click', async () => {
      try {
        const res = await fetch('/api/process', { method: 'POST' });
        const data = await res.json();
        if (!data.ok) throw new Error(data.error || 'Ukjent feil');
        const jobs = data.processed_jobs || 0;
        const merged = data.merged_label ? 'Slått sammen etiketter til ' + data.merged_label : 'Ingen etiketter å slå sammen';
        toast(`Kjørte ${jobs} jobber. ${merged}.`);
        loadJobs();
      } catch (err) {
        toast('Kjøring feilet: ' + err.message, 'error');
      }
    });

    document.getElementById('refresh-btn').addEventListener('click', () => loadJobs());
    loadJobs();
    setInterval(loadJobs, 8000);
  </script>
</body>
</html>
"""


if __name__ == "__main__":
    port = int(os.getenv("PACKCHICKEN_GUI_PORT", "5050"))
    app.run(host="0.0.0.0", port=port, debug=False)
