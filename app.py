from flask import Flask, render_template, request, redirect, url_for, session, send_file
import os
import csv
from datetime import datetime
import qrcode

app = Flask(__name__)
app.secret_key = "bea_secret_key"

# -----------------------------
# CONFIG
# -----------------------------
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin123"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
QR_FOLDER = os.path.join(BASE_DIR, "static", "qr")
CSV_FILE = os.path.join(BASE_DIR, "vehicle_logs.csv")

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
        username = request.form.get("username")
        password = request.form.get("password")

        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session["logged_in"] = True
            return redirect(url_for("admin"))
        else:
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

    vehicle_number = request.form.get("vehicle")
    date = request.form.get("date")

    if not vehicle_number or not date:
        return redirect(url_for("admin"))

    qr_data = f"{vehicle_number}|{date}"
    filename = f"{vehicle_number}_{date}.png"
    qr_path = os.path.join(QR_FOLDER, filename)

    qr = qrcode.make(qr_data)
    qr.save(qr_path)

    file_exists = os.path.isfile(CSV_FILE)
    with open(CSV_FILE, "a", newline="") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["vehicle_number", "date", "qr_file"])
        writer.writerow([vehicle_number, date, filename])

    return redirect(url_for("admin"))

# -----------------------------
# EXPORT CSV (ALL)
# -----------------------------
@app.route("/export")
def export_csv():
    if not session.get("logged_in"):
        return redirect(url_for("login"))

    if not os.path.exists(CSV_FILE):
        return redirect(url_for("admin"))

    return send_file(CSV_FILE, as_attachment=True)

# -----------------------------
# RUN
# -----------------------------
if __name__ == "__main__":
    app.run(debug=True)