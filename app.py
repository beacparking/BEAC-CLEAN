from flask import Flask, render_template, request, redirect, url_for, session
import psycopg2
import os
import qrcode
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = "bea_secure_key"  # keep same

# =========================
# DATABASE
# =========================
DATABASE_URL = os.environ.get("DATABASE_URL")

def get_db():
    return psycopg2.connect(DATABASE_URL)

# =========================
# LOGIN
# =========================
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin123"

@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if (
            request.form.get("username") == ADMIN_USERNAME
            and request.form.get("password") == ADMIN_PASSWORD
        ):
            session["logged_in"] = True
            return redirect("/admin")
        return render_template("login.html", error="Invalid credentials")

    return render_template("login.html")

# =========================
# ADMIN (GET ONLY)
# =========================
@app.route("/admin", methods=["GET"])
def admin():
    if not session.get("logged_in"):
        return redirect("/")

    qr = session.pop("last_qr", None)  # show once
    return render_template("admin.html", qr=qr)

# =========================
# GENERATE QR (POST ONLY)
# =========================
@app.route("/generate", methods=["POST"])
def generate_qr():
    if not session.get("logged_in"):
        return redirect("/")

    vehicle_number = request.form.get("vehicle_number", "").strip()
    selected_date = request.form.get("date", "").strip()

    if not vehicle_number or not selected_date:
        return redirect("/admin")

    generated_date = datetime.strptime(selected_date, "%Y-%m-%d").date()
    expires_date = generated_date + timedelta(days=1)  # 2-day validity

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO vehicle_qr (vehicle_number, generated_date, expires_date)
        VALUES (%s, %s, %s)
        RETURNING id
    """, (vehicle_number, generated_date, expires_date))

    qr_id = cur.fetchone()[0]
    conn.commit()
    conn.close()

    qr_url = f"{request.host_url}verify/{qr_id}"
    qr_img = qrcode.make(qr_url)

    qr_path = f"static/qr/{qr_id}.png"
    qr_img.save(qr_path)

    # Store ONLY for display (no reinsert on refresh)
    session["last_qr"] = {
        "sequence": qr_id,
        "vehicle_number": vehicle_number,
        "expires_date": expires_date.strftime("%d-%m-%Y"),
        "qr_image": qr_path
    }

    return redirect("/admin")  # 🔑 PRG FIX

# =========================
# VERIFY QR
# =========================
@app.route("/verify/<int:qr_id>")
def verify(qr_id):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT vehicle_number, expires_date
        FROM vehicle_qr
        WHERE id = %s
    """, (qr_id,))

    row = cur.fetchone()
    conn.close()

    if not row:
        return render_template("verify.html", status="INVALID")

    vehicle_number, expires_date = row
    today = datetime.utcnow().date()

    status = "VALID" if today <= expires_date else "EXPIRED"

    return render_template(
        "verify.html",
        status=status,
        vehicle_number=vehicle_number,
        expires_date=expires_date.strftime("%d-%m-%Y")
    )

# =========================
# LOGOUT
# =========================
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")