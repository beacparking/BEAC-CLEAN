from flask import Flask, render_template, request, redirect, url_for, session, send_file
import psycopg2
import os
import qrcode
from datetime import datetime
import csv
import tempfile

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "bea_secret_key")

# -----------------------------
# DATABASE
# -----------------------------
DATABASE_URL = os.environ.get("DATABASE_URL")

def get_db():
    return psycopg2.connect(DATABASE_URL, sslmode="require")

def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS vehicle_logs (
            id SERIAL PRIMARY KEY,
            vehicle_number TEXT NOT NULL,
            log_date DATE NOT NULL,
            qr_data TEXT NOT NULL
        )
    """)
    conn.commit()
    cur.close()
    conn.close()

init_db()

# -----------------------------
# AUTH
# -----------------------------
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin123"

@app.route("/")
def root():
    return redirect(url_for("login"))

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if (
            request.form.get("username") == ADMIN_USERNAME
            and request.form.get("password") == ADMIN_PASSWORD
        ):
            session["logged_in"] = True
            return redirect(url_for("admin"))
        return render_template("login.html", error="Invalid credentials")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# -----------------------------
# ADMIN
# -----------------------------
@app.route("/admin")
def admin():
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    return render_template("admin.html")

# -----------------------------
# GENERATE QR
# -----------------------------
@app.route("/generate", methods=["POST"])
def generate():
    if not session.get("logged_in"):
        return redirect(url_for("login"))

    vehicle = request.form.get("vehicle_number")
    log_date = request.form.get("date")

    if not vehicle:
        return redirect(url_for("admin"))

    if not log_date:
        log_date = datetime.now().date()

    # QR data
    qr_data = f"{vehicle}|{log_date}"

    # Create QR folder if not exists
    qr_dir = os.path.join("static", "qr")
    os.makedirs(qr_dir, exist_ok=True)

    qr_filename = f"{vehicle}_{log_date}.png"
    qr_path = os.path.join(qr_dir, qr_filename)

    # Generate QR image
    img = qrcode.make(qr_data)
    img.save(qr_path)

    # Save to PostgreSQL
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO vehicle_logs (vehicle, log_date, qr_data)
        VALUES (%s, %s, %s)
        """,
        (vehicle, log_date, qr_filename)
    )
    conn.commit()
    cur.close()
    conn.close()

    return redirect(url_for("admin"))

# -----------------------------
# EXPORT HELPERS
# -----------------------------
def export_csv(rows):
    temp = tempfile.NamedTemporaryFile(delete=False, suffix=".csv")
    with open(temp.name, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Vehicle Number", "Date", "QR Data"])
        for r in rows:
            writer.writerow(r)
    return temp.name

# -----------------------------
# EXPORT ROUTES (MATCH UI)
# -----------------------------
@app.route("/export/day")
def export_day():
    date = request.args.get("date")

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT vehicle, log_date, qr_data FROM vehicle_logs WHERE log_date=%s",
        (date,)
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()

    return send_file(export_csv(rows), as_attachment=True)


@app.route("/export/month")
def export_month():
    month = request.args.get("month")
    year = request.args.get("year")

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT vehicle, log_date, qr_data
        FROM vehicle_logs
        WHERE EXTRACT(MONTH FROM log_date)=%s
        AND EXTRACT(YEAR FROM log_date)=%s
        """,
        (month, year)
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()

    return send_file(export_csv(rows), as_attachment=True)


@app.route("/export/year")
def export_year():
    year = request.args.get("year")

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT vehicle, log_date, qr_data
        FROM vehicle_logs
        WHERE EXTRACT(YEAR FROM log_date)=%s
        """,
        (year,)
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()

    return send_file(export_csv(rows), as_attachment=True)