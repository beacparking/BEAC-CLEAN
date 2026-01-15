from flask import Flask, render_template, request, redirect, url_for, session, Response
import psycopg2
import os
import qrcode
from datetime import datetime, timedelta, date

app = Flask(__name__)
app.secret_key = "beac_secret_key"

DATABASE_URL = os.environ.get("DATABASE_URL")

def get_db():
    return psycopg2.connect(DATABASE_URL)

# =========================
# AUTH CONFIG
# =========================
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin123"

# =========================
# LOGIN
# =========================
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

# =========================
# ADMIN
# =========================
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

# =========================
# VERIFY
# =========================
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
    today = date.today()

    status = "VALID" if today <= expiry else "EXPIRED"

    return render_template(
        "verify.html",
        status=status,
        vehicle=vehicle,
        expiry=expiry.strftime("%d-%m-%Y")
    )

# =========================
# CSV EXPORTS
# =========================
def csv_response(rows, filename):
    def generate():
        yield "Token,Vehicle Number,Generated Date,Expiry Date\n"
        for r in rows:
            yield f"{r[0]},{r[1]},{r[2]},{r[3]}\n"

    return Response(
        generate(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

@app.route("/export/day")
def export_day():
    if not session.get("logged_in"):
        return redirect(url_for("login"))

    d = datetime.strptime(request.args.get("date"), "%Y-%m-%d").date()

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

    return csv_response(rows, "daily.csv")

@app.route("/export/week")
def export_week():
    if not session.get("logged_in"):
        return redirect(url_for("login"))

    start = date.today() - timedelta(days=7)

    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, vehicle_number, generated_date, expires_date
        FROM vehicle_qr
        WHERE generated_date >= %s
        ORDER BY id
    """, (start,))
    rows = cur.fetchall()
    conn.close()

    return csv_response(rows, "weekly.csv")

@app.route("/export/month")
def export_month():
    if not session.get("logged_in"):
        return redirect(url_for("login"))

    start = date.today().replace(day=1)

    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, vehicle_number, generated_date, expires_date
        FROM vehicle_qr
        WHERE generated_date >= %s
        ORDER BY id
    """, (start,))
    rows = cur.fetchall()
    conn.close()

    return csv_response(rows, "monthly.csv")

# =========================
# RUN
# =========================
if __name__ == "__main__":
    app.run(debug=True)