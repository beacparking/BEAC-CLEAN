from flask import Flask, render_template, request, redirect, url_for, session, send_file
import sqlite3
import qrcode
import os
from datetime import datetime
import csv

app = Flask(__name__)
app.secret_key = "bea-secret-key"

DB = "data.db"

# ---------------- INIT ----------------
def init_db():
    with sqlite3.connect(DB) as con:
        con.execute("""
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vehicle TEXT,
            expiry TEXT,
            created TEXT
        )
        """)
init_db()

# ---------------- AUTH ----------------
USERNAME = "admin"
PASSWORD = "1234"

# ---------------- LOGIN ----------------
@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form["username"] == USERNAME and request.form["password"] == PASSWORD:
            session["admin"] = True
            return redirect("/admin")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

# ---------------- ADMIN ----------------
@app.route("/admin", methods=["GET", "POST"])
def admin():
    if not session.get("admin"):
        return redirect("/")

    qr_url = None

    if request.method == "POST":
        vehicle = request.form["vehicle"]
        expiry = request.form["expiry"]
        created = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Save DB
        with sqlite3.connect(DB) as con:
            con.execute(
                "INSERT INTO logs (vehicle, expiry, created) VALUES (?,?,?)",
                (vehicle, expiry, created)
            )

        # Build QR URL
        qr_url = request.url_root + "verify/" + vehicle

        # Ensure static folder
        if not os.path.exists("static"):
            os.makedirs("static")

        # Generate QR
        img = qrcode.make(qr_url)
        img.save("static/qr.png")

    return render_template("admin.html", qr=qr_url)

# ---------------- VERIFY ----------------
@app.route("/verify/<vehicle>")
def verify(vehicle):
    with sqlite3.connect(DB) as con:
        row = con.execute(
            "SELECT expiry FROM logs WHERE vehicle=? ORDER BY id DESC LIMIT 1",
            (vehicle,)
        ).fetchone()

    if not row:
        return "INVALID QR"

    expiry = row[0]
    today = datetime.now().date()
    exp_date = datetime.strptime(expiry, "%Y-%m-%d").date()

    status = "VALID" if today <= exp_date else "EXPIRED"

    return render_template(
        "verify.html",
        vehicle=vehicle,
        expiry=expiry,
        status=status
    )

# ---------------- EXPORT HELPERS ----------------
def export_csv(rows, filename):
    path = f"/tmp/{filename}"
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Vehicle", "Expiry", "Created"])
        writer.writerows(rows)
    return send_file(path, as_attachment=True)

# ---------------- EXPORT DAY ----------------
@app.route("/export/day")
def export_day():
    date = request.args.get("date")
    with sqlite3.connect(DB) as con:
        rows = con.execute(
            "SELECT vehicle, expiry, created FROM logs WHERE DATE(created)=?",
            (date,)
        ).fetchall()
    return export_csv(rows, "day.csv")

# ---------------- EXPORT MONTH ----------------
@app.route("/export/month")
def export_month():
    month = request.args.get("month")
    with sqlite3.connect(DB) as con:
        rows = con.execute(
            "SELECT vehicle, expiry, created FROM logs WHERE substr(created,1,7)=?",
            (month,)
        ).fetchall()
    return export_csv(rows, "month.csv")

# ---------------- EXPORT YEAR ----------------
@app.route("/export/year")
def export_year():
    year = request.args.get("year")
    with sqlite3.connect(DB) as con:
        rows = con.execute(
            "SELECT vehicle, expiry, created FROM logs WHERE substr(created,1,4)=?",
            (year,)
        ).fetchall()
    return export_csv(rows, "year.csv")

# ---------------- RUN ----------------
if __name__ == "__main__":
    app.run(debug=True)