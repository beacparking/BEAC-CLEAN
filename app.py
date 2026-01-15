from flask import Flask, render_template, request, redirect, url_for, session, send_file
import os
import psycopg2
from datetime import datetime
import qrcode

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "bea_secret_key")

# =============================
# CONFIG
# =============================
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin123"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
QR_FOLDER = os.path.join(BASE_DIR, "static", "qr")
os.makedirs(QR_FOLDER, exist_ok=True)

DATABASE_URL = os.environ.get("DATABASE_URL")

# =============================
# DATABASE CONNECTION
# =============================
def get_db():
    return psycopg2.connect(DATABASE_URL, sslmode="require")

# =============================
# LOGIN
# =============================
@app.route("/", methods=["GET"])
def home():
    return redirect(url_for("login"))

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session["logged_in"] = True
            return redirect(url_for("admin"))
        return render_template("login.html", error="Invalid credentials")

    return render_template("login.html")

# =============================
# ADMIN DASHBOARD
# =============================
@app.route("/admin")
def admin():
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    return render_template("admin.html")

# =============================
# LOGOUT
# =============================
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

    vehicle_number = request.form.get("vehicle_number")
    date = request.form.get("date") or datetime.now().strftime("%Y-%m-%d")

    if not vehicle_number:
        return redirect(url_for("admin"))

    qr_data = f"{vehicle_number}|{date}"
    qr_filename = f"{vehicle_number}_{date}.png"
    qr_path = os.path.join(QR_FOLDER, qr_filename)

    qrcode.make(qr_data).save(qr_path)

    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO vehicle_logs (vehicle_number, log_date, qr_file)
        VALUES (%s, %s, %s)
    """, (vehicle_number, date, qr_filename))
    conn.commit()
    cur.close()
    conn.close()

    return redirect(url_for("admin"))

# =============================
# VERIFY QR (PUBLIC)
# =============================
@app.route("/verify")
def verify():
    vehicle_number = request.args.get("vehicle")
    date = request.args.get("date")

    if not vehicle_number or not date:
        return render_template("verify.html", valid=False)

    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT id FROM vehicle_logs
        WHERE vehicle_number = %s AND log_date = %s
    """, (vehicle_number, date))
    result = cur.fetchone()
    cur.close()
    conn.close()

    return render_template(
        "verify.html",
        valid=bool(result),
        vehicle=vehicle_number,
        date=date
    )

# =============================
# EXPORT CSV (ALL DATA)
# =============================
@app.route("/export")
def export_all():
    if not session.get("logged_in"):
        return redirect(url_for("login"))

    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT vehicle_number, log_date, created_at
        FROM vehicle_logs
        ORDER BY created_at DESC
    """)
    rows = cur.fetchall()
    cur.close()
    conn.close()

    file_path = os.path.join(BASE_DIR, "export.csv")
    with open(file_path, "w") as f:
        f.write("Vehicle Number,Date,Created At\n")
        for r in rows:
            f.write(f"{r[0]},{r[1]},{r[2]}\n")

    return send_file(file_path, as_attachment=True)

# =============================
# RUN
# =============================
if __name__ == "__main__":
    app.run(debug=True)