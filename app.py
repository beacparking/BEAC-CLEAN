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
                cur.execute("""
                    INSERT INTO vehicle_qr (vehicle_number, generated_date, expires_date)
                    VALUES (%s, %s, %s)
                    RETURNING id
                """, (vehicle, generated_date, expires_date))
                token = cur.fetchone()[0]
                conn.commit()
            except psycopg2.errors.UniqueViolation:
                conn.rollback()
                cur.execute("""
                    SELECT id, expires_date
                    FROM vehicle_qr
                    WHERE vehicle_number = %s AND generated_date = %s
                """, (vehicle, generated_date))
                token, expires_date = cur.fetchone()

            conn.close()

            qr_url = f"{request.host_url}verify/{token}"
            qr_path = f"static/qr/{token}.png"
            os.makedirs("static/qr", exist_ok=True)

            if not os.path.exists(qr_path):
                qrcode.make(qr_url).save(qr_path)

            qr = {
                "token": token,
                "vehicle": vehicle,
                "expiry": expires_date.strftime("%d-%m-%Y"),
                "qr_path": qr_path,
                "qr_url": qr_url
            }

    return render_template("admin.html", qr=qr, error=error)

# ======================
# VERIFY
# ======================
@app.route("/verify/<int:token>")
def verify(token):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT vehicle_number, expires_date
        FROM vehicle_qr
        WHERE id = %s
    """, (token,))
    row = cur.fetchone()
    conn.close()

    if not row:
        return render_template("verify.html", status="INVALID")

    vehicle, expiry = row
    status = "VALID" if date.today() <= expiry else "EXPIRED"

    return render_template(
        "verify.html",
        status=status,
        vehicle=vehicle,
        expiry=expiry.strftime("%d-%m-%Y")
    )

# ======================
# CSV HELPER
# ======================
def export_csv(rows, filename):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Token", "Vehicle Number", "Generated Date", "Expiry Date"])

    for r in rows:
        writer.writerow(r)

    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode()),
        mimetype="text/csv",
        as_attachment=True,
        download_name=filename
    )

# ======================
# EXPORT — DAILY (SELECTED DATE)
# ======================
@app.route("/admin/export/day")
def export_day():
    if not session.get("logged_in"):
        return redirect(url_for("login"))

    selected = request.args.get("date")
    d = datetime.strptime(selected, "%Y-%m-%d").date()

    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, vehicle_number, generated_date, expires_date
        FROM vehicle_qr
        WHERE generated_date = %s
        ORDER BY id
    """, (d,))
    rows = cur.fetchall()
    conn.close()

    return export_csv(rows, f"daily_{d}.csv")

# ======================
# EXPORT — WEEKLY (LAST 7 DAYS FROM SELECTED DATE)
# ======================
@app.route("/admin/export/week")
def export_week():
    if not session.get("logged_in"):
        return redirect(url_for("login"))

    selected = request.args.get("date")
    end = datetime.strptime(selected, "%Y-%m-%d").date()
    start = end - timedelta(days=6)

    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, vehicle_number, generated_date, expires_date
        FROM vehicle_qr
        WHERE generated_date BETWEEN %s AND %s
        ORDER BY id
    """, (start, end))
    rows = cur.fetchall()
    conn.close()

    return export_csv(rows, f"weekly_{start}_to_{end}.csv")

# ======================
# EXPORT — MONTHLY (SELECTED MONTH)
# ======================
@app.route("/admin/export/month")
def export_month():
    if not session.get("logged_in"):
        return redirect(url_for("login"))

    month = request.args.get("month")  # YYYY-MM
    year, mon = map(int, month.split("-"))
    start = date(year, mon, 1)
    end = (start + timedelta(days=32)).replace(day=1)

    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, vehicle_number, generated_date, expires_date
        FROM vehicle_qr
        WHERE generated_date >= %s AND generated_date < %s
        ORDER BY id
    """, (start, end))
    rows = cur.fetchall()
    conn.close()

    return export_csv(rows, f"monthly_{month}.csv")

# ======================
# RUN
# ======================
if __name__ == "__main__":
    app.run(debug=True)