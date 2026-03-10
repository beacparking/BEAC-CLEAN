from flask import Flask, render_template, request, redirect, url_for, session, send_file
import psycopg2
import psycopg2.errors
import os
import qrcode
import csv
import io
from datetime import datetime, timedelta, date

app = Flask(__name__)
app.secret_key = "beac_secret_key"

# ======================
# DATABASE / CONFIG
# ======================
DATABASE_URL = os.environ.get("DATABASE_URL")
BASE_URL = os.environ.get("BASE_URL")  # e.g. "http://192.168.1.7:5000"

def get_db():
    return psycopg2.connect(DATABASE_URL)

# ======================
# LOGIN
# ======================
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin123"
STATS_USERNAME = "beac"
STATS_PASSWORD = "beac"

@app.route("/")
def home():
    return redirect(url_for("login"))


@app.route("/robots.txt")
def robots():
    base = request.url_root.rstrip("/")
    return f"""User-agent: *
Allow: /
Sitemap: {base}/sitemap.xml
""", 200, {"Content-Type": "text/plain; charset=utf-8"}


@app.route("/sitemap.xml")
def sitemap():
    base = request.url_root.rstrip("/")
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>{base}/</loc><changefreq>weekly</changefreq><priority>1.0</priority></url>
  <url><loc>{base}/login</loc><changefreq>weekly</changefreq><priority>0.9</priority></url>
</urlset>"""
    return xml, 200, {"Content-Type": "application/xml; charset=utf-8"}


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session["logged_in"] = True
            return redirect(url_for("admin"))

        if username == STATS_USERNAME and password == STATS_PASSWORD:
            session["stats_logged_in"] = True
            return redirect(url_for("stats"))

        return render_template("login.html", error="Invalid credentials")

    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ======================
# ADMIN DASHBOARD
# ======================
@app.route("/admin", methods=["GET", "POST"])
def admin():
    if not session.get("logged_in"):
        return redirect(url_for("login"))

    qr = None
    error = None

    # Simple daily counts for today's date, shown in Daily report tab
    today = date.today()
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT truck_type, COUNT(*)
        FROM vehicle_qr
        WHERE generated_date = %s
        GROUP BY truck_type
        """,
        (today,),
    )
    rows = cur.fetchall()
    conn.close()

    total_today = 0
    bhutanese_today = 0
    indian_today = 0
    for t_type, cnt in rows:
        total_today += cnt
        if t_type == "Bhutanese":
            bhutanese_today = cnt
        elif t_type == "Indian":
            indian_today = cnt

    if request.method == "POST":
        vehicle = request.form.get("vehicle")
        selected_date = request.form.get("date")
        truck_type = request.form.get("truck_type")
        load_type = request.form.get("load_type")
        amount_collected = request.form.get("amount_collected")

        if not vehicle or not selected_date or not truck_type or not load_type or not amount_collected:
            error = "Vehicle number, date, truck type, load type and amount are required"
        else:
            generated_date = datetime.strptime(selected_date, "%Y-%m-%d").date()
            expires_date = generated_date + timedelta(days=2)  # today + tomorrow

            conn = get_db()
            cur = conn.cursor()

            try:
                # 🔢 DAILY TOKEN CALCULATION (separate per truck type)
                cur.execute("""
                    SELECT COALESCE(MAX(daily_token), 0) + 1
                    FROM vehicle_qr
                    WHERE generated_date = %s AND truck_type = %s
                """, (generated_date, truck_type))
                daily_token = cur.fetchone()[0]

                # INSERT NEW QR
                cur.execute("""
                    INSERT INTO vehicle_qr
                    (vehicle_number, truck_type, load_type, amount_collected, generated_date, expires_date, daily_token)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, (vehicle, truck_type, load_type, amount_collected, generated_date, expires_date, daily_token))

                token_id = cur.fetchone()[0]
                conn.commit()

            except psycopg2.errors.UniqueViolation:
                # 🔒 DUPLICATE LOCK — reuse existing QR
                conn.rollback()
                cur.execute("""
                    SELECT id, daily_token, expires_date
                    FROM vehicle_qr
                    WHERE vehicle_number = %s AND generated_date = %s
                """, (vehicle, generated_date))
                token_id, daily_token, expires_date = cur.fetchone()

            conn.close()

            base_url = BASE_URL or request.host_url
            if not base_url.endswith("/"):
                base_url += "/"
            qr_url = f"{base_url}verify/{token_id}"
            qr_path = f"static/qr/{token_id}.png"

            os.makedirs("static/qr", exist_ok=True)
            # Always overwrite so QR contains current base URL (important after deploy)
            qrcode.make(qr_url).save(qr_path)

            qr = {
                "token": daily_token,
                "vehicle": vehicle,
                "truck_type": truck_type,
                "load_type": load_type,
                "amount_collected": amount_collected,
                "expiry": expires_date.strftime("%d-%m-%Y"),
                "qr_path": qr_path,
                "qr_url": qr_url
            }

    return render_template(
        "admin.html",
        qr=qr,
        error=error,
        daily_counts={
            "total": total_today,
            "bhutanese": bhutanese_today,
            "indian": indian_today,
        },
    )


# ======================
# STATS DASHBOARD
# ======================
@app.route("/stats", methods=["GET"])
def stats():
    # Allow access if logged in as dedicated stats user OR as admin
    if not (session.get("stats_logged_in") or session.get("logged_in")):
        return redirect(url_for("login"))

    date_str = request.args.get("date")
    if date_str:
        stats_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    else:
        stats_date = date.today()

    conn = get_db()
    cur = conn.cursor()

    # Vehicle counts by truck type
    cur.execute(
        """
        SELECT truck_type, COUNT(*)
        FROM vehicle_qr
        WHERE generated_date = %s
        GROUP BY truck_type
        """,
        (stats_date,),
    )
    rows = cur.fetchall()
    total = 0
    bhutanese = 0
    indian = 0
    for t_type, cnt in rows:
        total += cnt
        if t_type == "Bhutanese":
            bhutanese = cnt
        elif t_type == "Indian":
            indian = cnt

    # Amounts and vehicle counts by truck type and load type
    cur.execute(
        """
        SELECT truck_type, load_type,
               COALESCE(SUM(amount_collected), 0),
               COUNT(*)
        FROM vehicle_qr
        WHERE generated_date = %s
        GROUP BY truck_type, load_type
        """,
        (stats_date,),
    )
    amount_rows = cur.fetchall()
    conn.close()

    amounts_bhutanese = {"total": 0, "geti": 0, "limestone": 0, "boulder": 0, "dust": 0, "other": 0}
    amounts_indian = {"total": 0, "geti": 0, "limestone": 0, "boulder": 0, "dust": 0, "other": 0}
    counts_bhutanese = {"geti": 0, "limestone": 0, "boulder": 0, "dust": 0, "other": 0}
    counts_indian = {"geti": 0, "limestone": 0, "boulder": 0, "dust": 0, "other": 0}

    for t_type, load_type, amt, cnt in amount_rows:
        amt = float(amt) if amt is not None else 0
        if t_type == "Bhutanese":
            amounts_bhutanese["total"] += amt
            if load_type in amounts_bhutanese:
                amounts_bhutanese[load_type] = amt
            if load_type in counts_bhutanese:
                counts_bhutanese[load_type] = cnt
        elif t_type == "Indian":
            amounts_indian["total"] += amt
            if load_type in amounts_indian:
                amounts_indian[load_type] = amt
            if load_type in counts_indian:
                counts_indian[load_type] = cnt

    stats_data = {
        "bhutanese": bhutanese,
        "indian": indian,
        "total": total,
        "amounts_bhutanese": amounts_bhutanese,
        "amounts_indian": amounts_indian,
        "counts_bhutanese": counts_bhutanese,
        "counts_indian": counts_indian,
    }

    return render_template("stats.html", stats=stats_data, stats_date=stats_date)


@app.route("/stats/export")
def stats_export():
    if not session.get("stats_logged_in"):
        return redirect(url_for("login"))

    date_str = request.args.get("date")
    if not date_str:
        return redirect(url_for("stats"))
    d = datetime.strptime(date_str, "%Y-%m-%d").date()
    truck_type = request.args.get("truck_type")

    conn = get_db()
    cur = conn.cursor()
    query = """
        SELECT daily_token, vehicle_number, truck_type, load_type, amount_collected, generated_date, expires_date
        FROM vehicle_qr
        WHERE generated_date = %s
    """
    params = [d]
    if truck_type:
        query += " AND truck_type = %s"
        params.append(truck_type)
    query += " ORDER BY daily_token"

    cur.execute(query, tuple(params))
    rows = cur.fetchall()
    conn.close()

    if truck_type == "Bhutanese":
        filename = f"stats_{d}_bhutanese.csv"
    elif truck_type == "Indian":
        filename = f"stats_{d}_indian.csv"
    else:
        filename = f"stats_{d}.csv"
    return export_csv(rows, filename)


# ======================
# VERIFY QR
# ======================
@app.route("/verify/<int:token_id>")
def verify(token_id):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT vehicle_number, truck_type, load_type, amount_collected, expires_date
        FROM vehicle_qr
        WHERE id = %s
    """, (token_id,))
    row = cur.fetchone()
    conn.close()

    if not row:
        return render_template("verify.html", status="INVALID")

    vehicle, truck_type, load_type, amount_collected, expiry = row
    today = date.today()

    status = "VALID" if today <= expiry else "EXPIRED"

    return render_template(
        "verify.html",
        status=status,
        vehicle=vehicle,
        truck_type=truck_type,
        load_type=load_type,
        amount_collected=amount_collected,
        expiry=expiry.strftime("%d-%m-%Y")
    )

# ======================
# CSV EXPORT UTIL
# ======================
def export_csv(rows, filename):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Daily Token", "Vehicle", "Truck Type", "Load Type", "Amount Collected"])

    for r in rows:
        writer.writerow(r[:5])

    return send_file(
        io.BytesIO(output.getvalue().encode()),
        mimetype="text/csv",
        as_attachment=True,
        download_name=filename
    )

# ======================
# EXPORT DAILY
# ======================
@app.route("/admin/export/day")
def export_day():
    if not session.get("logged_in"):
        return redirect(url_for("login"))

    d = datetime.strptime(request.args.get("date"), "%Y-%m-%d").date()
    truck_type = request.args.get("truck_type")

    conn = get_db()
    cur = conn.cursor()
    query = """
        SELECT daily_token, vehicle_number, truck_type, load_type, amount_collected, generated_date, expires_date
        FROM vehicle_qr
        WHERE generated_date = %s
    """
    params = [d]
    if truck_type:
        query += " AND truck_type = %s"
        params.append(truck_type)
    query += " ORDER BY daily_token"

    cur.execute(query, tuple(params))
    rows = cur.fetchall()
    conn.close()

    return export_csv(rows, f"daily_{d}.csv")

# ======================
# EXPORT WEEKLY
# ======================
@app.route("/admin/export/week")
def export_week():
    if not session.get("logged_in"):
        return redirect(url_for("login"))

    end = datetime.strptime(request.args.get("date"), "%Y-%m-%d").date()
    start = end - timedelta(days=6)
    truck_type = request.args.get("truck_type")

    conn = get_db()
    cur = conn.cursor()
    query = """
        SELECT daily_token, vehicle_number, truck_type, load_type, amount_collected, generated_date, expires_date
        FROM vehicle_qr
        WHERE generated_date BETWEEN %s AND %s
    """
    params = [start, end]
    if truck_type:
        query += " AND truck_type = %s"
        params.append(truck_type)
    query += " ORDER BY generated_date, daily_token"

    cur.execute(query, tuple(params))
    rows = cur.fetchall()
    conn.close()

    return export_csv(rows, f"weekly_{start}_to_{end}.csv")

# ======================
# EXPORT MONTHLY
# ======================
@app.route("/admin/export/month")
def export_month():
    if not session.get("logged_in"):
        return redirect(url_for("login"))

    month_str = request.args.get("month")  # format YYYY-MM
    truck_type = request.args.get("truck_type")

    # First day of selected month
    start = datetime.strptime(month_str, "%Y-%m").date().replace(day=1)
    # First day of next month
    if start.month == 12:
        next_month_start = start.replace(year=start.year + 1, month=1, day=1)
    else:
        next_month_start = start.replace(month=start.month + 1, day=1)

    conn = get_db()
    cur = conn.cursor()
    query = """
        SELECT daily_token, vehicle_number, truck_type, load_type, amount_collected, generated_date, expires_date
        FROM vehicle_qr
        WHERE generated_date >= %s AND generated_date < %s
    """
    params = [start, next_month_start]
    if truck_type:
        query += " AND truck_type = %s"
        params.append(truck_type)
    query += " ORDER BY generated_date, daily_token"

    cur.execute(query, tuple(params))
    rows = cur.fetchall()
    conn.close()

    return export_csv(rows, f"monthly_{start.strftime('%Y_%m')}.csv")

# ======================
# RUN
# ======================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)