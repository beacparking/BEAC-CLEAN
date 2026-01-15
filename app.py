from flask import Flask, render_template, request, redirect, session
import psycopg2
import os
import qrcode
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = "bea_secure_key"

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
        if request.form["username"] == "admin" and request.form["password"] == "admin123":
            session["logged_in"] = True
            return redirect("/admin")
        return render_template("login.html", error="Invalid credentials")
    return render_template("login.html")

# ======================
# ADMIN PAGE (GET ONLY)
# ======================
@app.route("/admin", methods=["GET"])
def admin():
    if not session.get("logged_in"):
        return redirect("/")
    qr = session.pop("last_qr", None)
    return render_template("admin.html", qr=qr)

# ======================
# GENERATE QR (POST ONLY)
# ======================
@app.route("/generate", methods=["POST"])
def generate():
    if not session.get("logged_in"):
        return redirect("/")

    vehicle_number = request.form.get("vehicle_number")
    selected_date = request.form.get("date")

    if not vehicle_number or not selected_date:
        return redirect("/admin")

    generated_date = datetime.strptime(selected_date, "%Y-%m-%d").date()
    expires_date = generated_date + timedelta(days=1)

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

    os.makedirs("static/qr", exist_ok=True)
    qr_path = f"static/qr/{qr_id}.png"
    qr_img.save(qr_path)

    session["last_qr"] = {
        "sequence": qr_id,
        "vehicle_number": vehicle_number,
        "expires_date": expires_date.strftime("%d-%m-%Y"),
        "qr_image": qr_path
    }

    return redirect("/admin")

# ======================
# VERIFY QR
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

    row = cur.fetchone()
    conn.close()

    if not row:
        return "INVALID QR"

    vehicle_number, expires_date = row
    today = datetime.utcnow().date()

    status = "VALID" if today <= expires_date else "EXPIRED"

    return f"""
    <h2>Status: {status}</h2>
    <p>Vehicle: {vehicle_number}</p>
    <p>Expires: {expires_date}</p>
    """

# ======================
# LOGOUT
# ======================
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")