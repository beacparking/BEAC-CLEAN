from flask import Flask, render_template, request, redirect, url_for, session, send_file
import psycopg2
import psycopg2.errors
import os
import qrcode
import csv
import io
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo

app = Flask(__name__)
app.secret_key = "beac_secret_key"

# ======================
# DATABASE / CONFIG
# ======================
DATABASE_URL = os.environ.get("DATABASE_URL")
BASE_URL = os.environ.get("BASE_URL")  # e.g. "http://192.168.1.7:5000"

def get_db():
    return psycopg2.connect(DATABASE_URL)


# /members, /stats, /verify/export: hide these from display for *today only* (ramps over the day).
DISPLAY_HIDE_BHUTAN_100_CAP = 7
DISPLAY_HIDE_INDIAN_150_CAP = 8
# Ramp hits 100% at 7:30 PM Asia/Thimphu; after that, full 7 + 8 hide (if matching rows exist).
DISPLAY_HIDE_RAMP_END_HOURS_FROM_MIDNIGHT = 19.5
DISPLAY_HIDE_TZ = ZoneInfo("Asia/Thimphu")


def _ramped_hide_counts_today(bhutan_100_count, indian_150_count, view_date):
    """Return (bhutan_hide, indian_hide). Non-zero only when view_date is today."""
    if view_date != date.today():
        return 0, 0
    now = datetime.now(DISPLAY_HIDE_TZ)
    hours_elapsed = now.hour + now.minute / 60.0 + now.second / 3600.0
    ramp = min(1.0, hours_elapsed / DISPLAY_HIDE_RAMP_END_HOURS_FROM_MIDNIGHT)
    bh = round(min(DISPLAY_HIDE_BHUTAN_100_CAP, bhutan_100_count) * ramp)
    ih = round(min(DISPLAY_HIDE_INDIAN_150_CAP, indian_150_count) * ramp)
    return bh, ih


# ======================
# LOGIN
# ======================
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin123"
STATS_USERNAME = "620443"
STATS_PASSWORD = "620443"
MEMBERS_USERNAME = "member"
MEMBERS_PASSWORD = "member"
EXPORT_USERNAME = "ADD"
EXPORT_PASSWORD = "ADD123"

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

        if username == MEMBERS_USERNAME and password == MEMBERS_PASSWORD:
            session["members_logged_in"] = True
            return redirect(url_for("members"))

        if username == EXPORT_USERNAME and password == EXPORT_PASSWORD:
            session["export_logged_in"] = True
            return redirect(url_for("verify_export"))

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

    # Daily counts
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

    total_today = 0
    bhutanese_today = 0
    indian_today = 0
    for t_type, cnt in rows:
        total_today += cnt
        if t_type == "Bhutanese":
            bhutanese_today = cnt
        elif t_type == "Indian":
            indian_today = cnt

    # Unpaid tokens (amount 0 or null) for today
    cur.execute(
        """
        SELECT id, truck_type, daily_token, vehicle_number, generated_date, load_type
        FROM vehicle_qr
        WHERE generated_date = %s
          AND (amount_collected IS NULL OR amount_collected::numeric <= 0)
        ORDER BY truck_type, daily_token
        """,
        (today,),
    )
    unpaid_rows = cur.fetchall()
    conn.close()

    unpaid_bhutanese = []
    unpaid_indian = []
    for rec_id, t_type, token, vehicle, gen_date, load_type in unpaid_rows:
        item = {
            "id": rec_id,
            "token": token,
            "vehicle": vehicle,
            "truck_type": t_type,
            "date": gen_date,
            "load_type": load_type,
        }
        if t_type == "Bhutanese":
            unpaid_bhutanese.append(item)
        elif t_type == "Indian":
            unpaid_indian.append(item)

    if request.method == "POST":
        record_id = request.form.get("record_id")
        daily_token_input = request.form.get("daily_token")
        vehicle = request.form.get("vehicle")
        selected_date = request.form.get("date")
        truck_type = request.form.get("truck_type")
        load_type = request.form.get("load_type")
        ticket_number = request.form.get("ticket_number")
        amount_collected = request.form.get("amount_collected")

        # If editing an existing token, allow changing vehicle, token number, ticket and amount
        if record_id:
            if not daily_token_input:
                error = "Token number is required to update."
            else:
                try:
                    daily_token_update = int(daily_token_input)
                    if daily_token_update < 1:
                        error = "Token number must be at least 1."
                except ValueError:
                    error = "Token number must be a number."
                    daily_token_update = None
            if not error and not amount_collected:
                error = "Amount is required to update."
            elif not error:
                try:
                    if float(amount_collected) > 500:
                        error = "Amount cannot exceed 500."
                except (ValueError, TypeError):
                    error = "Amount must be a number."
            if not error and record_id:
                conn = get_db()
                cur = conn.cursor()
                cur.execute(
                    """
                    SELECT 1 FROM vehicle_qr v2
                    WHERE v2.generated_date = (SELECT generated_date FROM vehicle_qr WHERE id = %s)
                      AND v2.daily_token = %s
                      AND v2.truck_type = (SELECT truck_type FROM vehicle_qr WHERE id = %s)
                      AND v2.id != %s
                    """,
                    (record_id, daily_token_update, record_id, record_id),
                )
                if cur.fetchone():
                    conn.close()
                    error = (
                        "Another vehicle of the same truck type already uses this token number on that date."
                    )
                else:
                    cur.execute(
                        """
                        UPDATE vehicle_qr
                        SET vehicle_number = %s,
                            ticket_number = %s,
                            amount_collected = %s,
                            daily_token = %s
                        WHERE id = %s
                        RETURNING vehicle_number, truck_type, load_type, daily_token, expires_date, ticket_number
                        """,
                        (vehicle, ticket_number, amount_collected, daily_token_update, record_id),
                    )
                    row = cur.fetchone()
                    conn.commit()
                    conn.close()

                    if row:
                        vehicle, truck_type, load_type, daily_token, expires_date, ticket_number_row = row
                        qr = {
                            "token": daily_token,
                            "vehicle": vehicle,
                            "truck_type": truck_type,
                            "load_type": load_type,
                            "amount_collected": amount_collected,
                            "ticket_number": ticket_number_row or "",
                            "expiry": expires_date.strftime("%d-%m-%Y"),
                            "qr_path": None,
                            "qr_url": None,
                        }
        else:
            if not daily_token_input or not vehicle or not selected_date or not truck_type or not load_type or not amount_collected:
                error = "Token number, vehicle number, date, truck type, load type and amount are required"
            else:
                try:
                    daily_token = int(daily_token_input)
                except ValueError:
                    error = "Token number must be a number"
                    daily_token = None

            if not error:
                try:
                    if float(amount_collected) > 500:
                        error = "Amount cannot exceed 500."
                except (ValueError, TypeError):
                    error = "Amount must be a number."

            if not error:
                generated_date = datetime.strptime(selected_date, "%Y-%m-%d").date()
                expires_date = generated_date + timedelta(days=2)  # today + tomorrow

                conn = get_db()
                cur = conn.cursor()

                def token_taken_same_type(exclude_id=None):
                    if exclude_id is None:
                        cur.execute(
                            """
                            SELECT 1 FROM vehicle_qr
                            WHERE generated_date = %s AND daily_token = %s AND truck_type = %s
                            """,
                            (generated_date, daily_token, truck_type),
                        )
                    else:
                        cur.execute(
                            """
                            SELECT 1 FROM vehicle_qr
                            WHERE generated_date = %s AND daily_token = %s AND truck_type = %s
                              AND id != %s
                            """,
                            (generated_date, daily_token, truck_type, exclude_id),
                        )
                    return cur.fetchone() is not None

                token_id = None
                if token_taken_same_type():
                    conn.close()
                    error = (
                        "This token number is already used for another "
                        + truck_type
                        + " truck on this date. Indian and Bhutanese can share the same number."
                    )
                else:
                    try:
                        # INSERT NEW QR
                        cur.execute("""
                            INSERT INTO vehicle_qr
                            (vehicle_number, truck_type, load_type, ticket_number, amount_collected, generated_date, expires_date, daily_token)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                            RETURNING id
                        """, (vehicle, truck_type, load_type, ticket_number, amount_collected, generated_date, expires_date, daily_token))

                        token_id = cur.fetchone()[0]
                        conn.commit()

                    except psycopg2.errors.UniqueViolation:
                        # Same vehicle + date already exists: update with new token and details
                        conn.rollback()
                        cur.execute(
                            "SELECT id FROM vehicle_qr WHERE vehicle_number = %s AND generated_date = %s",
                            (vehicle, generated_date),
                        )
                        existing_row = cur.fetchone()
                        if not existing_row:
                            conn.close()
                            error = "Could not update existing record."
                        elif token_taken_same_type(exclude_id=existing_row[0]):
                            conn.close()
                            error = (
                                "This token number is already used for another "
                                + truck_type
                                + " truck on this date. Indian and Bhutanese can share the same number."
                            )
                        else:
                            cur.execute("""
                                UPDATE vehicle_qr
                                SET truck_type = %s, load_type = %s, ticket_number = %s,
                                    amount_collected = %s, daily_token = %s
                                WHERE vehicle_number = %s AND generated_date = %s
                                RETURNING id, daily_token, expires_date
                            """, (truck_type, load_type, ticket_number, amount_collected, daily_token, vehicle, generated_date))
                            token_id, daily_token, expires_date = cur.fetchone()
                            conn.commit()

                    if not error and token_id is not None:
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
                            "ticket_number": ticket_number or "",
                            "expiry": expires_date.strftime("%d-%m-%Y"),
                            "qr_path": qr_path,
                            "qr_url": qr_url
                        }
                    elif not error:
                        conn.close()
    # Last 3 vehicles for today (any truck type)
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT daily_token, vehicle_number, generated_date, truck_type,
               load_type, ticket_number, amount_collected
        FROM vehicle_qr
        WHERE generated_date = %s
        ORDER BY id DESC
        LIMIT 3
        """,
        (today,),
    )
    last_rows = cur.fetchall()

    last_entries = [
        {
            "token": r[0],
            "vehicle": r[1],
            "date": r[2],
            "truck_type": r[3],
            "load_type": r[4],
            "ticket_number": r[5],
            "amount_collected": r[6],
        }
        for r in last_rows
    ]

    # Search: by token = today only; by vehicle plate = all dates
    search_vehicle = request.args.get("search_vehicle")
    search_rows = []
    search_mode = None
    if search_vehicle:
        try:
            token_val = int(search_vehicle)
        except ValueError:
            token_val = None

        if token_val is not None:
            search_mode = "token"
            cur.execute(
                """
                SELECT id, daily_token, ticket_number, generated_date, amount_collected, vehicle_number, truck_type, load_type
                FROM vehicle_qr
                WHERE daily_token = %s AND generated_date = %s
                ORDER BY daily_token DESC
                """,
                (token_val, today),
            )
        else:
            search_mode = "vehicle"
            cur.execute(
                """
                SELECT id, daily_token, ticket_number, generated_date, amount_collected, vehicle_number, truck_type, load_type
                FROM vehicle_qr
                WHERE vehicle_number = %s
                ORDER BY generated_date DESC, daily_token DESC
                """,
                (search_vehicle,),
            )
        search_rows = cur.fetchall()

    conn.close()

    return render_template(
        "admin.html",
        qr=qr,
        error=error,
        default_date=today,
        search_vehicle=search_vehicle,
        search_rows=search_rows,
        search_mode=search_mode,
        daily_counts={
            "total": total_today,
            "bhutanese": bhutanese_today,
            "indian": indian_today,
        },
        last_entries=last_entries,
        unpaid_bhutanese=unpaid_bhutanese,
        unpaid_indian=unpaid_indian,
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

    # Fetch record-level data so we can hide Indian vehicles deterministically
    cur.execute(
        """
        SELECT id, truck_type, daily_token, load_type, amount_collected
        FROM vehicle_qr
        WHERE generated_date = %s
        ORDER BY truck_type, daily_token
        """,
        (stats_date,),
    )
    all_rows = cur.fetchall()
    conn.close()

    bhutan_rows = [r for r in all_rows if r[1] == "Bhutanese"]
    indian_rows = [r for r in all_rows if r[1] == "Indian"]

    bhutan_100_rows = [
        r for r in bhutan_rows
        if r[4] is not None and float(r[4]) == 100.0
    ]
    indian_150_rows = [
        r for r in indian_rows
        if r[4] is not None and float(r[4]) == 150.0
    ]
    bhutan_hide, indian_hide = _ramped_hide_counts_today(
        len(bhutan_100_rows), len(indian_150_rows), stats_date
    )
    hidden_bhutan_ids = set(
        r[0] for r in sorted(bhutan_100_rows, key=lambda r: r[2])[:bhutan_hide]
    )
    hidden_indian_ids = set(
        r[0] for r in sorted(indian_150_rows, key=lambda r: r[2])[:indian_hide]
    )
    hidden_ids = hidden_bhutan_ids | hidden_indian_ids

    bhutanese = len(bhutan_rows)
    indian_actual = len(indian_rows)
    bhutan_display = max(0, bhutanese - len(hidden_bhutan_ids))
    indian_display = max(0, indian_actual - len(hidden_indian_ids))
    total = bhutan_display + indian_display

    amounts_bhutanese = {"total": 0, "geti": 0, "limestone": 0, "boulder": 0, "dust": 0, "other": 0}
    amounts_indian = {"total": 0, "geti": 0, "limestone": 0, "boulder": 0, "dust": 0, "other": 0}
    counts_bhutanese = {"geti": 0, "limestone": 0, "boulder": 0, "dust": 0, "other": 0}
    counts_indian = {"geti": 0, "limestone": 0, "boulder": 0, "dust": 0, "other": 0}

    for row in bhutan_rows:
        rec_id, _, _, load_type, amount_collected = row
        if rec_id in hidden_ids:
            continue
        amt = float(amount_collected) if amount_collected is not None else 0.0
        amounts_bhutanese["total"] += amt
        if load_type in amounts_bhutanese:
            amounts_bhutanese[load_type] += amt
        if load_type in counts_bhutanese:
            counts_bhutanese[load_type] += 1

    for row in indian_rows:
        rec_id, _, _, load_type, amount_collected = row
        if rec_id in hidden_ids:
            continue
        amt = float(amount_collected) if amount_collected is not None else 0.0
        amounts_indian["total"] += amt
        if load_type in amounts_indian:
            amounts_indian[load_type] += amt
        if load_type in counts_indian:
            counts_indian[load_type] += 1

    stats_data = {
        "bhutanese": bhutan_display,
        "indian": indian_display,
        "total": total,
        "amounts_bhutanese": amounts_bhutanese,
        "amounts_indian": amounts_indian,
        "counts_bhutanese": counts_bhutanese,
        "counts_indian": counts_indian,
    }

    return render_template("stats.html", stats=stats_data, stats_date=stats_date)


# ======================
# BEA MEMBERS (today only: hide up to 7 Bhutanese @100 + 8 Indian @150 Nu, ramped over the day)
# ======================
@app.route("/members", methods=["GET"])
def members():
    if not session.get("members_logged_in"):
        return redirect(url_for("login"))

    date_str = request.args.get("date")
    if date_str:
        members_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    else:
        members_date = date.today()

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT truck_type, COUNT(*)
        FROM vehicle_qr
        WHERE generated_date = %s
        GROUP BY truck_type
        """,
        (members_date,),
    )
    rows = cur.fetchall()

    bhutanese = 0
    indian_actual = 0
    for t_type, cnt in rows:
        if t_type == "Bhutanese":
            bhutanese = cnt
        elif t_type == "Indian":
            indian_actual = cnt

    cur.execute(
        """
        SELECT COUNT(*)
        FROM vehicle_qr
        WHERE generated_date = %s
          AND truck_type = 'Bhutanese'
          AND amount_collected = 100
        """,
        (members_date,),
    )
    bhutan_100 = cur.fetchone()[0] or 0

    cur.execute(
        """
        SELECT COUNT(*)
        FROM vehicle_qr
        WHERE generated_date = %s
          AND truck_type = 'Indian'
          AND amount_collected = 150
        """,
        (members_date,),
    )
    indian_150 = cur.fetchone()[0] or 0

    # Amounts collected for selected date
    cur.execute(
        """
        SELECT
          COALESCE(SUM(amount_collected), 0),
          COALESCE(SUM(CASE WHEN truck_type = 'Bhutanese' THEN amount_collected END), 0),
          COALESCE(SUM(CASE WHEN truck_type = 'Indian' THEN amount_collected END), 0)
        FROM vehicle_qr
        WHERE generated_date = %s
        """,
        (members_date,),
    )
    amt_row = cur.fetchone()
    amount_total = float(amt_row[0] or 0)
    amount_bhutanese = float(amt_row[1] or 0)
    amount_indian = float(amt_row[2] or 0)
    conn.close()

    bhutan_sub, indian_sub = _ramped_hide_counts_today(bhutan_100, indian_150, members_date)

    bhutan_display = max(0, bhutanese - bhutan_sub)
    indian_display = max(0, indian_actual - indian_sub)

    amount_subtracted = bhutan_sub * 100.0 + indian_sub * 150.0
    amount_total_display = max(0.0, amount_total - amount_subtracted)
    amount_bhutanese_display = max(0.0, amount_bhutanese - bhutan_sub * 100.0)
    amount_indian_display = max(0.0, amount_indian - indian_sub * 150.0)

    return render_template(
        "members.html",
        members_date=members_date,
        bhutanese=bhutan_display,
        indian=indian_display,
        indian_actual=indian_actual,
        amount_total=amount_total_display,
        amount_bhutanese=amount_bhutanese_display,
        amount_indian=amount_indian_display,
        amount_subtracted=amount_subtracted,
        subtraction=indian_sub,
    )


@app.route("/stats/export")
def stats_export():
    if not session.get("stats_logged_in"):
        return redirect(url_for("login"))

    date_str = request.args.get("date")
    if not date_str:
        return redirect(url_for("stats"))
    d = datetime.strptime(date_str, "%Y-%m-%d").date()
    truck_type = request.args.get("truck_type")
    summary = request.args.get("summary")
    only_150 = request.args.get("only_150") or request.args.get("only_200")

    # Summary CSV: single row with total / Bhutanese / Indian amounts
    if summary == "1":
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
              COALESCE(SUM(CASE WHEN truck_type = 'Bhutanese' THEN amount_collected END), 0) AS bhutanese_amount,
              COALESCE(SUM(CASE WHEN truck_type = 'Indian' THEN amount_collected END), 0) AS indian_amount
            FROM vehicle_qr
            WHERE generated_date = %s
            """,
            (d,),
        )
        row = cur.fetchone()
        conn.close()

        bhutan_amt = float(row[0] or 0)
        indian_amt = float(row[1] or 0)
        total_amt = bhutan_amt + indian_amt

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Date", "Total amount", "Bhutanese amount", "Indian amount"])
        writer.writerow(
            [d.isoformat(), f"{total_amt:.2f}", f"{bhutan_amt:.2f}", f"{indian_amt:.2f}"]
        )

        return send_file(
            io.BytesIO(output.getvalue().encode()),
            mimetype="text/csv",
            as_attachment=True,
            download_name=f"stats_summary_{d}.csv",
        )

    # CSV of Indian vehicles with amount 150 (the ones hidden on BEA members page)
    if only_150 == "1":
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT daily_token, truck_type, load_type, amount_collected, ticket_number
            FROM vehicle_qr
            WHERE generated_date = %s
              AND truck_type = 'Indian'
              AND amount_collected = 150
            ORDER BY daily_token
            """,
            (d,),
        )
        rows = cur.fetchall()
        conn.close()

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Token", "Truck Type", "Load Type", "Amount", "Ticket Number"])
        for r in rows:
            writer.writerow(r)

        return send_file(
            io.BytesIO(output.getvalue().encode()),
            mimetype="text/csv",
            as_attachment=True,
            download_name=f"stats_indian_150_{d}.csv",
        )

    conn = get_db()
    cur = conn.cursor()
    query = """
        SELECT daily_token, vehicle_number, truck_type, load_type, ticket_number, amount_collected, generated_date, expires_date
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
# VERIFY PAGE: CSV DOWNLOAD (ADD / ADD123)
# ======================
@app.route("/verify/export")
def verify_export_csv():
    if not session.get("export_logged_in"):
        return redirect(url_for("verify_export"))
    date_str = request.args.get("date")
    bhutan = request.args.get("bhutan") == "1"
    indian = request.args.get("indian") == "1"
    if not date_str or (not bhutan and not indian):
        return redirect(url_for("verify_export", error="Select a date and at least one vehicle type."))
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return redirect(url_for("verify_export", error="Invalid date."))

    conn = get_db()
    cur = conn.cursor()

    bhutan_100_count = 0
    indian_150_count = 0
    if d == date.today():
        if bhutan:
            cur.execute(
                """
                SELECT COUNT(*)
                FROM vehicle_qr
                WHERE generated_date = %s
                  AND truck_type = 'Bhutanese'
                  AND amount_collected = 100
                """,
                (d,),
            )
            bhutan_100_count = cur.fetchone()[0] or 0
        if indian:
            cur.execute(
                """
                SELECT COUNT(*)
                FROM vehicle_qr
                WHERE generated_date = %s
                  AND truck_type = 'Indian'
                  AND amount_collected = 150
                """,
                (d,),
            )
            indian_150_count = cur.fetchone()[0] or 0
    bhutan_sub, indian_sub = _ramped_hide_counts_today(bhutan_100_count, indian_150_count, d)

    # Fetch rows; drop Bhutanese @100 and Indian @150 to match /members for today only
    if bhutan and indian:
        cur.execute(
            """
            SELECT truck_type, vehicle_number, load_type, amount_collected
            FROM vehicle_qr
            WHERE generated_date = %s
              AND truck_type IN ('Bhutanese', 'Indian')
            ORDER BY truck_type, daily_token
            """,
            (d,),
        )
    elif bhutan:
        cur.execute(
            """
            SELECT truck_type, vehicle_number, load_type, amount_collected
            FROM vehicle_qr
            WHERE generated_date = %s AND truck_type = 'Bhutanese'
            ORDER BY daily_token
            """,
            (d,),
        )
    else:
        cur.execute(
            """
            SELECT truck_type, vehicle_number, load_type, amount_collected
            FROM vehicle_qr
            WHERE generated_date = %s AND truck_type = 'Indian'
            ORDER BY daily_token
            """,
            (d,),
        )

    all_rows = cur.fetchall()
    conn.close()

    rows = []
    hide_bhutan_left = bhutan_sub
    hide_indian_left = indian_sub
    for t_type, vehicle_number, load_type, amount_collected in all_rows:
        if (
            t_type == "Bhutanese"
            and hide_bhutan_left > 0
            and amount_collected is not None
            and float(amount_collected) == 100.0
        ):
            hide_bhutan_left -= 1
            continue
        if (
            t_type == "Indian"
            and hide_indian_left > 0
            and amount_collected is not None
            and float(amount_collected) == 150.0
        ):
            hide_indian_left -= 1
            continue
        rows.append((vehicle_number, load_type, amount_collected))

    output = io.StringIO()
    writer = csv.writer(output)
    # Serial number instead of token number
    writer.writerow(["Serial number", "Vehicle number", "Type of load", "Amount"])
    for idx, r in enumerate(rows, start=1):
        vehicle_number, load_type, amount_collected = r
        writer.writerow([
            str(idx),
            str(vehicle_number) if vehicle_number is not None else "",
            str(load_type) if load_type is not None else "",
            str(amount_collected) if amount_collected is not None else "",
        ])
    return send_file(
        io.BytesIO(output.getvalue().encode("utf-8-sig")),
        mimetype="text/csv",
        as_attachment=True,
        download_name=f"vehicles_{d}.csv"
    )


@app.route("/verify", methods=["GET", "POST"])
def verify_export():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        if username == EXPORT_USERNAME and password == EXPORT_PASSWORD:
            session["export_logged_in"] = True
            return redirect(url_for("verify_export"))
        return render_template("verify.html", login_error="Invalid credentials")
    if not session.get("export_logged_in"):
        return render_template("verify.html", login_error=request.args.get("error"))
    return render_template("verify.html", logged_in=True, error=request.args.get("error"))


# ======================
# VERIFY QR (public scan by token id)
# ======================
@app.route("/verify/<int:token_id>")
def verify_qr(token_id):
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
        return render_template("verify_qr.html", status="INVALID")

    vehicle, truck_type, load_type, amount_collected, expiry = row
    today = date.today()

    status = "VALID" if today <= expiry else "EXPIRED"

    return render_template(
        "verify_qr.html",
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
    writer.writerow(["Daily Token", "Vehicle", "Truck Type", "Load Type", "Ticket Number", "Amount Collected"])

    for r in rows:
        # Ensure each value is written as string so token numbers (e.g. 1) always show
        row = r[:6]
        writer.writerow([str(x) if x is not None else "" for x in row])

    return send_file(
        io.BytesIO(output.getvalue().encode("utf-8-sig")),
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
        SELECT daily_token, vehicle_number, truck_type, load_type, ticket_number, amount_collected, generated_date, expires_date
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
        SELECT daily_token, vehicle_number, truck_type, load_type, ticket_number, amount_collected, generated_date, expires_date
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