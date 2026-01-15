from flask import Flask, render_template, request, redirect, url_for
import psycopg2
import os
import qrcode
from datetime import datetime, timedelta, date

app = Flask(__name__)

# =================================================
# DATABASE (PostgreSQL - Render)
# =================================================
DATABASE_URL = os.environ.get("DATABASE_URL")

def get_db():
    return psycopg2.connect(DATABASE_URL, sslmode="require")

# =================================================
# LOGIN (OPTION A – UI ONLY, NO AUTH YET)
# =================================================
@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        # UI-only login for Phase 1
        return redirect(url_for("admin"))
    return render_template("login.html")

# =================================================
# ADMIN – QR GENERATION
# =================================================
@app.route("/admin", methods=["GET", "POST"])
def admin():
    qr = None
    error = None

    if request.method == "POST":
        # 🔐 READ FORM SAFELY
        vehicle_number = request.form.get("vehicle_number", "").strip()
        selected_date = request.form.get("date", "").strip()

        # 🛑 HARD VALIDATION (NO CRASH)
        if not vehicle_number:
            error = "Vehicle number is required."
            return render_template("admin.html", error=error)

        if not selected_date:
            error = "Date is required."
            return render_template("admin.html", error=error)

        try:
            generated_date = datetime.strptime(selected_date, "%Y-%m-%d").date()
        except Exception:
            error = "Invalid date format."
            return render_template("admin.html", error=error)

        # ⏳ 2-DAY VALIDITY
        expires_date = generated_date + timedelta(days=1)

        # =================================================
        # DATABASE INSERT (SEQUENCE = id)
        # =================================================
        try:
            conn = get_db()
            cur = conn.cursor()

            cur.execute("""
                INSERT INTO vehicle_qr (vehicle_number, generated_date, expires_date)
                VALUES (%s, %s, %s)
                RETURNING id
            """, (vehicle_number, generated_date, expires_date))

            sequence = cur.fetchone()[0]
            conn.commit()
            conn.close()

        except Exception as e:
            error = "Database error. Please try again."
            return render_template("admin.html", error=error)

        # =================================================
        # QR GENERATION (STABLE)
        # =================================================
        qr_url = f"{request.host_url}verify/{sequence}"

        qr_img = qrcode.make(qr_url)

        qr_folder = os.path.join("static", "qr")
        os.makedirs(qr_folder, exist_ok=True)

        qr_path = os.path.join(qr_folder, f"{sequence}.png")
        qr_img.save(qr_path)

        qr = {
            "sequence": sequence,
            "vehicle_number": vehicle_number,
            "generated_date": generated_date.strftime("%d-%m-%Y"),
            "expires_date": expires_date.strftime("%d-%m-%Y"),
            "qr_image": qr_path
        }

    return render_template("admin.html", qr=qr, error=error)

# =================================================
# VERIFY QR (PUBLIC, SAFE FOREVER)
# =================================================
@app.route("/verify/<int:qr_id>")
def verify(qr_id):
    try:
        conn = get_db()
        cur = conn.cursor()

        cur.execute("""
            SELECT vehicle_number, expires_date
            FROM vehicle_qr
            WHERE id = %s
        """, (qr_id,))

        record = cur.fetchone()
        conn.close()

    except Exception:
        return render_template("verify.html", status="INVALID")

    if not record:
        return render_template("verify.html", status="INVALID")

    vehicle_number, expires_date = record
    today = date.today()

    status = "VALID" if today <= expires_date else "EXPIRED"

    return render_template(
        "verify.html",
        status=status,
        vehicle_number=vehicle_number,
        expires_date=expires_date.strftime("%d-%m-%Y"),
        sequence=qr_id
    )

# =================================================
# RUN
# =================================================
if __name__ == "__main__":
    app.run(debug=True)