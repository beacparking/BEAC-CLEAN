from flask import Flask, render_template, request, redirect, url_for
import psycopg2
import qrcode
import os
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = "bea_secret_key"

# ------------------ DATABASE ------------------
DATABASE_URL = os.environ.get("DATABASE_URL")

def get_db():
    return psycopg2.connect(DATABASE_URL)

# ------------------ PATHS ------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
QR_FOLDER = os.path.join(BASE_DIR, "static", "qr")
os.makedirs(QR_FOLDER, exist_ok=True)

# ------------------ LOGIN ------------------
@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form["username"] == "admin" and request.form["password"] == "admin123":
            return redirect("/admin")
    return render_template("login.html")

# ------------------ ADMIN ------------------
@app.route("/admin")
def admin():
    return render_template("admin.html")

# ------------------ GENERATE QR ------------------
@app.route("/generate", methods=["POST"])
def generate_qr():
    vehicle_number = request.form.get("vehicle")
    date_str = request.form.get("date")

    if not vehicle_number or not date_str:
        return redirect("/admin")

    generated_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    expires_on = generated_date + timedelta(days=1)

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO qr_codes (vehicle_number, generated_date, expires_on)
        VALUES (%s, %s, %s)
        RETURNING id
        """,
        (vehicle_number, generated_date, expires_on)
    )

    seq_no = cur.fetchone()[0]
    conn.commit()

    # QR DATA → points to verify page
    qr_data = f"{request.host_url}verify/{seq_no}"

    qr_img = qrcode.make(qr_data)
    qr_filename = f"qr_{seq_no}.png"
    qr_path = os.path.join(QR_FOLDER, qr_filename)
    qr_img.save(qr_path)

    cur.close()
    conn.close()

    return render_template(
        "admin.html",
        qr_image=url_for("static", filename=f"qr/{qr_filename}"),
        seq_no=seq_no,
        vehicle_number=vehicle_number
    )

# ------------------ VERIFY QR ------------------
@app.route("/verify/<int:qr_id>")
def verify(qr_id):
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "SELECT vehicle_number, expires_on FROM qr_codes WHERE id=%s",
        (qr_id,)
    )

    row = cur.fetchone()
    cur.close()
    conn.close()

    if not row:
        return render_template("verify.html", status="INVALID")

    vehicle_number, expires_on = row
    today = datetime.utcnow().date()

    if today <= expires_on:
        status = "VALID"
    else:
        status = "EXPIRED"

    return render_template(
        "verify.html",
        status=status,
        vehicle_number=vehicle_number,
        expires_on=expires_on
    )

# ------------------ RUN ------------------
if __name__ == "__main__":
    app.run(debug=True)