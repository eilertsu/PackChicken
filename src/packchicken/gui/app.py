#!/usr/bin/env python3
from __future__ import annotations

import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from dotenv import load_dotenv, dotenv_values
from flask import Flask, jsonify, render_template_string, request, send_from_directory
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

SETTINGS_KEYS = [
    "BRING_RETURN_NAME",
    "BRING_RETURN_ADDRESS",
    "BRING_RETURN_ADDRESS2",
    "BRING_RETURN_POSTAL",
    "BRING_RETURN_CITY",
    "BRING_RETURN_COUNTRY",
    "BRING_RETURN_EMAIL",
    "BRING_RETURN_PHONE",
]


def current_settings() -> Dict[str, str]:
    return {k: os.getenv(k, "") or "" for k in SETTINGS_KEYS}


def save_env_settings(updates: Dict[str, str]) -> None:
    env_path = REPO_ROOT / ".env"
    existing = dotenv_values(env_path) if env_path.exists() else {}
    merged = {**{k: str(v) for k, v in existing.items()}, **{k: str(v) for k, v in updates.items()}}
    lines = [f"{k}={v}" for k, v in merged.items()]
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    # reload into process env
    load_dotenv(env_path, override=True)


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
        settings=current_settings(),
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
            "settings": current_settings(),
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
    is_test = str(request.args.get("test", "false")).lower() in {"1", "true", "yes", "y"}
    do_fulfill = str(request.args.get("fulfill", "false")).lower() in {"1", "true", "yes", "y"}
    return_label = str(request.args.get("return_label", "false")).lower() in {"1", "true", "yes", "y"}
    summary = process_all_pending_jobs(test_indicator=is_test, update_fulfill=do_fulfill, return_label=return_label)
    summary["ok"] = True
    summary["test_mode"] = is_test
    summary["fulfill"] = do_fulfill
    summary["return_label"] = return_label
    # Build download-friendly URLs for merged/single labels
    def label_url(path_str: str | None) -> str | None:
        if not path_str:
            return None
        p = Path(path_str)
        if not p.exists():
            return None
        return f"/labels/{p.name}"

    summary["merged_label_url"] = label_url(summary.get("merged_label"))
    summary["label_urls"] = [label_url(p) for p in summary.get("downloaded_labels", []) if label_url(p)]
    summary["merged_label_name"] = Path(summary["merged_label"]).name if summary.get("merged_label") else None
    summary["label_names"] = [Path(p).name for p in summary.get("downloaded_labels", [])]
    return jsonify(summary)


@app.post("/api/fulfill")
def api_fulfill():
    summary = process_all_pending_jobs(test_indicator=False, update_fulfill=True)
    summary["ok"] = True
    return jsonify(summary)


@app.get("/labels/<path:filename>")
def serve_label(filename: str):
    # Serve generated label PDFs from LABEL_DIR
    return send_from_directory(LABEL_DIR, filename, as_attachment=True)


@app.post("/api/settings")
def api_settings():
    payload = request.get_json(silent=True) or {}
    updates = {k: v for k, v in payload.items() if k in SETTINGS_KEYS and v is not None}
    if not updates:
        return json_error("Ingen settings oppdatert.")
    save_env_settings(updates)
    return jsonify({"ok": True, "settings": current_settings()})


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
    .stat-row { display: flex; gap: 12px; flex-wrap: wrap; align-items: center; }
    .stat { background: var(--card); padding: 12px 14px; border-radius: 12px; border: 1px solid rgba(255,255,255,0.05); min-width: 140px; }
    .stat label { display: block; color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px; }
    .stat strong { font-size: 22px; }
    form { display: grid; gap: 10px; }
    .file-picker {
      position: relative;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      flex-direction: column;
      text-align: center;
      gap: 12px;
      padding: 32px 16px;
      border: 1px dashed rgba(255,255,255,0.2);
      border-radius: 12px;
      background: rgba(255,255,255,0.03);
      color: var(--text);
      cursor: pointer;
      transition: border-color 120ms ease, background 120ms ease;
    }
    .file-picker:hover { border-color: rgba(163,230,53,0.6); background: rgba(255,255,255,0.05); }
    .file-picker.dragging { border-color: var(--accent-2); background: rgba(34,211,238,0.08); }
    .file-picker input[type="file"] {
      position: absolute;
      inset: 0;
      opacity: 0;
      cursor: pointer;
    }
    .file-picker .label { font-weight: 600; }
    button, .btn {
      background: linear-gradient(135deg, var(--accent), var(--accent-2));
      color: #0b1220;
      border: none;
      padding: 12px 14px;
      border-radius: 10px;
      font-weight: 700;
      cursor: pointer;
      transition: transform 120ms ease, box-shadow 120ms ease;
      box-shadow: 0 10px 25px rgba(34,211,238,0.25);
      height: 46px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 6px;
    }
    button:hover, .btn:hover { transform: translateY(-1px); box-shadow: 0 16px 40px rgba(34,211,238,0.35); }
    button.secondary, .btn.secondary { background: #1f2937; color: var(--text); box-shadow: none; border: 1px solid rgba(255,255,255,0.08); }
    button:disabled, .btn:disabled {
      opacity: 0.5;
      cursor: not-allowed;
      transform: none;
      box-shadow: none;
      background: #1f2937;
      color: var(--muted);
      border: 1px solid rgba(255,255,255,0.05);
    }
    .toggle {
      display: inline-flex;
      align-items: center;
      gap: 10px;
      color: var(--muted);
      user-select: none;
    }
    .toggle input { display: none; }
    .switch {
      position: relative;
      width: 48px;
      height: 26px;
      background: #1f2937;
      border-radius: 999px;
      border: 1px solid rgba(255,255,255,0.08);
      transition: background 120ms ease, border 120ms ease;
    }
    .switch::after {
      content: '';
      position: absolute;
      top: 3px;
      left: 3px;
      width: 20px;
      height: 20px;
      background: var(--text);
      border-radius: 50%;
      transition: transform 140ms ease, background 120ms ease;
      box-shadow: 0 4px 10px rgba(0,0,0,0.2);
    }
    .toggle input:checked + .switch {
      background: linear-gradient(135deg, var(--accent), var(--accent-2));
      border-color: rgba(255,255,255,0.2);
    }
    .toggle input:checked + .switch::after {
      transform: translateX(22px);
      background: #0b1220;
    }
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
    .download-item { margin-top: 10px; padding: 10px; border: 1px solid rgba(255,255,255,0.06); border-radius: 12px; background: rgba(255,255,255,0.02); }
    .download-name { font-weight: 600; color: var(--text); }
    .download-actions { margin-top: 8px; }
    .modal {
      position: fixed; inset: 0; background: rgba(0,0,0,0.55);
      display: none; align-items: center; justify-content: center; z-index: 20;
    }
    .modal.active { display: flex; }
    .modal-content {
      background: #0b1220; border: 1px solid rgba(255,255,255,0.1); border-radius: 14px;
      padding: 20px; max-width: 520px; width: 90%;
      box-shadow: 0 30px 80px rgba(0,0,0,0.45);
    }
    .modal h3 { margin-top: 0; margin-bottom: 12px; }
    .form-grid { display: grid; gap: 10px; }
    .form-grid label { font-size: 12px; color: var(--muted); }
    .form-grid input { width: 100%; padding: 10px; border-radius: 10px; border: 1px solid rgba(255,255,255,0.1); background: rgba(255,255,255,0.03); color: var(--text); }
    .modal-actions { display: flex; gap: 10px; justify-content: flex-end; margin-top: 14px; }
  </style>
</head>
<body>
  <div class="shell">
    <header>
      <div style="display:flex; align-items:center; justify-content: space-between; gap:12px;">
        <div>
          <h1>PackChicken Dashboard</h1>
          <p class="lead">Last opp ordre-CSV fra shopify og kjør Bring-booking fra nettleseren.</p>
        </div>
        <button id="settings-btn" class="secondary" style="padding:10px 12px;">Innstillinger</button>
      </div>
    </header>

    <section class="panel">
      <h3>Oversikt</h3>
      <div class="stat-row" id="stats">
        <div class="stat"><label>Totalt</label><strong>0</strong></div>
        <div class="stat"><label>Done</label><strong>0</strong></div>
        <div class="stat"><label>Failed</label><strong>0</strong></div>
      </div>
    </section>

    <section class="grid two">
      <div class="panel">
        <h3>Last opp & kjør</h3>
        <p class="card-text">Velg Shopify CSV, og kjør Bring-booking. Etiketter lagres i {{ label_dir }}.</p>
        <form id="upload-form" enctype="multipart/form-data" style="margin-top:10px;">
          <label class="file-picker" id="file-picker">
            <span class="label" id="file-label">Slipp CSV her eller velg fil</span>
            <input id="file-input" type="file" name="file" accept=".csv,text/csv" required>
          </label>
          <div class="stat-row" style="margin-top:8px; flex-wrap: nowrap; align-items:center;">
            <button type="submit" data-test="false">Lag etikett</button>
            <button type="button" id="return-btn" class="secondary">Lag returetikett</button>
            <label class="toggle" for="test-toggle">
              <input type="checkbox" id="test-toggle" name="test-toggle">
              <span class="switch"></span>
              <span>Testmodus</span>
            </label>
          </div>
        </form>
      </div>
      <div class="panel">
        <div style="display:flex; align-items:center; justify-content: space-between;">
          <h3>Etiketter</h3>
          <span class="card-text">Siste genererte PDFer</span>
        </div>
        <div id="downloads" class="card-text" style="margin-top:8px;">
          <div class="download-item">
            <div class="download-name">Ingen etikett generert ennå</div>
            <div class="download-actions">
              <button class="secondary" disabled>Last ned</button>
            </div>
          </div>
        </div>
        <div style="margin-top:12px; display:flex; justify-content:flex-start;">
          <button id="fulfill-btn" class="secondary" disabled>Fulfill ordre i Shopify</button>
        </div>
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
  <div id="settings-modal" class="modal">
    <div class="modal-content">
      <h3>Innstillinger (returadresse)</h3>
      <div class="form-grid">
        <div>
          <label for="set-return-name">Navn</label>
          <input id="set-return-name" name="BRING_RETURN_NAME" placeholder="Din butikk AS (Retur)">
        </div>
        <div>
          <label for="set-return-address">Adresse</label>
          <input id="set-return-address" name="BRING_RETURN_ADDRESS" placeholder="Gate 1">
        </div>
        <div>
          <label for="set-return-address2">Adresselinje 2</label>
          <input id="set-return-address2" name="BRING_RETURN_ADDRESS2" placeholder="">
        </div>
        <div>
          <label for="set-return-postal">Postnr</label>
          <input id="set-return-postal" name="BRING_RETURN_POSTAL" placeholder="0123">
        </div>
        <div>
          <label for="set-return-city">By</label>
          <input id="set-return-city" name="BRING_RETURN_CITY" placeholder="Oslo">
        </div>
        <div>
          <label for="set-return-country">Landkode</label>
          <input id="set-return-country" name="BRING_RETURN_COUNTRY" placeholder="NO">
        </div>
        <div>
          <label for="set-return-email">E-post</label>
          <input id="set-return-email" name="BRING_RETURN_EMAIL" placeholder="retur@dinbutikk.no">
        </div>
        <div>
          <label for="set-return-phone">Telefon</label>
          <input id="set-return-phone" name="BRING_RETURN_PHONE" placeholder="+47XXXXXXXX">
        </div>
      </div>
      <div class="modal-actions">
        <button id="settings-cancel" class="secondary" type="button">Lukk</button>
        <button id="settings-save" type="button">Lagre</button>
      </div>
    </div>
  </div>
  <div id="toast"></div>
  <script>
    const ordersDir = {{ orders_dir|tojson }};
    const labelDir = {{ label_dir|tojson }};
    const settings = {{ settings|tojson }};
    const fileInput = document.getElementById('file-input');
    const fileLabel = document.getElementById('file-label');
    const filePicker = document.getElementById('file-picker');
    const testToggle = document.getElementById('test-toggle');
    const fulfillBtn = document.getElementById('fulfill-btn');
    const returnBtn = document.getElementById('return-btn');
    const settingsModal = document.getElementById('settings-modal');

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
      const done = stats.done || stats.Done || 0;
      const failed = stats.failed || stats.Failed || 0;
      const total = Object.values(stats || {}).reduce((acc, val) => acc + (Number(val) || 0), 0);
      statEl.innerHTML = `
        <div class="stat"><label>Totalt</label><strong>${total}</strong></div>
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

    function renderDownloads(payload) {
      const container = document.getElementById('downloads');
      const mergedUrl = payload.merged_label_url;
      const mergedName = payload.merged_label_name;
      const labelUrls = payload.label_urls || [];
      const labelNames = payload.label_names || [];
      const testMode = payload.test_mode;
      const isReturn = payload.return_label;

      const makeButton = (url, text, secondary = false) =>
        `<div class="download-actions"><a href="${url}" class="btn ${secondary ? 'secondary' : ''}" style="text-decoration:none;">${text}</a></div>`;

      if (mergedUrl && mergedName) {
        const tag = testMode ? '<span class="badge fail" style="margin-left:6px;">Test</span>' : '';
        container.innerHTML = `
          <div class="download-item">
            <div class="download-name">${mergedName}${tag}</div>
            ${makeButton(mergedUrl, 'Last ned PDF')}
          </div>
        `;
        fulfillBtn.disabled = isReturn;
        return;
      }
      if (labelUrls.length) {
        container.innerHTML = labelUrls.map((url, idx) => {
          const name = labelNames[idx] || url.split('/').pop();
          return `
            <div class="download-item">
              <div class="download-name">${name}</div>
              ${makeButton(url, 'Last ned etikett', true)}
            </div>
          `;
        }).join('');
        fulfillBtn.disabled = isReturn;
        return;
      }
      container.innerHTML = `
        <div class="download-item">
          <div class="download-name">Ingen etikett generert ennå</div>
          <div class="download-actions">
            <button class="secondary" disabled>Last ned</button>
          </div>
        </div>
      `;
      fulfillBtn.disabled = true;
    }

    async function uploadAndProcess(formEl, isTest, isReturn, btnOverride) {
      const formData = new FormData(formEl);
      const btn = btnOverride || formEl.querySelector('button[type="submit"]');
      if (!fileInput.files?.length) {
        toast('Velg eller dra inn en CSV først', 'error');
        return;
      }
      const originalLabel = btn.textContent;
      btn.disabled = true;
      btn.textContent = 'Jobber...';
      try {
        const uploadRes = await fetch('/api/upload', { method: 'POST', body: formData });
        const uploadData = await uploadRes.json();
        if (!uploadData.ok) throw new Error(uploadData.error || 'Ukjent feil ved opplasting');
        const added = Array.isArray(uploadData.orders_added) ? uploadData.orders_added.length : 0;

        const procRes = await fetch(`/api/process?test=${isTest ? 'true' : 'false'}&return_label=${isReturn ? 'true' : 'false'}`, { method: 'POST' });
        const procData = await procRes.json();
        if (!procData.ok) throw new Error(procData.error || 'Ukjent feil ved kjøring');
        const modeText = isReturn ? 'returetiketter' : 'etiketter';
        toast(`La til ${added} jobber og kjørte ${procData.processed_jobs || 0} ${modeText}${isTest ? ' (testmodus)' : ''}.`);
        if (procData.errors && procData.errors.length) {
            toast(`Noen jobber feilet: ${procData.errors.join('; ').slice(0, 200)}`, 'error');
        }
        renderDownloads(procData);
        loadJobs();
      } catch (err) {
        toast(err.message, 'error');
      } finally {
        btn.disabled = false;
        btn.textContent = originalLabel || 'Lag etikett';
        formEl.reset();
      }
    }

    document.getElementById('upload-form').addEventListener('submit', (ev) => {
      ev.preventDefault();
      uploadAndProcess(ev.target, !!testToggle.checked, false, ev.submitter || undefined);
    });

    returnBtn.addEventListener('click', (ev) => {
      ev.preventDefault();
      uploadAndProcess(document.getElementById('upload-form'), !!testToggle.checked, true, returnBtn);
    });

    fulfillBtn.addEventListener('click', async () => {
      fulfillBtn.disabled = true;
      fulfillBtn.textContent = 'Fulfiller...';
      try {
        const res = await fetch('/api/fulfill', { method: 'POST' });
        const data = await res.json();
        if (!data.ok) throw new Error(data.error || 'Ukjent feil ved fulfillment');
        toast(`Fulfilled ${data.processed_jobs || 0} jobber i Shopify.`);
        if (data.errors && data.errors.length) {
          toast(`Noen jobber feilet: ${data.errors.join('; ').slice(0, 200)}`, 'error');
        }
        loadJobs();
      } catch (err) {
        toast(err.message, 'error');
      } finally {
        fulfillBtn.textContent = 'Fulfill ordre i Shopify';
      }
    });

    // Settings modal
    function openSettings() {
      settingsModal.classList.add('active');
      setSettingsForm(settings);
    }
    function closeSettings() {
      settingsModal.classList.remove('active');
    }
    function setSettingsForm(data) {
      document.getElementById('set-return-name').value = data.BRING_RETURN_NAME || '';
      document.getElementById('set-return-address').value = data.BRING_RETURN_ADDRESS || '';
      document.getElementById('set-return-address2').value = data.BRING_RETURN_ADDRESS2 || '';
      document.getElementById('set-return-postal').value = data.BRING_RETURN_POSTAL || '';
      document.getElementById('set-return-city').value = data.BRING_RETURN_CITY || '';
      document.getElementById('set-return-country').value = data.BRING_RETURN_COUNTRY || '';
      document.getElementById('set-return-email').value = data.BRING_RETURN_EMAIL || '';
      document.getElementById('set-return-phone').value = data.BRING_RETURN_PHONE || '';
    }
    async function saveSettings() {
      const payload = {
        BRING_RETURN_NAME: document.getElementById('set-return-name').value,
        BRING_RETURN_ADDRESS: document.getElementById('set-return-address').value,
        BRING_RETURN_ADDRESS2: document.getElementById('set-return-address2').value,
        BRING_RETURN_POSTAL: document.getElementById('set-return-postal').value,
        BRING_RETURN_CITY: document.getElementById('set-return-city').value,
        BRING_RETURN_COUNTRY: document.getElementById('set-return-country').value,
        BRING_RETURN_EMAIL: document.getElementById('set-return-email').value,
        BRING_RETURN_PHONE: document.getElementById('set-return-phone').value,
      };
      try {
        const res = await fetch('/api/settings', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        const data = await res.json();
        if (!data.ok) throw new Error(data.error || 'Kunne ikke lagre settings');
        setSettingsForm(data.settings || {});
        toast('Lagret innstillinger for returadresse.');
        closeSettings();
      } catch (err) {
        toast(err.message, 'error');
      }
    }

    document.getElementById('settings-btn').addEventListener('click', openSettings);
    document.getElementById('settings-cancel').addEventListener('click', closeSettings);
    document.getElementById('settings-save').addEventListener('click', saveSettings);
    settingsModal.addEventListener('click', (ev) => {
      if (ev.target === settingsModal) closeSettings();
    });

    // Vis en deaktivert knapp fra start
    renderDownloads({ merged_label_url: null, merged_label_name: null, label_urls: [], label_names: [], test_mode: false });

    function setFileLabel(text) {
      fileLabel.textContent = text || 'Slipp CSV her eller velg fil';
    }

    fileInput.addEventListener('change', () => {
      const f = fileInput.files?.[0];
      setFileLabel(f ? f.name : null);
    });

    ['dragenter','dragover'].forEach(evt => {
      filePicker.addEventListener(evt, (e) => {
        e.preventDefault(); e.stopPropagation();
        filePicker.classList.add('dragging');
      });
    });
    ['dragleave','drop'].forEach(evt => {
      filePicker.addEventListener(evt, (e) => {
        e.preventDefault(); e.stopPropagation();
        filePicker.classList.remove('dragging');
      });
    });
    filePicker.addEventListener('drop', (e) => {
      const dt = e.dataTransfer;
      if (!dt || !dt.files || !dt.files.length) return;
      const csv = Array.from(dt.files).find(f => f.name.toLowerCase().endsWith('.csv'));
      if (!csv) {
        toast('Dra inn en CSV-fil', 'error');
        return;
      }
      const dataTransfer = new DataTransfer();
      dataTransfer.items.add(csv);
      fileInput.files = dataTransfer.files;
      setFileLabel(csv.name);
    });

    document.getElementById('refresh-btn').addEventListener('click', () => {
      try {
        loadJobs();
      } catch (err) {
        toast('Kunne ikke oppdatere: ' + err.message, 'error');
      }
    });

    loadJobs();
    setInterval(loadJobs, 8000);
  </script>
</body>
</html>
"""


if __name__ == "__main__":
    port = int(os.getenv("PACKCHICKEN_GUI_PORT", "5050"))
    app.run(host="0.0.0.0", port=port, debug=False)
