from flask import Flask, render_template, request, redirect, url_for
import psycopg2
import os
import qrcode
from datetime import datetime, timedelta

app = Flask(__name__)

# -----------------------------
# DATABASE CONNECTION
# -----------------------------
DATABASE_URL = os.environ.get("DATABASE_URL")

def get_db():
    return psycopg2.connect(DATABASE_URL)

# -----------------------------
# LOGIN (OPTION A – NO AUTH YET)
# -----------------------------
@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        # Option A: UI-only login (no validation)
        return redirect(url_for("admin"))

    return render_template("login.html")

# -----------------------------
# ADMIN + QR GENERATION
# -----------------------------
@app.route("/admin", methods=["GET", "POST"])
def admin():
    qr_data = None
    error = None

    if request.method == "POST":
        vehicle_number = request.form.get("vehicle_number")
        selected_date = request.form.get("date")

        # 🛑 SAFETY CHECK (prevents crash)
        if not vehicle_number or not selected_date:
            error = "Vehicle number and date are required"
            return render_template("admin.html", error=error)

        try:
            generated_date = datetime.strptime(selected_date, "%Y-%m-%d").date()
        except Exception:
            error = "Invalid date format"
            return render_template("admin.html", error=error)

        # 2-day validity (generated day + next day)
        expires_date = generated_date + timedelta(days=1)

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

        # QR points to verify page
        qr_payload = f"{request.host_url}verify/{sequence_no}"

        qr_img = qrcode.make(qr_payload)
        qr_path = f"static/qr/{sequence_no}.png"
        qr_img.save(qr_path)

        qr_data = {
            "sequence": sequence_no,
            "vehicle_number": vehicle_number,
            "expires_date": expires_date.strftime("%d-%m-%Y"),
            "qr_image": qr_path
        }

    return render_template("admin.html", qr=qr_data)

# -----------------------------
# VERIFY QR
# -----------------------------
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

# -----------------------------
# RUN
# -----------------------------
if __name__ == "__main__":
    app.run(debug=True)