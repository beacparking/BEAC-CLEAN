from flask import Flask, render_template, request, redirect, url_for
import psycopg2
import psycopg2.extras
import qrcode
import os
from datetime import datetime, timedelta
from io import BytesIO
import base64

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "fallback-secret")

DATABASE_URL = os.environ.get("DATABASE_URL")

def get_db():
    return psycopg2.connect(DATABASE_URL, sslmode="require")

# ✅ ROOT ROUTE (FIXES YOUR ISSUE)
@app.route("/")
def home():
    return redirect(url_for("admin"))

@app.route("/admin", methods=["GET", "POST"])
def admin():
    qr_image = None
    seq_no = None

    if request.method == "POST":
        vehicle_number = request.form["vehicle"]
        generated_date = datetime.strptime(request.form["date"], "%Y-%m-%d").date()
        expires_date = generated_date + timedelta(days=2)

        conn = get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

        cur.execute("""
            INSERT INTO vehicle_qr (vehicle_number, generated_date, expires_date)
            VALUES (%s, %s, %s)
            RETURNING id
        """, (vehicle_number, generated_date, expires_date))

        record_id = cur.fetchone()[0]
        conn.commit()

        cur.execute("SELECT COUNT(*) FROM vehicle_qr")
        seq_no = cur.fetchone()[0]

        cur.close()
        conn.close()

        qr_url = url_for("verify", qr_id=record_id, _external=True)

        qr = qrcode.make(qr_url)
        buffer = BytesIO()
        qr.save(buffer, format="PNG")
        qr_image = base64.b64encode(buffer.getvalue()).decode()

    return render_template(
        "admin.html",
        qr_image=qr_image,
        seq_no=seq_no
    )

@app.route("/verify/<int:qr_id>")
def verify(qr_id):
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    cur.execute("SELECT * FROM vehicle_qr WHERE id = %s", (qr_id,))
    record = cur.fetchone()

    cur.close()
    conn.close()

    if not record:
        return "INVALID QR", 404

    today = datetime.utcnow().date()
    status = "VALID" if today <= record["expires_date"] else "EXPIRED"

    return render_template(
        "verify.html",
        status=status,
        vehicle_number=record["vehicle_number"],
        generated_date=record["generated_date"],
        expires_date=record["expires_date"]
    )

if __name__ == "__main__":
    app.run(debug=True)