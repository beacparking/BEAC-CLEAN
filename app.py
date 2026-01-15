from flask import Flask, render_template, request, redirect, url_for
import psycopg2
import os
import qrcode
from datetime import datetime, timedelta, date

app = Flask(__name__)
app.secret_key = "stable-secret-key"

# ============================
# DATABASE (PostgreSQL)
# ============================
DATABASE_URL = os.environ.get("DATABASE_URL")

def get_db():
    return psycopg2.connect(DATABASE_URL, sslmode="require")

# ============================
# LOGIN
# ============================
@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        # UI already validates username/password
        return redirect(url_for("admin"))
    return render_template("login.html")

# ============================
# ADMIN (QR GENERATION)
# ============================
@app.route("/admin", methods=["GET", "POST"])
def admin():
    qr = None
    error = None

    if request.method == "POST":

        # ✅ ACCEPT EXISTING UI FIELD NAMES
        vehicle = request.form.get("vehicle") or request.form.get("vehicle_number")
        expiry = request.form.get("expiry") or request.form.get("date")

        if not vehicle or not expiry:
            error = "Vehicle number and date are required."
            return render_template("admin.html", error=error)

        try:
            generated_date = datetime.strptime(expiry, "%Y-%m-%d").date()
        except ValueError:
            error = "Invalid date format."
            return render_template("admin.html", error=error)

        # ⏳ 2-day validity
        expires_date = generated_date + timedelta(days=1)

        try:
            conn = get_db()
            cur = conn.cursor()

            cur.execute("""
                INSERT INTO vehicle_qr (vehicle_number, generated_date, expires_date)
                VALUES (%s, %s, %s)
                RETURNING id
            """, (vehicle.strip(), generated_date, expires_date))

            sequence = cur.fetchone()[0]
            conn.commit()
            conn.close()

        except Exception:
            error = "Database error. QR not saved."
            return render_template("admin.html", error=error)

        # ============================
        # QR CREATION
        # ============================
        qr_url = f"{request.host_url}verify/{sequence}"

        os.makedirs("static/qr", exist_ok=True)
        qr_path = f"static/qr/{sequence}.png"

        qr_img = qrcode.make(qr_url)
        qr_img.save(qr_path)

        qr = {
            "sequence": sequence,
            "vehicle": vehicle,
            "generated": generated_date.strftime("%d-%m-%Y"),
            "expires": expires_date.strftime("%d-%m-%Y"),
            "image": qr_path
        }

    return render_template("admin.html", qr=qr, error=error)

# ============================
# VERIFY QR
# ============================
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

        row = cur.fetchone()
        conn.close()

    except Exception:
        return render_template("verify.html", status="INVALID")

    if not row:
        return render_template("verify.html", status="INVALID")

    vehicle, expires_date = row
    today = date.today()

    status = "VALID" if today <= expires_date else "EXPIRED"

    return render_template(
        "verify.html",
        status=status,
        vehicle=vehicle,
        expires=expires_date.strftime("%d-%m-%Y"),
        sequence=qr_id
    )

# ============================
# RUN
# ============================
if __name__ == "__main__":
    app.run(debug=True)