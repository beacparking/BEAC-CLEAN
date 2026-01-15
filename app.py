from flask import Flask, render_template, request, redirect, url_for, session
import psycopg2
import os
import qrcode
import csv
import io
from datetime import datetime, timedelta, date

app = Flask(__name__)
app.secret_key = "beac_secret_key"

DATABASE_URL = os.environ.get("DATABASE_URL")

def get_db():
    return psycopg2.connect(DATABASE_URL)
def export_csv(rows, filename):
    def generate():
        data = csv.writer([])
        yield "vehicle_number,generated_date,expires_date\n"
        for r in rows:
            yield f"{r[0]},{r[1]},{r[2]}\n"

    return Response(
        generate(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

# ---------------- LOGIN ----------------
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin123"

@app.route("/")
def home():
    return redirect(url_for("login"))

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

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ---------------- ADMIN ----------------
@app.route("/admin", methods=["GET", "POST"])
def admin():
    if not session.get("logged_in"):
        return redirect(url_for("login"))

    qr_data = None
    error = None

    if request.method == "POST":
        vehicle = request.form.get("vehicle")
        selected_date = request.form.get("date")

        if not vehicle or not selected_date:
            error = "Vehicle number and date required"
        else:
            generated_date = datetime.strptime(selected_date, "%Y-%m-%d").date()
            expires_date = generated_date + timedelta(days=2)

            conn = get_db()
            cur = conn.cursor()

            try:
                # Try insert (new QR)
                cur.execute("""
                    INSERT INTO vehicle_qr (vehicle_number, generated_date, expires_date)
                    VALUES (%s, %s, %s)
                    RETURNING id
                """, (vehicle, generated_date, expires_date))
                token_id = cur.fetchone()[0]
                conn.commit()

            except psycopg2.errors.UniqueViolation:
                # Duplicate → reuse existing QR
                conn.rollback()
                cur.execute("""
                    SELECT id, expires_date
                    FROM vehicle_qr
                    WHERE vehicle_number = %s AND generated_date = %s
                """, (vehicle, generated_date))
                token_id, expires_date = cur.fetchone()

            conn.close()

            qr_url = f"{request.host_url}verify/{token_id}"
            qr_path = f"static/qr/{token_id}.png"

            if not os.path.exists(qr_path):
                os.makedirs("static/qr", exist_ok=True)
                qrcode.make(qr_url).save(qr_path)

            qr_data = {
                "token": token_id,
                "vehicle": vehicle,
                "expiry": expires_date.strftime("%d-%m-%Y"),
                "qr_path": qr_path,
                "qr_url": qr_url
            }

    return render_template("admin.html", qr=qr_data, error=error)
from flask import Response
from datetime import timedelta

@app.route("/admin/export/daily")
def export_daily():
    if not session.get("logged_in"):
        return redirect(url_for("login"))

    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT vehicle_number, generated_date, expires_date
        FROM vehicle_qr
        WHERE generated_date = CURRENT_DATE
        ORDER BY generated_date DESC
    """)
    rows = cur.fetchall()
    conn.close()

    return export_csv(rows, "daily_qr.csv")


@app.route("/admin/export/weekly")
def export_weekly():
    if not session.get("logged_in"):
        return redirect(url_for("login"))

    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT vehicle_number, generated_date, expires_date
        FROM vehicle_qr
        WHERE generated_date >= CURRENT_DATE - INTERVAL '7 days'
        ORDER BY generated_date DESC
    """)
    rows = cur.fetchall()
    conn.close()

    return export_csv(rows, "weekly_qr.csv")


@app.route("/admin/export/monthly")
def export_monthly():
    if not session.get("logged_in"):
        return redirect(url_for("login"))

    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT vehicle_number, generated_date, expires_date
        FROM vehicle_qr
        WHERE generated_date >= CURRENT_DATE - INTERVAL '30 days'
        ORDER BY generated_date DESC
    """)
    rows = cur.fetchall()
    conn.close()

    return export_csv(rows, "monthly_qr.csv")

# ---------------- VERIFY ----------------
@app.route("/verify/<int:token_id>")
def verify(token_id):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT vehicle_number, expires_date
        FROM vehicle_qr
        WHERE id = %s
    """, (token_id,))
    row = cur.fetchone()
    conn.close()

    if not row:
        return render_template("verify.html", status="INVALID")

    vehicle, expiry = row
    today = date.today()
    status = "VALID" if today < expiry else "EXPIRED"

    return render_template(
        "verify.html",
        status=status,
        vehicle=vehicle,
        expiry=expiry.strftime("%d-%m-%Y")
    )

if __name__ == "__main__":
    app.run(debug=True)