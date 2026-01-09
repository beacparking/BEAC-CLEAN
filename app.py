from flask import Flask, render_template, request
import sqlite3
import qrcode
import os
from datetime import datetime

app = Flask(__name__)

DB = "vehicles.db"
QR_FOLDER = "static/qr"
os.makedirs(QR_FOLDER, exist_ok=True)

# ---------- DATABASE INIT ----------
def init_db():
    with sqlite3.connect(DB) as conn:
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS vehicles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vehicle TEXT NOT NULL,
                expiry TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        conn.commit()

init_db()

# ---------- HOME + QR GENERATION ----------
@app.route("/", methods=["GET", "POST"])
def index():
    qr_image = None
    verify_url = None

    if request.method == "POST":
        vehicle = request.form["vehicle"].strip()
        expiry = request.form["expiry"]

        with sqlite3.connect(DB) as conn:
            c = conn.cursor()
            c.execute(
                "INSERT INTO vehicles (vehicle, expiry, created_at) VALUES (?, ?, ?)",
                (vehicle, expiry, datetime.utcnow().isoformat())
            )
            token_id = c.lastrowid
            conn.commit()

        verify_url = f"https://beac-vehicle-qr-clean.onrender.com/verify/{token_id}"

        qr_path = f"{QR_FOLDER}/{token_id}.png"
        qrcode.make(verify_url).save(qr_path)

        qr_image = qr_path

    return render_template("index.html", qr_image=qr_image, verify_url=verify_url)

# ---------- VERIFY BY TOKEN ----------
@app.route("/verify/<int:token>")
def verify(token):
    with sqlite3.connect(DB) as conn:
        c = conn.cursor()
        c.execute("SELECT vehicle, expiry FROM vehicles WHERE id=?", (token,))
        row = c.fetchone()

    if not row:
        return "Invalid QR", 404

    vehicle, expiry = row
    today = datetime.today().date()
    expiry_date = datetime.strptime(expiry, "%Y-%m-%d").date()

    status = "VALID" if expiry_date >= today else "EXPIRED"

    return render_template(
        "verify.html",
        vehicle=vehicle,
        expiry=expiry,
        status=status,
        token=token
    )

# ---------- RUN ----------
if __name__ == "__main__":
    app.run()