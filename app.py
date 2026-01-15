from flask import Flask, render_template, request, redirect, url_for, session
import psycopg2
import psycopg2.extras
import os
import uuid
from datetime import datetime, timedelta
import qrcode

app = Flask(__name__)
app.secret_key = "bea_secure_qr_system"

# -------------------- DATABASE CONNECTION --------------------
def get_db():
    return psycopg2.connect(
        os.environ.get("DATABASE_URL"),
        sslmode="require"
    )

# -------------------- LOGIN --------------------
@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        # simple fixed login (as you already use)
        if username == "admin" and password == "admin123":
            session["admin"] = True
            return redirect(url_for("admin"))
        return render_template("login.html", error="Invalid credentials")

    return render_template("login.html")

# -------------------- LOGOUT --------------------
@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# -------------------- ADMIN PAGE --------------------
@app.route("/admin", methods=["GET", "POST"])
def admin():
    if not session.get("admin"):
        return redirect(url_for("login"))

    qr_image = None
    seq_no = None

    if request.method == "POST":
        vehicle_number = request.form.get("vehicle_number")
        selected_date = request.form.get("date")

        generated_at = datetime.strptime(selected_date, "%Y-%m-%d")
        expires_at = generated_at + timedelta(days=2)

        qr_id = str(uuid.uuid4())

        conn = get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

        cur.execute(
            """
            INSERT INTO vehicle_qr (id, vehicle_number, generated_at, expires_at)
            VALUES (%s, %s, %s, %s)
            RETURNING seq_no
            """,
            (qr_id, vehicle_number, generated_at, expires_at)
        )

        seq_no = cur.fetchone()["seq_no"]
        conn.commit()
        cur.close()
        conn.close()

        # QR CONTENT = only UUID (safe for redeploy)
        qr_data = f"{request.url_root}verify/{qr_id}"

        qr = qrcode.make(qr_data)
        qr_path = f"static/qr/{qr_id}.png"
        qr.save(qr_path)

        qr_image = qr_path

    return render_template(
        "admin.html",
        qr_image=qr_image,
        seq_no=seq_no
    )

# -------------------- VERIFY QR --------------------
@app.route("/verify/<qr_id>")
def verify(qr_id):
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    cur.execute(
        "SELECT * FROM vehicle_qr WHERE id = %s",
        (qr_id,)
    )

    record = cur.fetchone()
    cur.close()
    conn.close()

    if not record:
        return render_template(
            "verify.html",
            status="EXPIRED",
            vehicle_number="Unknown",
            expiry_date="N/A"
        )

    now = datetime.utcnow()
    expires_at = record["expires_at"]

    status = "VALID" if now <= expires_at else "EXPIRED"

    return render_template(
        "verify.html",
        status=status,
        vehicle_number=record["vehicle_number"],
        expiry_date=expires_at.strftime("%d-%m-%Y")
    )

# -------------------- RUN --------------------
if __name__ == "__main__":
    app.run(debug=False)