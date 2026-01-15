from flask import Flask, render_template, request, redirect, url_for, session, send_file
import psycopg2
import os
from datetime import datetime
import qrcode
import csv
import io

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "bea_secret_key")

# -----------------------------
# CONFIG
# -----------------------------
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin123"

DATABASE_URL = os.environ.get("DATABASE_URL")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
QR_FOLDER = os.path.join(BASE_DIR, "static", "qr")
os.makedirs(QR_FOLDER, exist_ok=True)

# -----------------------------
# DB CONNECTION
# -----------------------------
def get_db():
    return psycopg2.connect(DATABASE_URL)

# -----------------------------
# LOGIN
# -----------------------------
@app.route("/")
def home():
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

# -----------------------------
# ADMIN
# -----------------------------
@app.route("/admin")
def admin():
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    return render_template("admin.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# -----------------------------
# GENERATE QR
# -----------------------------
@app.route("/generate", methods=["POST"])
def generate_qr():
    if not session.get("logged_in"):
        return redirect(url_for("login"))

    vehicle = request.form.get("vehicle_number")
    date = request.form.get("date")

    if not vehicle or not date:
        return redirect(url_for("admin"))

    qr_data = f"{vehicle}|{date}"
    filename = f"{vehicle}_{date}.png"
    path = os.path.join(QR_FOLDER, filename)

    qrcode.make(qr_data).save(path)

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO vehicle_logs (vehicle_number, entry_date, qr_file)
        VALUES (%s, %s, %s)
        """,
        (vehicle, date, filename),
    )
    conn.commit()
    cur.close()
    conn.close()

    return redirect(url_for("admin"))

# -----------------------------
# EXPORT DAY
# -----------------------------
@app.route("/export/day")
def export_day():
    if not session.get("logged_in"):
        return redirect(url_for("login"))

    date = request.args.get("date")
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "SELECT vehicle_number, entry_date, qr_file FROM vehicle_logs WHERE entry_date=%s",
        (date,),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()

    return export_csv(rows, f"logs_{date}.csv")

# -----------------------------
# EXPORT MONTH
# -----------------------------
@app.route("/export/month")
def export_month():
    if not session.get("logged_in"):
        return redirect(url_for("login"))

    month = request.args.get("month")
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT vehicle_number, entry_date, qr_file
        FROM vehicle_logs
        WHERE TO_CHAR(entry_date, 'MM')=%s
        """,
        (month,),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()

    return export_csv(rows, f"logs_month_{month}.csv")

# -----------------------------
# EXPORT YEAR
# -----------------------------
@app.route("/export/year")
def export_year():
    if not session.get("logged_in"):
        return redirect(url_for("login"))

    year = request.args.get("year")
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT vehicle_number, entry_date, qr_file
        FROM vehicle_logs
        WHERE TO_CHAR(entry_date, 'YYYY')=%s
        """,
        (year,),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()

    return export_csv(rows, f"logs_year_{year}.csv")

# -----------------------------
# CSV HELPER
# -----------------------------
def export_csv(rows, filename):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Vehicle Number", "Date", "QR File"])
    for r in rows:
        writer.writerow(r)

    mem = io.BytesIO()
    mem.write(output.getvalue().encode("utf-8"))
    mem.seek(0)
    output.close()

    return send_file(mem, as_attachment=True, download_name=filename, mimetype="text/csv")

# -----------------------------
# RUN
# -----------------------------
if __name__ == "__main__":
    app.run(debug=True)