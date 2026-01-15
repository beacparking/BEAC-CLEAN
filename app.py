from flask import Flask, render_template, request, redirect, url_for, session, send_file
import os
import psycopg2
from datetime import datetime
import qrcode

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "bea_secret_key")

# -------------------------
# DATABASE (PostgreSQL)
# -------------------------
DATABASE_URL = os.environ.get("DATABASE_URL")

def get_db():
    return psycopg2.connect(DATABASE_URL)

def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS vehicle_logs (
            id SERIAL PRIMARY KEY,
            vehicle_number TEXT NOT NULL,
            entry_date DATE NOT NULL,
            qr_file TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    cur.close()
    conn.close()

init_db()

# -------------------------
# CONFIG
# -------------------------
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin123"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
QR_FOLDER = os.path.join(BASE_DIR, "static", "qr")
os.makedirs(QR_FOLDER, exist_ok=True)

# -------------------------
# ROUTES
# -------------------------
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

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/admin")
def admin():
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    return render_template("admin.html")

# -------------------------
# GENERATE QR
# -------------------------
@app.route("/generate", methods=["POST"])
def generate_qr():
    if not session.get("logged_in"):
        return redirect(url_for("login"))

    vehicle_number = request.form.get("vehicle_number")
    entry_date = request.form.get("date")

    if not vehicle_number:
        return redirect(url_for("admin"))

    if not entry_date:
        entry_date = datetime.now().strftime("%Y-%m-%d")

    qr_data = f"{vehicle_number}|{entry_date}"
    qr_filename = f"{vehicle_number}_{entry_date}.png"
    qr_path = os.path.join(QR_FOLDER, qr_filename)

    qrcode.make(qr_data).save(qr_path)

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO vehicle_logs (vehicle_number, entry_date, qr_file) VALUES (%s, %s, %s)",
        (vehicle_number, entry_date, qr_filename),
    )
    conn.commit()
    cur.close()
    conn.close()

    return redirect(url_for("admin"))

# -------------------------
# EXPORT DAY
# -------------------------
@app.route("/export/day")
def export_day():
    if not session.get("logged_in"):
        return redirect(url_for("login"))

    date = request.args.get("date")
    if not date:
        return redirect(url_for("admin"))

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT vehicle_number, entry_date FROM vehicle_logs WHERE entry_date = %s",
        (date,),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()

    if not rows:
        return redirect(url_for("admin"))

    csv_path = f"/tmp/export_day_{date}.csv"
    with open(csv_path, "w") as f:
        f.write("Vehicle Number,Date\n")
        for r in rows:
            f.write(f"{r[0]},{r[1]}\n")

    return send_file(csv_path, as_attachment=True)

# -------------------------
# EXPORT MONTH
# -------------------------
@app.route("/export/month")
def export_month():
    if not session.get("logged_in"):
        return redirect(url_for("login"))

    month = request.args.get("month")
    if not month:
        return redirect(url_for("admin"))

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT vehicle_number, entry_date FROM vehicle_logs WHERE TO_CHAR(entry_date, 'YYYY-MM') = %s",
        (month,),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()

    csv_path = f"/tmp/export_month_{month}.csv"
    with open(csv_path, "w") as f:
        f.write("Vehicle Number,Date\n")
        for r in rows:
            f.write(f"{r[0]},{r[1]}\n")

    return send_file(csv_path, as_attachment=True)

# -------------------------
# EXPORT YEAR
# -------------------------
@app.route("/export/year")
def export_year():
    if not session.get("logged_in"):
        return redirect(url_for("login"))

    year = request.args.get("year")
    if not year:
        return redirect(url_for("admin"))

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT vehicle_number, entry_date FROM vehicle_logs WHERE EXTRACT(YEAR FROM entry_date) = %s",
        (year,),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()

    csv_path = f"/tmp/export_year_{year}.csv"
    with open(csv_path, "w") as f:
        f.write("Vehicle Number,Date\n")
        for r in rows:
            f.write(f"{r[0]},{r[1]}\n")

    return send_file(csv_path, as_attachment=True)

# -------------------------
# RUN
# -------------------------
if __name__ == "__main__":
    app.run(debug=True)