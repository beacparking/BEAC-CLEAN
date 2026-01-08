from flask import Flask, render_template, request
import sqlite3
import qrcode
import os
from datetime import datetime

app = Flask(__name__)

DB_NAME = "vehicles.db"
QR_FOLDER = os.path.join("static", "qr")

# ------------------ INIT ------------------
os.makedirs(QR_FOLDER, exist_ok=True)

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS vehicles (
            vehicle_number TEXT PRIMARY KEY,
            expiry_date TEXT
        )
    """)
    conn.commit()
    conn.close()

init_db()

# ------------------ HOME ------------------
@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")

# ------------------ GENERATE QR ------------------
@app.route("/generate", methods=["POST"])
def generate():
    vehicle_number = request.form.get("vehicle_number")
    expiry_date = request.form.get("expiry_date")

    if not vehicle_number or not expiry_date:
        return "Missing data", 400

    # Save to DB
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute(
        "INSERT OR REPLACE INTO vehicles (vehicle_number, expiry_date) VALUES (?, ?)",
        (vehicle_number.upper(), expiry_date)
    )
    conn.commit()
    conn.close()

    # Create QR
    qr_data = f"{request.host_url}verify/{vehicle_number.upper()}"
    qr_path = os.path.join(QR_FOLDER, f"{vehicle_number.upper()}.png")

    img = qrcode.make(qr_data)
    img.save(qr_path)

    return render_template(
        "index.html",
        qr_image=f"/static/qr/{vehicle_number.upper()}.png"
    )

# ------------------ VERIFY ------------------
@app.route("/verify/<vehicle_number>", methods=["GET"])
def verify(vehicle_number):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute(
        "SELECT expiry_date FROM vehicles WHERE vehicle_number = ?",
        (vehicle_number.upper(),)
    )
    row = c.fetchone()
    conn.close()

    if not row:
        return render_template(
            "verify.html",
            vehicle=vehicle_number,
            expiry="N/A",
            status="INVALID"
        )

    expiry = datetime.strptime(row[0], "%Y-%m-%d").date()
    today = datetime.today().date()

    status = "VALID" if expiry >= today else "EXPIRED"

    return render_template(
        "verify.html",
        vehicle=vehicle_number,
        expiry=row[0],
        status=status
    )

# ------------------ RUN ------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)