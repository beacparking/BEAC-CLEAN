from flask import Flask, render_template, request, redirect
import os
import psycopg2
from datetime import datetime, timedelta, date
import qrcode
import uuid

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret")

DATABASE_URL = os.environ.get("DATABASE_URL")

# -------------------------
# DB CONNECTION
# -------------------------
def get_db():
    return psycopg2.connect(DATABASE_URL)

# -------------------------
# ROOT → LOGIN
# -------------------------
@app.route("/")
def login_page():
    return render_template("login.html")

# -------------------------
# LOGIN ACTION
# -------------------------
@app.route("/login", methods=["POST"])
def login():
    username = request.form.get("username")
    password = request.form.get("password")

    if (
        username == os.environ.get("ADMIN_USERNAME")
        and password == os.environ.get("ADMIN_PASSWORD")
    ):
        return redirect("/admin")

    return render_template("login.html", error="Invalid credentials")

# -------------------------
# ADMIN PAGE
# -------------------------
@app.route("/admin")
def admin():
    return render_template("admin.html")

# -------------------------
# GENERATE QR
# -------------------------
@app.route("/generate_qr", methods=["POST"])
def generate_qr():
    vehicle_number = request.form["vehicle_number"]
    generated_date = datetime.strptime(request.form["date"], "%Y-%m-%d").date()
    expires_date = generated_date + timedelta(days=1)

    qr_id = str(uuid.uuid4())

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO vehicle_qr (id, vehicle_number, generated_date, expires_date)
        VALUES (%s, %s, %s, %s)
        RETURNING id;
    """, (qr_id, vehicle_number, generated_date, expires_date))

    conn.commit()
    cur.close()
    conn.close()

    # Generate QR image
    qr_url = request.host_url + "verify/" + qr_id
    img = qrcode.make(qr_url)

    qr_path = f"static/qr/{qr_id}.png"
    os.makedirs("static/qr", exist_ok=True)
    img.save(qr_path)

    return render_template(
        "admin.html",
        qr_image=qr_path,
        vehicle_number=vehicle_number
    )

# -------------------------
# VERIFY QR (SCAN)
# -------------------------
@app.route("/verify/<qr_id>")
def verify(qr_id):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT vehicle_number, generated_date, expires_date
        FROM vehicle_qr
        WHERE id = %s
    """, (qr_id,))

    row = cur.fetchone()
    cur.close()
    conn.close()

    if not row:
        return "INVALID QR", 404

    vehicle_number, generated_date, expires_date = row
    today = date.today()

    status = "VALID" if today <= expires_date else "EXPIRED"

    return render_template(
        "verify.html",
        vehicle_number=vehicle_number,
        status=status,
        generated_date=generated_date,
        expires_date=expires_date
    )

# -------------------------
# RUN
# -------------------------
if __name__ == "__main__":
    app.run(debug=True)