from flask import Flask, render_template, request, redirect, session, send_file
import sqlite3
import qrcode
import io
import base64
from datetime import datetime, date
import csv

app = Flask(__name__)
app.secret_key = "beac-secret-key"

DB = "vehicles.db"

# ---------------- DATABASE ----------------
def get_db():
    return sqlite3.connect(DB, check_same_thread=False)

def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS vehicles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vehicle TEXT NOT NULL,
            expiry TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

init_db()

# ---------------- LOGIN ----------------
@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form["username"] == "admin" and request.form["password"] == "admin123":
            session["admin"] = True
            return redirect("/admin")
    return render_template("login.html")

# ---------------- LOGOUT ----------------
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

# ---------------- ADMIN ----------------
@app.route("/admin", methods=["GET", "POST"])
def admin():
    if not session.get("admin"):
        return redirect("/")

    qr_base64 = None
    token = None
    message = None

    if request.method == "POST":
        vehicle = request.form.get("vehicle")
        expiry = request.form.get("expiry")

        if not vehicle or not expiry:
            message = "Vehicle and expiry required"
        else:
            conn = get_db()
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO vehicles (vehicle, expiry, created_at) VALUES (?, ?, ?)",
                (vehicle, expiry, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            )
            token = cur.lastrowid
            conn.commit()
            conn.close()

            verify_url = f"https://beac-vehicle-qr-clean.onrender.com/verify/{token}"

            qr = qrcode.make(verify_url)
            buffer = io.BytesIO()
            qr.save(buffer, format="PNG")
            buffer.seek(0)
            qr_base64 = base64.b64encode(buffer.getvalue()).decode()

            message = "QR generated successfully"

    return render_template(
        "admin.html",
        qr_base64=qr_base64,
        token=token,
        message=message
    )

# ---------------- VERIFY ----------------
@app.route("/verify/<int:token>")
def verify(token):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT vehicle, expiry, created_at FROM vehicles WHERE id=?",
        (token,)
    )
    row = cur.fetchone()
    conn.close()

    if not row:
        return "INVALID QR"

    vehicle, expiry, created_at = row
    expiry_date = datetime.strptime(expiry, "%Y-%m-%d").date()
    status = "VALID" if expiry_date >= date.today() else "EXPIRED"

    return render_template(
        "verify.html",
        vehicle=vehicle,
        expiry=expiry,
        status=status,
        created_at=created_at
    )

# ---------------- EXPORT LOGS ----------------
@app.route("/export")
def export_logs():
    if not session.get("admin"):
        return redirect("/")

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, vehicle, expiry, created_at FROM vehicles ORDER BY id DESC")
    rows = cur.fetchall()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Vehicle", "Expiry", "Created At"])
    for r in rows:
        writer.writerow(r)

    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode()),
        mimetype="text/csv",
        as_attachment=True,
        download_name="vehicle_logs.csv"
    )

# ---------------- RUN ----------------
if __name__ == "__main__":
    app.run(debug=True)