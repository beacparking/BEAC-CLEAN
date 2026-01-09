from flask import Flask, render_template, request, redirect, session, url_for, send_file
import sqlite3
import qrcode
import os
from datetime import datetime
from openpyxl import Workbook
import io

app = Flask(__name__)
app.secret_key = "beac_secret_key"

DB = "database.db"

# ------------------ DATABASE INIT ------------------
def init_db():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS vehicles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vehicle TEXT,
            expiry DATE,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

init_db()

# ------------------ LOGIN ------------------
ADMIN_USER = "admin"
ADMIN_PASS = "1234"

@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form["username"] == ADMIN_USER and request.form["password"] == ADMIN_PASS:
            session["admin"] = True
            return redirect("/admin")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

# ------------------ ADMIN DASHBOARD ------------------
@app.route("/admin", methods=["GET", "POST"])
def admin():
    if not session.get("admin"):
        return redirect("/")

    qr_url = None

    if request.method == "POST":
        vehicle = request.form["vehicle"]
        expiry = request.form["expiry"]

        conn = sqlite3.connect(DB)
        cur = conn.cursor()
        cur.execute("INSERT INTO vehicles (vehicle, expiry) VALUES (?, ?)", (vehicle, expiry))
        vid = cur.lastrowid
        conn.commit()
        conn.close()

        qr_url = f"https://beac-vehicle-qr-clean.onrender.com/verify/{vid}"

        img = qrcode.make(qr_url)
        img.save("static/qr.png")

    return render_template("admin.html", qr=qr_url)

# ------------------ VERIFY ------------------
@app.route("/verify/<int:vid>")
def verify(vid):
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute("SELECT vehicle, expiry FROM vehicles WHERE id=?", (vid,))
    row = cur.fetchone()
    conn.close()

    if not row:
        return "Invalid QR"

    return render_template("verify.html",
                           vehicle=row[0],
                           expiry=row[1])

# ------------------ EXCEL EXPORT COMMON ------------------
def generate_excel(rows, filename):
    wb = Workbook()
    ws = wb.active
    ws.append(["Vehicle Number", "Expiry Date", "Generated Time"])

    for r in rows:
        ws.append(r)

    file = io.BytesIO()
    wb.save(file)
    file.seek(0)

    return send_file(file, as_attachment=True, download_name=filename)

# ------------------ EXPORT DAY ------------------
@app.route("/export/day")
def export_day():
    date = request.args.get("date")

    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute("SELECT vehicle, expiry, created_at FROM vehicles WHERE DATE(created_at)=?", (date,))
    rows = cur.fetchall()
    conn.close()

    return generate_excel(rows, f"vehicle_day_{date}.xlsx")

# ------------------ EXPORT MONTH ------------------
@app.route("/export/month")
def export_month():
    month = request.args.get("month")

    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute("SELECT vehicle, expiry, created_at FROM vehicles WHERE strftime('%Y-%m', created_at)=?", (month,))
    rows = cur.fetchall()
    conn.close()

    return generate_excel(rows, f"vehicle_month_{month}.xlsx")

# ------------------ EXPORT YEAR ------------------
@app.route("/export/year")
def export_year():
    year = request.args.get("year")

    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute("SELECT vehicle, expiry, created_at FROM vehicles WHERE strftime('%Y', created_at)=?", (year,))
    rows = cur.fetchall()
    conn.close()

    return generate_excel(rows, f"vehicle_year_{year}.xlsx")

if __name__ == "__main__":
    app.run(debug=True)