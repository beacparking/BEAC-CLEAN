from flask import Flask, render_template, request, redirect, url_for
from werkzeug.middleware.proxy_fix import ProxyFix
import sqlite3
import qrcode
import os
from datetime import datetime

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

DB_NAME = "vehicles.db"
QR_FOLDER = "static/qr"

os.makedirs(QR_FOLDER, exist_ok=True)

# ---------- DATABASE ----------
def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS vehicles (
            vehicle_no TEXT PRIMARY KEY,
            expiry TEXT
        )
    """)
    conn.commit()
    conn.close()

init_db()

# ---------- ROUTES ----------

@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")

@app.route("/verify", methods=["POST"])
def verify_post():
    vehicle_no = request.form.get("vehicle_no", "").strip().upper()
    if not vehicle_no:
        return redirect(url_for("index"))
    return redirect(url_for("verify_result", vehicle_no=vehicle_no))

@app.route("/verify/<vehicle_no>", methods=["GET"])
def verify_result(vehicle_no):
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM vehicles WHERE vehicle_no = ?",
        (vehicle_no.upper(),)
    ).fetchone()
    conn.close()

    if not row:
        return render_template(
            "verify.html",
            vehicle="N/A",
            expiry="N/A",
            status="INVALID"
        )

    expiry_date = datetime.strptime(row["expiry"], "%Y-%m-%d")
    today = datetime.today()

    status = "VALID" if expiry_date >= today else "EXPIRED"

    return render_template(
        "verify.html",
        vehicle=row["vehicle_no"],
        expiry=row["expiry"],
        status=status
    )

@app.route("/dashboard", methods=["GET", "POST"])
def dashboard():
    if request.method == "POST":
        vehicle_no = request.form["vehicle_no"].strip().upper()
        expiry = request.form["expiry"]

        conn = get_db()
        conn.execute(
            "INSERT OR REPLACE INTO vehicles (vehicle_no, expiry) VALUES (?, ?)",
            (vehicle_no, expiry)
        )
        conn.commit()
        conn.close()

        qr_url = request.url_root.rstrip("/") + url_for(
            "verify_result", vehicle_no=vehicle_no
        )

        img = qrcode.make(qr_url)
        img.save(f"{QR_FOLDER}/{vehicle_no}.png")

    return render_template("dashboard.html")

# ---------- START ----------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)