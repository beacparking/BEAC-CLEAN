from flask import Flask, render_template, request, redirect, url_for, session
import psycopg2
import psycopg2.extras
import os
import uuid
import qrcode
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev_secret")

DATABASE_URL = os.environ.get("DATABASE_URL")

def get_db():
    return psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)

# ------------------------
# LOGIN
# ------------------------
@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        if (
            username == os.environ.get("ADMIN_USERNAME")
            and password == os.environ.get("ADMIN_PASSWORD")
        ):
            session["admin"] = True
            return redirect(url_for("admin"))

        return render_template("login.html", error="Invalid credentials")

    return render_template("login.html")

# ------------------------
# ADMIN DASHBOARD
# ------------------------
@app.route("/admin", methods=["GET"])
def admin():
    if not session.get("admin"):
        return redirect(url_for("login"))

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM vehicle_qr")
    count = cur.fetchone()["count"]
    cur.close()
    conn.close()

    return render_template("admin.html", count=count)

# ------------------------
# GENERATE QR (POST ONLY)
# ------------------------
@app.route("/generate", methods=["POST"])
def generate_qr():
    if not session.get("admin"):
        return redirect(url_for("login"))

    vehicle_number = request.form.get("vehicle_number")
    selected_date = request.form.get("date")

    generated_at = datetime.strptime(selected_date, "%Y-%m-%d")
    expires_at = generated_at + timedelta(days=2)

    qr_id = str(uuid.uuid4())

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO vehicle_qr (id, vehicle_number, generated_at, expires_at)
        VALUES (%s, %s, %s, %s)
        RETURNING seq_no
        """,
        (qr_id, vehicle_number, generated_at, expires_at),
    )
    seq_no = cur.fetchone()["seq_no"]
    conn.commit()
    cur.close()
    conn.close()

    qr_url = url_for("verify", qr_id=qr_id, _external=True)

    img = qrcode.make(qr_url)
    qr_path = f"static/qr/{qr_id}.png"
    img.save(qr_path)

    return render_template(
        "admin.html",
        qr_image=qr_path,
        vehicle_number=vehicle_number,
        seq_no=seq_no,
    )

# ------------------------
# VERIFY QR
# ------------------------
@app.route("/verify/<qr_id>")
def verify(qr_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM vehicle_qr WHERE id = %s", (qr_id,))
    record = cur.fetchone()
    cur.close()
    conn.close()

    if not record:
        return render_template("verify.html", status="INVALID", vehicle_number="")

    now = datetime.utcnow()
    status = "VALID" if now <= record["expires_at"] else "EXPIRED"

    return render_template(
        "verify.html",
        status=status,
        vehicle_number=record["vehicle_number"],
    )

# ------------------------
# LOGOUT
# ------------------------
@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

if __name__ == "__main__":
    app.run(debug=True)