from flask import Flask, render_template, request, redirect, url_for, session
import psycopg2
import os
import qrcode
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = "bea-secret-key"

# ======================
# DATABASE
# ======================
DATABASE_URL = os.environ.get("DATABASE_URL")

def get_db():
    return psycopg2.connect(DATABASE_URL)

# ======================
# LOGIN
# ======================
@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")

        if username == "admin" and password == "admin123":
            session["logged_in"] = True
            return redirect("/admin")

        return render_template("login.html", error="Invalid credentials")

    return render_template("login.html")

# ======================
# ADMIN
# ======================
@app.route("/admin", methods=["GET", "POST"])
def admin():
    if not session.get("logged_in"):
        return redirect("/")

    qr = None
    error = None

    if request.method == "POST":
        vehicle_number = request.form.get("vehicle_number")
        selected_date = request.form.get("generated_date")

        if not vehicle_number or not selected_date:
            error = "Vehicle number and date are required"
            return render_template("admin.html", error=error)

        try:
            generated_date = datetime.strptime(selected_date, "%Y-%m-%d").date()
        except Exception:
            error = "Invalid date"
            return render_template("admin.html", error=error)

        expires_date = generated_date + timedelta(days=1)

        # ---- DB INSERT ----
        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO vehicle_qr (vehicle_number, generated_date, expires_date)
                VALUES (%s, %s, %s)
                RETURNING id
            """, (vehicle_number, generated_date, expires_date))
            sequence_no = cur.fetchone()[0]
            conn.commit()
            conn.close()
        except Exception as e:
            error = "Database error"
            return render_template("admin.html", error=error)

        # ======================
        # QR GENERATION (SAFE)
        # ======================
        os.makedirs("static/qr", exist_ok=True)  # 🔒 CRASH-PROOF LINE

        qr_url = f"{request.host_url}verify/{sequence_no}"
        qr_img = qrcode.make(qr_url)

        qr_path = f"static/qr/{sequence_no}.png"
        qr_img.save(qr_path)

        qr = {
            "sequence": sequence_no,
            "vehicle_number": vehicle_number,
            "expires_date": expires_date.strftime("%d-%m-%Y"),
            "qr_image": qr_path
        }

    return render_template("admin.html", qr=qr, error=error)

# ======================
# VERIFY
# ======================
@app.route("/verify/<int:qr_id>")
def verify(qr_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT vehicle_number, expires_date
        FROM vehicle_qr
        WHERE id = %s
    """, (qr_id,))
    record = cur.fetchone()
    conn.close()

    if not record:
        return render_template("verify.html", status="INVALID")

    vehicle_number, expires_date = record
    today = datetime.utcnow().date()

    status = "VALID" if today <= expires_date else "EXPIRED"

    return render_template(
        "verify.html",
        status=status,
        vehicle_number=vehicle_number,
        expires_date=expires_date.strftime("%d-%m-%Y")
    )

# ======================
# LOGOUT
# ======================
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")