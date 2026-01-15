from flask import Flask, render_template, request, redirect, url_for, session, send_file
import psycopg2
import psycopg2.extras
import qrcode
import os
from datetime import datetime
from io import StringIO
import csv

app = Flask(__name__)
app.secret_key = "bea_secret_key"

# =============================
# DATABASE (Render PostgreSQL)
# =============================
DATABASE_URL = os.environ.get("DATABASE_URL")

def get_db():
    return psycopg2.connect(DATABASE_URL, sslmode="require")

# =============================
# AUTH CONFIG
# =============================
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin123"

# =============================
# QR STORAGE
# =============================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
QR_FOLDER = os.path.join(BASE_DIR, "static", "qr")
os.makedirs(QR_FOLDER, exist_ok=True)

# =============================
# ROUTES
# =============================
@app.route("/")
def home():
    return redirect(url_for("login"))

# ---------- LOGIN ----------
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

# ---------- ADMIN ----------
@app.route("/admin")
def admin():
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    return render_template("admin.html")

# ---------- LOGOUT ----------
@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# =============================
# GENERATE QR
# =============================
@app.route("/generate", methods=["POST"])
def generate_qr():
    if not session.get("logged_in"):
        return redirect(url_for("login"))

    vehicle_number = request.form.get("vehicle")
    date_str = request.form.get("date")

    if not vehicle_number or not date_str:
        return redirect(url_for("admin"))

    log_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    qr_data = f"{vehicle_number}|{log_date}"

    qr_filename = f"{vehicle_number}_{log_date}.png"
    qr_path = os.path.join(QR_FOLDER, qr_filename)

    img = qrcode.make(qr_data)
    img.save(qr_path)

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO vehicle_logs (vehicle_number, log_date, qr_data)
        VALUES (%s, %s, %s)
        """,
        (vehicle_number, log_date, qr_filename),
    )
    conn.commit()
    cur.close()
    conn.close()

    return redirect(url_for("admin"))

# =============================
# EXPORT DAY
# =============================
@app.route("/export/day")
def export_day():
    if not session.get("logged_in"):
        return redirect(url_for("login"))

    date_str = request.args.get("date")
    if not date_str:
        return redirect(url_for("admin"))

    log_date = datetime.strptime(date_str, "%Y-%m-%d").date()

    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cur.execute(
        "SELECT vehicle_number, log_date FROM vehicle_logs WHERE log_date = %s",
        (log_date,),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()

    return csv_response(rows, f"vehicle_logs_{log_date}.csv")

# =============================
# EXPORT MONTH
# =============================
@app.route("/export/month")
def export_month():
    if not session.get("logged_in"):
        return redirect(url_for("login"))

    month = request.args.get("month")
    if not month:
        return redirect(url_for("admin"))

    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cur.execute(
        """
        SELECT vehicle_number, log_date
        FROM vehicle_logs
        WHERE TO_CHAR(log_date, 'MM') = %s
        """,
        (month.zfill(2),),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()

    return csv_response(rows, f"vehicle_logs_month_{month}.csv")

# =============================
# EXPORT YEAR
# =============================
@app.route("/export/year")
def export_year():
    if not session.get("logged_in"):
        return redirect(url_for("login"))

    year = request.args.get("year")
    if not year:
        return redirect(url_for("admin"))

    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cur.execute(
        """
        SELECT vehicle_number, log_date
        FROM vehicle_logs
        WHERE TO_CHAR(log_date, 'YYYY') = %s
        """,
        (year,),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()

    return csv_response(rows, f"vehicle_logs_year_{year}.csv")

# =============================
# CSV HELPER
# =============================
def csv_response(rows, filename):
    si = StringIO()
    cw = csv.writer(si)
    cw.writerow(["Vehicle Number", "Date"])

    for r in rows:
        cw.writerow([r["vehicle_number"], r["log_date"]])

    output = si.getvalue()
    return send_file(
        StringIO(output),
        mimetype="text/csv",
        download_name=filename,
        as_attachment=True,
    )

# =============================
# RUN LOCAL
# =============================
if __name__ == "__main__":
    app.run(debug=True)