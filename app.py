from flask import Flask, render_template, request, redirect, url_for, send_file
import psycopg2
import os
import qrcode
from datetime import datetime, date
import csv

app = Flask(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL")

def get_db():
    return psycopg2.connect(DATABASE_URL, sslmode="require")

# ----------------- INIT DB -----------------
def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS vehicle_logs (
            id SERIAL PRIMARY KEY,
            vehicle TEXT NOT NULL,
            expiry DATE NOT NULL,
            created_at TIMESTAMP NOT NULL
        )
    """)
    conn.commit()
    cur.close()
    conn.close()

init_db()

# ----------------- LOGIN (unchanged) -----------------
@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form["username"] == "admin" and request.form["password"] == "admin123":
            return redirect("/admin")
    return render_template("login.html")

@app.route("/logout")
def logout():
    return redirect("/")

# ----------------- ADMIN -----------------
@app.route("/admin", methods=["GET", "POST"])
def admin():
    qr = None

    if request.method == "POST":
        vehicle = request.form["vehicle"]
        expiry = request.form["expiry"]
        created = datetime.now()

        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO vehicle_logs (vehicle, expiry, created_at) VALUES (%s, %s, %s) RETURNING id",
            (vehicle, expiry, created)
        )
        qr_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        conn.close()

        qr_url = f"{request.url_root}verify/{qr_id}"
        img = qrcode.make(qr_url)
        img.save("static/qr.png")
        qr = qr_url

    return render_template("admin.html", qr=qr)

# ----------------- VERIFY -----------------
@app.route("/verify/<int:qr_id>")
def verify(qr_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT vehicle, expiry, created_at FROM vehicle_logs WHERE id=%s", (qr_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()

    if not row:
        return "INVALID QR"

    vehicle, expiry, created = row
    status = "VALID" if date.today() <= expiry else "EXPIRED"

    return render_template(
        "verify.html",
        vehicle=vehicle,
        expiry=expiry,
        created=created,
        status=status
    )

# ----------------- EXPORT CSV -----------------
def export_csv(rows, filename):
    path = f"/tmp/{filename}"
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Vehicle", "Expiry", "Generated At"])
        writer.writerows(rows)
    return send_file(path, as_attachment=True)

@app.route("/export/day")
def export_day():
    date_q = request.args.get("date")
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT vehicle, expiry, created_at FROM vehicle_logs WHERE DATE(created_at)=%s", (date_q,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return export_csv(rows, "day.csv")

@app.route("/export/month")
def export_month():
    month = request.args.get("month")
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT vehicle, expiry, created_at FROM vehicle_logs WHERE TO_CHAR(created_at,'YYYY-MM')=%s",
        (month,)
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return export_csv(rows, "month.csv")

@app.route("/export/year")
def export_year():
    year = request.args.get("year")
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT vehicle, expiry, created_at FROM vehicle_logs WHERE EXTRACT(YEAR FROM created_at)=%s",
        (year,)
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return export_csv(rows, "year.csv")

if __name__ == "__main__":
    app.run()