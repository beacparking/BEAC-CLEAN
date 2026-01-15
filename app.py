from flask import Flask, render_template, request, redirect, url_for, session, send_file
import psycopg2
import os
import csv
from datetime import datetime
import qrcode

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "bea_secret_key")

# -----------------------------
# DATABASE (Render PostgreSQL)
# -----------------------------
DATABASE_URL = os.environ.get("DATABASE_URL")

def get_db():
    return psycopg2.connect(DATABASE_URL)

# -----------------------------
# ADMIN CREDENTIALS
# -----------------------------
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin123"

# -----------------------------
# QR CONFIG
# -----------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
QR_FOLDER = os.path.join(BASE_DIR, "static", "qr")
os.makedirs(QR_FOLDER, exist_ok=True)

# -----------------------------
# ROUTES
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
        username = request.form.get("username")
        password = request.form.get("password")

        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session["logged_in"] = True
            return redirect(url_for("admin"))
        else:
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
# GENERATE QR
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
    cur.execute("""
        INSERT INTO vehicle_logs (vehicle_number, entry_date, qr_file)
        VALUES (%s, %s, %s)
    """, (vehicle_number, date, qr_filename))
    conn.commit()
    cur.close()
    conn.close()

    return redirect(url_for("admin"))

# -----------------------------
# EXPORT CSV
# -----------------------------
@app.route("/export")
def export_csv():
    if not session.get("logged_in"):
        return redirect(url_for("login"))

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT vehicle_number, entry_date FROM vehicle_logs ORDER BY entry_date DESC")
    rows = cur.fetchall()
    cur.close()
    conn.close()

    export_path = os.path.join(BASE_DIR, "export.csv")
    with open(export_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Vehicle Number", "Date"])
        writer.writerows(rows)

    return send_file(export_path, as_attachment=True)

# -----------------------------
# RUN
# -----------------------------
if __name__ == "__main__":
    app.run()