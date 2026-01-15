from flask import Flask, render_template, request, redirect, url_for, session, send_file
import os
import psycopg2
from datetime import datetime
import qrcode
import csv
from io import StringIO, BytesIO

app = Flask(__name__)
app.secret_key = "bea_secret_key"

# -----------------------------
# ADMIN LOGIN
# -----------------------------
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin123"

# -----------------------------
# DATABASE (Render PostgreSQL)
# -----------------------------
DATABASE_URL = os.environ.get("DATABASE_URL")

def get_db():
    return psycopg2.connect(DATABASE_URL)

# -----------------------------
# QR STORAGE
# -----------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
QR_FOLDER = os.path.join(BASE_DIR, "static", "qr")
os.makedirs(QR_FOLDER, exist_ok=True)

# -----------------------------
# HOME
# -----------------------------
@app.route("/")
def home():
    return redirect(url_for("login"))

# -----------------------------
# LOGIN
# -----------------------------
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
# ADMIN DASHBOARD
# -----------------------------
@app.route("/admin")
def admin():
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    return render_template("admin.html")

# -----------------------------
# LOGOUT
# -----------------------------
@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# -----------------------------
# GENERATE QR (POSTGRES)
# -----------------------------
@app.route("/generate", methods=["POST"])
def generate_qr():
    if not session.get("logged_in"):
        return redirect(url_for("login"))

    vehicle_number = request.form.get("vehicle_number")
    date = request.form.get("date") or datetime.now().strftime("%Y-%m-%d")

    if not vehicle_number:
        return redirect(url_for("admin"))

    qr_data = f"{vehicle_number}|{date}"
    qr_filename = f"{vehicle_number}_{date}.png"
    qr_path = os.path.join(QR_FOLDER, qr_filename)

    qr = qrcode.make(qr_data)
    qr.save(qr_path)

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO vehicle_logs (vehicle_number, entry_date, qr_file)
        VALUES (%s, %s, %s)
        """,
        (vehicle_number, date, qr_filename),
    )
    conn.commit()
    cur.close()
    conn.close()

    return redirect(url_for("admin"))

# -----------------------------
# EXPORT CSV (POSTGRES)
# -----------------------------
@app.route("/export")
def export_all():
    if not session.get("logged_in"):
        return redirect(url_for("login"))

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT vehicle_number, entry_date, qr_file FROM vehicle_logs ORDER BY entry_date DESC"
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()

    si = StringIO()
    writer = csv.writer(si)
    writer.writerow(["Vehicle Number", "Date", "QR File"])
    writer.writerows(rows)

    output = BytesIO()
    output.write(si.getvalue().encode("utf-8"))
    output.seek(0)

    return send_file(
        output,
        mimetype="text/csv",
        as_attachment=True,
        download_name="vehicle_logs.csv",
    )

# -----------------------------
# RUN
# -----------------------------
if __name__ == "__main__":
    app.run(debug=True)