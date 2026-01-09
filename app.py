from flask import Flask, render_template, request, redirect, session, url_for
import sqlite3
import qrcode
import os
from datetime import date

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "beac-secret-key")

DB = "vehicles.db"

# ------------------ DB INIT ------------------
def init_db():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS vehicles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vehicle TEXT UNIQUE,
            expiry TEXT
        )
    """)
    conn.commit()
    conn.close()

init_db()

# ------------------ LOGIN ------------------
@app.route("/")
def home():
    if session.get("logged_in"):
        return redirect("/dashboard")
    return render_template("login.html")

@app.route("/login", methods=["POST"])
def login():
    username = request.form["username"]
    password = request.form["password"]

    # CHANGE THESE LATER
    if username == "admin" and password == "beac123":
        session["logged_in"] = True
        return redirect("/dashboard")

    return render_template("login.html", error="Invalid credentials")

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

# ------------------ DASHBOARD (ADMIN ONLY) ------------------
@app.route("/dashboard", methods=["GET", "POST"])
def dashboard():
    if not session.get("logged_in"):
        return redirect("/")

    qr_url = None

    if request.method == "POST":
        vehicle = request.form["vehicle"]
        expiry = request.form["expiry"]

        conn = sqlite3.connect(DB)
        c = conn.cursor()
        c.execute(
            "INSERT OR REPLACE INTO vehicles (vehicle, expiry) VALUES (?, ?)",
            (vehicle, expiry)
        )
        conn.commit()
        conn.close()

        qr_url = f"{request.host_url}verify/{vehicle}"

        img = qrcode.make(qr_url)
        img.save("static/qr.png")

    return render_template("index.html", qr_url=qr_url)

# ------------------ VERIFY (PUBLIC) ------------------
@app.route("/verify/<vehicle>")
def verify(vehicle):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT expiry FROM vehicles WHERE vehicle = ?", (vehicle,))
    row = c.fetchone()
    conn.close()

    if not row:
        return "❌ INVALID QR", 404

    expiry = row[0]
    status = "VALID" if expiry >= str(date.today()) else "EXPIRED"

    return render_template(
        "verify.html",
        vehicle=vehicle,
        expiry=expiry,
        status=status
    )

# ------------------
if __name__ == "__main__":
    app.run()