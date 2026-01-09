from flask import Flask, render_template, request, redirect, url_for, abort
import sqlite3
import qrcode
import os
from datetime import datetime, date

app = Flask(__name__)

DB_PATH = "vehicles.db"
QR_FOLDER = "static/qr"
QR_VERSION = 1  # 🔒 QR VERSION LOCK

os.makedirs(QR_FOLDER, exist_ok=True)

# -----------------------------
# DATABASE INIT (VERY IMPORTANT)
# -----------------------------
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS vehicles (
            vehicle TEXT PRIMARY KEY,
            expiry TEXT,
            version INTEGER,
            created_at TEXT
        )
    """)
    conn.commit()
    conn.close()

init_db()  # 👈 THIS FIXES YOUR ERROR

# -----------------------------
# HOME / GENERATE QR
# -----------------------------
@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        vehicle = request.form.get("vehicle", "").strip().upper()
        expiry = request.form.get("expiry", "").strip()

        if not vehicle or not expiry:
            abort(400)

        conn = get_db()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT OR REPLACE INTO vehicles (vehicle, expiry, version, created_at)
            VALUES (?, ?, ?, ?)
        """, (
            vehicle,
            expiry,
            QR_VERSION,
            datetime.utcnow().isoformat()
        ))

        conn.commit()
        conn.close()

        verify_url = url_for(
            "verify",
            vehicle=vehicle,
            version=QR_VERSION,
            _external=True
        )

        qr_img = qrcode.make(verify_url)
        qr_path = os.path.join(QR_FOLDER, f"{vehicle}_v{QR_VERSION}.png")
        qr_img.save(qr_path)

        return render_template(
            "index.html",
            qr_image=qr_path,
            verify_url=verify_url
        )

    return render_template("index.html")

# -----------------------------
# LOCKED VERIFY ROUTE
# -----------------------------
@app.route("/verify/<vehicle>/v<int:version>")
def verify(vehicle, version):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT * FROM vehicles
        WHERE vehicle = ? AND version = ?
    """, (vehicle.upper(), version))

    row = cursor.fetchone()
    conn.close()

    if not row:
        abort(404)

    expiry_date = datetime.strptime(row["expiry"], "%Y-%m-%d").date()
    today = date.today()

    if today > expiry_date:
        status = "EXPIRED"
        warning = "This QR has expired."
    elif (expiry_date - today).days <= 2:
        status = "VALID (EXPIRING SOON)"
        warning = "⚠ This QR will expire soon."
    else:
        status = "VALID"
        warning = None

    return render_template(
        "verify.html",
        vehicle=vehicle,
        expiry=row["expiry"],
        status=status,
        warning=warning,
        version=version
    )

# -----------------------------
# BLOCK EVERYTHING ELSE
# -----------------------------
@app.errorhandler(404)
def not_found(e):
    return "QR route not found or invalid.", 404

@app.errorhandler(500)
def server_error(e):
    return "Internal server error. Please contact administrator.", 500

# -----------------------------
# RUN (LOCAL ONLY)
# -----------------------------
if __name__ == "__main__":
    app.run(debug=True)