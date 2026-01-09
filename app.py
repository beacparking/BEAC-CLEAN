from flask import Flask, render_template, request, redirect, session, abort
import sqlite3
import qrcode
import io
import base64
from datetime import datetime
import os

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "beac-secret-key")

DB_FILE = "vehicles.db"

# ---------- DB INIT ----------
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS vehicles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vehicle TEXT NOT NULL,
            expiry TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

init_db()

# ---------- LOGIN ----------
@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form["username"] == "admin" and request.form["password"] == "admin123":
            session["admin"] = True
            return redirect("/dashboard")
        return render_template("login.html", error="Invalid credentials")
    return render_template("login.html")

# ---------- DASHBOARD ----------
@app.route("/dashboard", methods=["GET", "POST"])
def dashboard():
    if not session.get("admin"):
        return redirect("/")

    qr_image = None
    qr_url = None

    if request.method == "POST":
        vehicle = request.form["vehicle"]
        expiry = request.form["expiry"]

        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("INSERT INTO vehicles (vehicle, expiry) VALUES (?, ?)", (vehicle, expiry))
        vid = c.lastrowid
        conn.commit()
        conn.close()

        qr_url = request.host_url + f"verify/{vid}"

        # 🔐 Generate QR in memory (NO FILE WRITE)
        img = qrcode.make(qr_url)
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        qr_image = base64.b64encode(buffer.getvalue()).decode()

    return render_template("index.html", qr_image=qr_image, qr_url=qr_url)

# ---------- VERIFY ----------
@app.route("/verify/<int:vid>")
def verify(vid):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT vehicle, expiry FROM vehicles WHERE id=?", (vid,))
    row = c.fetchone()
    conn.close()

    if not row:
        abort(404)

    vehicle, expiry = row
    today = datetime.today().date()
    expiry_date = datetime.strptime(expiry, "%Y-%m-%d").date()
    status = "VALID" if expiry_date >= today else "EXPIRED"

    return render_template("verify.html", vehicle=vehicle, expiry=expiry, status=status)

# ---------- LOGOUT ----------
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

if __name__ == "__main__":
    app.run()