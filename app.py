from flask import Flask, render_template, request, redirect, url_for, session, send_file
import psycopg2
import os
import qrcode
import csv
import io
from datetime import datetime, timedelta, date

app = Flask(__name__)
app.secret_key = "beac_secret_key"

# ======================
# DATABASE
# ======================
DATABASE_URL = os.environ.get("DATABASE_URL")

def get_db():
    return psycopg2.connect(DATABASE_URL)

# ======================
# LOGIN
# ======================
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

# ======================
# ADMIN
# ======================
@app.route("/admin", methods=["GET", "POST"])
def admin():
    if not session.get("logged_in"):
        return redirect(url_for("login"))

    qr = None
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
                # 🔹 Calculate DAILY TOKEN (per day)
                cur.execute("""
                    SELECT COALESCE(MAX(daily_token), 0) + 1
                    FROM vehicle_qr
                    WHERE generated_date = %s
                """, (generated_date,))
                daily_token = cur.fetchone()[0]

                # 🔹 Insert new QR
                cur.execute("""
                    INSERT INTO vehicle_qr
                    (vehicle_number, generated_date, expires_date, daily_token)
                    VALUES (%s, %s, %s, %s)
                    RETURNING id
                """, (vehicle, generated_date, expires_date, daily_token))

                token_id = cur.fetchone()[0]
                conn.commit()

            except psycopg2.errors.UniqueViolation:
                # 🔹 Reuse existing QR
                conn.rollback()
                cur.execute("""
                    SELECT id, daily_token, expires_date
                    FROM vehicle_qr
                    WHERE vehicle_number = %s AND generated_date = %s
                """, (vehicle, generated_date))
                token_id, daily_token, expires_date = cur.fetchone()

            conn.close()

            qr_url = f"{request.host_url}verify/{token_id}"
            qr_path = f"static/qr/{token_id}.png"

            os.makedirs("static/qr", exist_ok=True)
            if not os.path.exists(qr_path):
                qrcode.make(qr_url).save(qr_path)

            qr = {
                "token": daily_token,   # 👈 DISPLAY TOKEN
                "vehicle": vehicle,
                "expiry": expires_date.strftime("%d-%m-%Y"),
                "qr_path": qr_path,
                "qr_url": qr_url
            }

    return render_template("admin.html", qr=qr, error=error)

# ======================
# VERIFY
# ======================
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
    status = "VALID" if today <= expiry else "EXPIRED"

    return render_template(
        "verify.html",
        status=status,
        vehicle=vehicle,
        expiry=expiry.strftime("%d-%m-%Y")
    )

# ======================
# CSV EXPORT
# ======================
def export_csv(rows, filename):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Daily Token", "Vehicle", "Generated Date", "Expiry Date"])

    for r in rows:
        writer.writerow(r)

    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode()),
        mimetype="text/csv",
        as_attachment=True,
        download_name=filename
    )

@app.route("/admin/export/daily")
def export_daily():
    if not session.get("logged_in"):
        return redirect(url_for("login"))

    today = date.today()
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT daily_token, vehicle_number, generated_date, expires_date
        FROM vehicle_qr
        WHERE generated_date = %s
        ORDER BY daily_token
    """, (today,))
    rows = cur.fetchall()
    conn.close()

    return export_csv(rows, f"daily_{today}.csv")

@app.route("/admin/export/weekly")
def export_weekly():
    if not session.get("logged_in"):
        return redirect(url_for("login"))

    today = date.today()
    start = today - timedelta(days=6)

    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT daily_token, vehicle_number, generated_date, expires_date
        FROM vehicle_qr
        WHERE generated_date BETWEEN %s AND %s
        ORDER BY generated_date, daily_token
    """, (start, today))
    rows = cur.fetchall()
    conn.close()

    return export_csv(rows, "weekly.csv")

@app.route("/admin/export/monthly")
def export_monthly():
    if not session.get("logged_in"):
        return redirect(url_for("login"))

    start = date.today().replace(day=1)
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT daily_token, vehicle_number, generated_date, expires_date
        FROM vehicle_qr
        WHERE generated_date >= %s
        ORDER BY generated_date, daily_token
    """, (start,))
    rows = cur.fetchall()
    conn.close()

    return export_csv(rows, "monthly.csv")

# ======================
# RUN
# ======================
if __name__ == "__main__":
    app.run(debug=True)