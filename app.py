from flask import Flask, render_template, request, redirect, url_for, session, send_file
import psycopg2
import psycopg2.errors
import os
import qrcode
import csv
import io
import math
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


def _thimphu_today():
    return datetime.now(DISPLAY_HIDE_TZ).date()


def _display_amount_eq(val, nu):
    """Match Nu amounts from DB (Decimal/float) to whole-number targets for hide rules."""
    if val is None:
        return False
    try:
        return abs(float(val) - float(nu)) < 0.5
    except (TypeError, ValueError):
        return False


def _ramped_hide_counts_today(bhutan_total_count, indian_total_count, view_date):
    """Return (bhutan_hide, indian_hide). Non-zero only when view_date is *today* in Asia/Thimphu.

    Caps use **all** Bhutanese / Indian trucks that day (not only @100 / @150), so we can hide
    8 Indians and 7 Bhutanese whenever at least that many trucks exist. Which rows are hidden
    is chosen in `_hidden_vehicle_ids_from_rows` (prefer 150 / 100 Nu, then others by token).
    Bhutanese CHIMIRD / VAJRA (vehicle number or load type) are never hidden.
    """
    if view_date != _thimphu_today():
        return 0, 0
    now = datetime.now(DISPLAY_HIDE_TZ)
    hours_elapsed = now.hour + now.minute / 60.0 + now.second / 3600.0

    cap_bh = min(DISPLAY_HIDE_BHUTAN_100_CAP, bhutan_total_count)
    cap_ih = min(DISPLAY_HIDE_INDIAN_150_CAP, indian_total_count)
    max_hide = cap_bh + cap_ih
    if max_hide == 0:
        return 0, 0

    if hours_elapsed >= DISPLAY_HIDE_RAMP_END_HOURS_FROM_MIDNIGHT:
        return cap_bh, cap_ih

    ramp_frac = hours_elapsed / DISPLAY_HIDE_RAMP_END_HOURS_FROM_MIDNIGHT
    target_total = min(max_hide, max(0, math.floor(max_hide * ramp_frac + 0.5)))

    if cap_bh == 0:
        return 0, min(cap_ih, target_total)
    if cap_ih == 0:
        return min(cap_bh, target_total), 0

    # Indian first: ensures target_total==15 => 8 Indian + 7 Bhutan when caps allow
    hide_ih = min(cap_ih, target_total)
    hide_bh = min(cap_bh, target_total - hide_ih)

    shortfall = target_total - hide_bh - hide_ih
    while shortfall > 0:
        if hide_bh < cap_bh:
            hide_bh += 1
            shortfall -= 1
        elif hide_ih < cap_ih:
            hide_ih += 1
            shortfall -= 1
        else:
            break

    return hide_bh, hide_ih


def _bhutan_protected_from_member_hide(row):
    """
    Bhutanese trucks that must never be hidden from members / verify export:
    CHIMIRD and VAJRA fleets (vehicle number or load type text).
    row: (id, truck_type, daily_token, load_type, amount_collected[, vehicle_number])
    """
    if row[1] != "Bhutanese":
        return False
    vn = ""
    if len(row) > 5 and row[5] is not None:
        vn = str(row[5])
    lt = str(row[3] or "")
    blob = f"{vn} {lt}".upper()
    return "CHIMIRD" in blob or "VAJRA" in blob


def _hidden_vehicle_ids_from_rows(all_rows, hide_bh, hide_ih):
    """Rows: (id, truck_type, daily_token, load_type, amount_collected[, vehicle_number])."""
    bhutan_rows = [
        r
        for r in all_rows
        if r[1] == "Bhutanese" and not _bhutan_protected_from_member_hide(r)
    ]
    indian_rows = [r for r in all_rows if r[1] == "Indian"]
    bh_sorted = sorted(
        bhutan_rows,
        key=lambda r: (0 if _display_amount_eq(r[4], 100) else 1, r[2]),
    )
    in_sorted = sorted(
        indian_rows,
        key=lambda r: (0 if _display_amount_eq(r[4], 150) else 1, r[2]),
    )
    ids = set()
    for r in in_sorted[:hide_ih]:
        ids.add(r[0])
    for r in bh_sorted[:hide_bh]:
        ids.add(r[0])
    return ids


def _amount_hidden_by_type(all_rows, hidden_ids):
    """Same row shape as _hidden_vehicle_ids_from_rows. Returns (bhutan_sum, indian_sum)."""
    b_amt = 0.0
    i_amt = 0.0
    for r in all_rows:
        if r[0] not in hidden_ids:
            continue
        amt = float(r[4]) if r[4] is not None else 0.0
        if r[1] == "Bhutanese":
            b_amt += amt
        elif r[1] == "Indian":
            i_amt += amt
    return b_amt, i_amt


def _amounts_visible_nu(detail_rows, hidden_ids):
    """Nu totals on rows not hidden (members, stats net, summary CSV)."""
    b_amt = 0.0
    i_amt = 0.0
    for r in detail_rows:
        if r[0] in hidden_ids:
            continue
        amt = float(r[4]) if r[4] is not None else 0.0
        if r[1] == "Bhutanese":
            b_amt += amt
        elif r[1] == "Indian":
            i_amt += amt
    return b_amt, i_amt


def _ensure_member_hide_override_table(cur):
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS member_hide_override (
            for_date DATE PRIMARY KEY,
            bhutan_count INTEGER NOT NULL DEFAULT 0,
            indian_count INTEGER NOT NULL DEFAULT 0,
            bhutan_amount NUMERIC(12, 2),
            indian_amount NUMERIC(12, 2)
        )
        """
    )


def _fetch_member_hide_override(for_date):
    conn = get_db()
    cur = conn.cursor()
    try:
        _ensure_member_hide_override_table(cur)
        cur.execute(
            """
            SELECT bhutan_count, indian_count, bhutan_amount, indian_amount
            FROM member_hide_override
            WHERE for_date = %s
            """,
            (for_date,),
        )
        row = cur.fetchone()
    finally:
        conn.close()
    if not row:
        return None
    return {
        "bhutan_count": int(row[0] or 0),
        "indian_count": int(row[1] or 0),
        "bhutan_amount": None if row[2] is None else float(row[2]),
        "indian_amount": None if row[3] is None else float(row[3]),
    }


def _resolve_hide_counts(bhutan_total, indian_total, view_date, override=None):
    """Manual override from Stats wins when set; else automatic ramp (today Thimphu only)."""
    ov = override if override is not None else _fetch_member_hide_override(view_date)
    if ov is not None and (ov["bhutan_count"] > 0 or ov["indian_count"] > 0):
        return (
            min(max(0, ov["bhutan_count"]), bhutan_total),
            min(max(0, ov["indian_count"]), indian_total),
        )
    return _ramped_hide_counts_today(bhutan_total, indian_total, view_date)


def _member_hide_sets(for_date):
    """Hidden vehicle ids for a date using DB override or automatic ramp (same as members / verify)."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, truck_type, daily_token, load_type, amount_collected, vehicle_number
        FROM vehicle_qr
        WHERE generated_date = %s
        ORDER BY truck_type, daily_token
        """,
        (for_date,),
    )
    detail_rows = cur.fetchall()
    conn.close()
    n_bh = sum(1 for r in detail_rows if r[1] == "Bhutanese")
    n_in = sum(1 for r in detail_rows if r[1] == "Indian")
    ov = _fetch_member_hide_override(for_date)
    hb, hi = _resolve_hide_counts(n_bh, n_in, for_date, ov)
    hidden_ids = _hidden_vehicle_ids_from_rows(detail_rows, hb, hi)
    return hidden_ids, detail_rows, ov


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

    # Simple daily counts for today's date, shown in Daily report tab (Bhutan calendar)
    today = _thimphu_today()
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
        stats_date = _thimphu_today()

    conn = get_db()
    cur = conn.cursor()

    # Full DB counts and amounts; row detail for hidden-vehicle line (Members rule, today Thimphu only)
    cur.execute(
        """
        SELECT id, truck_type, daily_token, load_type, amount_collected, vehicle_number
        FROM vehicle_qr
        WHERE generated_date = %s
        """,
        (stats_date,),
    )
    detail_rows = cur.fetchall()
    conn.close()

    bhutanese = 0
    indian_count = 0
    amt_bhutan = 0.0
    amt_indian = 0.0
    for _id, truck_type, _tok, _lt, amount_collected, *_rest in detail_rows:
        amt = float(amount_collected) if amount_collected is not None else 0.0
        if truck_type == "Bhutanese":
            bhutanese += 1
            amt_bhutan += amt
        elif truck_type == "Indian":
            indian_count += 1
            amt_indian += amt

    total = bhutanese + indian_count
    hide_ov = _fetch_member_hide_override(stats_date)
    hb, hi = _resolve_hide_counts(bhutanese, indian_count, stats_date, hide_ov)
    hid = _hidden_vehicle_ids_from_rows(detail_rows, hb, hi)
    hidden_count = len(hid)
    actual_bh_hid, actual_ih_hid = _amount_hidden_by_type(detail_rows, hid)
    hidden_amount = actual_bh_hid + actual_ih_hid

    # Full-day counts and Nu (Members page uses visible-only totals)
    stats_data = {
        "bhutanese": bhutanese,
        "indian": indian_count,
        "total": total,
        "amounts_bhutanese": {"total": amt_bhutan},
        "amounts_indian": {"total": amt_indian},
        "hidden_count": hidden_count,
        "hidden_amount": hidden_amount,
    }

    return render_template(
        "stats.html",
        stats=stats_data,
        stats_date=stats_date,
        hide_override=hide_ov,
    )


@app.route("/stats/member-hide", methods=["POST"])
def stats_member_hide():
    if not (session.get("stats_logged_in") or session.get("logged_in")):
        return redirect(url_for("login"))
    date_str = (request.form.get("date") or "").strip()
    try:
        for_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return redirect(url_for("stats"))

    conn = get_db()
    cur = conn.cursor()
    _ensure_member_hide_override_table(cur)

    if request.form.get("action") == "clear":
        cur.execute(
            "DELETE FROM member_hide_override WHERE for_date = %s",
            (for_date,),
        )
        conn.commit()
        conn.close()
        return redirect(url_for("stats", date=for_date.isoformat()))

    def _parse_nonneg_int(name):
        raw = (request.form.get(name) or "").strip()
        if not raw:
            return 0
        try:
            return max(0, int(raw))
        except ValueError:
            return 0

    def _parse_optional_amount(name):
        raw = (request.form.get(name) or "").strip()
        if not raw:
            return None
        try:
            return float(raw)
        except ValueError:
            return None

    bc = _parse_nonneg_int("bhutan_count")
    ic = _parse_nonneg_int("indian_count")
    ba = _parse_optional_amount("bhutan_amount")
    ia = _parse_optional_amount("indian_amount")

    if bc == 0 and ic == 0:
        cur.execute(
            "DELETE FROM member_hide_override WHERE for_date = %s",
            (for_date,),
        )
    else:
        cur.execute(
            """
            INSERT INTO member_hide_override (
                for_date, bhutan_count, indian_count, bhutan_amount, indian_amount
            )
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (for_date) DO UPDATE SET
                bhutan_count = EXCLUDED.bhutan_count,
                indian_count = EXCLUDED.indian_count,
                bhutan_amount = EXCLUDED.bhutan_amount,
                indian_amount = EXCLUDED.indian_amount
            """,
            (for_date, bc, ic, ba, ia),
        )
    conn.commit()
    conn.close()
    return redirect(url_for("stats", date=for_date.isoformat()))


# ======================
# BEA MEMBERS (per-day hide rules from Statistics)
# ======================
@app.route("/members", methods=["GET"])
def members():
    if not session.get("members_logged_in"):
        return redirect(url_for("login"))

    date_str = (request.args.get("date") or "").strip()
    members_date = None
    if date_str:
        try:
            members_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            members_date = None

    today_th = _thimphu_today()
    members_max_date = (today_th - timedelta(days=1)).isoformat()

    if members_date is None:
        return render_template(
            "members.html",
            members_date=None,
            show_data=False,
            members_max_date=members_max_date,
        )

    if members_date >= today_th:
        return render_template(
            "members.html",
            members_date=members_date,
            show_data=False,
            today_not_allowed=True,
            members_max_date=members_max_date,
        )

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
        SELECT id, truck_type, daily_token, load_type, amount_collected, vehicle_number
        FROM vehicle_qr
        WHERE generated_date = %s
        ORDER BY truck_type, daily_token
        """,
        (members_date,),
    )
    member_detail_rows = cur.fetchall()
    conn.close()

    hide_ov = _fetch_member_hide_override(members_date)
    bhutan_hide_n, indian_hide_n = _resolve_hide_counts(
        bhutanese, indian_actual, members_date, hide_ov
    )
    hidden_ids = _hidden_vehicle_ids_from_rows(
        member_detail_rows, bhutan_hide_n, indian_hide_n
    )
    bhutan_sub = sum(
        1
        for r in member_detail_rows
        if r[0] in hidden_ids and r[1] == "Bhutanese"
    )
    indian_sub = sum(
        1
        for r in member_detail_rows
        if r[0] in hidden_ids and r[1] == "Indian"
    )

    bhutan_display = max(0, bhutanese - bhutan_sub)
    indian_display = max(0, indian_actual - indian_sub)

    amt_bh_hid, amt_ih_hid = _amount_hidden_by_type(member_detail_rows, hidden_ids)
    amount_subtracted = amt_bh_hid + amt_ih_hid
    amount_bhutanese_display, amount_indian_display = _amounts_visible_nu(
        member_detail_rows, hidden_ids
    )
    amount_total_display = amount_bhutanese_display + amount_indian_display

    return render_template(
        "members.html",
        members_date=members_date,
        show_data=True,
        members_max_date=members_max_date,
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
    if not (session.get("stats_logged_in") or session.get("logged_in")):
        return redirect(url_for("login"))

    date_str = request.args.get("date")
    if not date_str:
        return redirect(url_for("stats"))
    d = datetime.strptime(date_str, "%Y-%m-%d").date()
    truck_type = request.args.get("truck_type")
    summary = request.args.get("summary")
    only_150 = request.args.get("only_150") or request.args.get("only_200")

    # Summary CSV: full database totals for the day (admin / stats parity)
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

    # CSV listing rows hidden from members / verify (override or automatic ramp)
    if only_150 == "1":
        hidden_ids, _, _ = _member_hide_sets(d)
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, truck_type, daily_token, load_type, amount_collected, vehicle_number, ticket_number
            FROM vehicle_qr
            WHERE generated_date = %s
            ORDER BY truck_type, daily_token
            """,
            (d,),
        )
        rows_all = cur.fetchall()
        conn.close()
        hidden = hidden_ids
        bhutan_out = sorted(
            [r for r in rows_all if r[0] in hidden and r[1] == "Bhutanese"],
            key=lambda r: r[2],
        )
        indian_out = sorted(
            [r for r in rows_all if r[0] in hidden and r[1] == "Indian"],
            key=lambda r: r[2],
        )
        rows_out = []
        for r in bhutan_out + indian_out:
            ticket = r[6] if len(r) > 6 and r[6] is not None else ""
            rows_out.append((r[2], r[5], r[1], r[3], r[4], ticket))

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            ["Token", "Vehicle", "Truck Type", "Load Type", "Amount", "Ticket Number"]
        )
        for r in rows_out:
            writer.writerow(r)

        return send_file(
            io.BytesIO(output.getvalue().encode()),
            mimetype="text/csv",
            as_attachment=True,
            download_name=f"stats_hidden_display_{d}.csv",
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

    cur.execute(
        """
        SELECT id, truck_type, daily_token, load_type, amount_collected, vehicle_number
        FROM vehicle_qr
        WHERE generated_date = %s
        ORDER BY truck_type, daily_token
        """,
        (d,),
    )
    detail_all = cur.fetchall()
    n_bh = sum(1 for r in detail_all if r[1] == "Bhutanese")
    n_in = sum(1 for r in detail_all if r[1] == "Indian")
    hide_ov = _fetch_member_hide_override(d)
    hide_bh, hide_ih = _resolve_hide_counts(n_bh, n_in, d, hide_ov)
    hidden_ids = _hidden_vehicle_ids_from_rows(detail_all, hide_bh, hide_ih)

    if bhutan and indian:
        cur.execute(
            """
            SELECT id, truck_type, daily_token, vehicle_number, load_type, amount_collected
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
            SELECT id, truck_type, daily_token, vehicle_number, load_type, amount_collected
            FROM vehicle_qr
            WHERE generated_date = %s AND truck_type = 'Bhutanese'
            ORDER BY daily_token
            """,
            (d,),
        )
    else:
        cur.execute(
            """
            SELECT id, truck_type, daily_token, vehicle_number, load_type, amount_collected
            FROM vehicle_qr
            WHERE generated_date = %s AND truck_type = 'Indian'
            ORDER BY daily_token
            """,
            (d,),
        )

    all_rows = cur.fetchall()
    conn.close()

    rows = []
    for rid, t_type, _tok, vehicle_number, load_type, amount_collected in all_rows:
        if rid in hidden_ids:
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