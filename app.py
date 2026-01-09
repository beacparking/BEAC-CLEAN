from flask import Flask, render_template, request, redirect, url_for, abort
import sqlite3
import qrcode
import os
from datetime import datetime, date

app = Flask(__name__)

DB = "vehicles.db"
QR_FOLDER = "static/qr"
QR_VERSION = "v1"   # 🔒 QR VERSION (do not change once live)

os.makedirs(QR_FOLDER, exist_ok=True)

# ------------------------
# DATABASE
# ------------------------
def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

# ------------------------
# HOME (QR GENERATION)
# ------------------------
@app.route("/", methods=["GET", "POST"])
def index():
    qr_file = None

    if request.method == "POST":
        vehicle = request.form["vehicle"].strip().upper()
        expiry = request.form["expiry"]

        if not vehicle or not expiry:
            return redirect(url_for("index"))

        conn = get_db()
        conn.execute(
            "INSERT OR REPLACE INTO vehicles (vehicle, expiry) VALUES (?, ?)",
            (vehicle, expiry)
        )
        conn.commit()
        conn.close()

        qr_url = url_for("verify", version=QR_VERSION, vehicle=vehicle, _external=True)
        qr_path = f"{QR_FOLDER}/{QR_VERSION}_{vehicle}.png"

        qrcode.make(qr_url).save(qr_path)
        qr_file = qr_path

    return render_template("index.html", qr_file=qr_file)

# ------------------------
# 🔒 LOCKED VERIFY ROUTE
# ------------------------
@app.route("/verify/<version>/<vehicle>")
def verify(version, vehicle):
    if version != QR_VERSION:
        abort(404)   # 🔒 Old or tampered QR blocked forever

    conn = get_db()
    row = conn.execute(
        "SELECT * FROM vehicles WHERE vehicle=?",
        (vehicle.upper(),)
    ).fetchone()
    conn.close()

    if not row:
        abort(404)

    expiry_date = datetime.strptime(row["expiry"], "%Y-%m-%d").date()
    today = date.today()
    days_left = (expiry_date - today).days

    if days_left < 0:
        status = "EXPIRED"
        color = "red"
        warning = "❌ Vehicle validity has expired"
    elif days_left <= 2:
        status = "EXPIRING SOON"
        color = "orange"
        warning = f"⚠️ Expires in {days_left} day(s)"
    else:
        status = "VALID"
        color = "green"
        warning = None

    return render_template(
        "verify.html",
        vehicle=vehicle,
        expiry=row["expiry"],
        status=status,
        color=color,
        warning=warning,
        version=version
    )

# ------------------------
if __name__ == "__main__":
    app.run(debug=True)