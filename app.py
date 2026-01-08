from flask import Flask, render_template, request
import qrcode
import os
from datetime import datetime, timedelta

app = Flask(__name__)

QR_FOLDER = "static/qr"
os.makedirs(QR_FOLDER, exist_ok=True)

# ---------------- HOME & QR GENERATION ----------------
@app.route("/", methods=["GET", "POST"])
def index():
    qr_file = None
    error = None

    if request.method == "POST":
        try:
            vehicle_no = request.form.get("vehicle_no").strip()

            if not vehicle_no:
                error = "Vehicle number is required"
            else:
                # QR points to verify page
                verify_url = request.url_root + f"verify/{vehicle_no}"

                qr = qrcode.make(verify_url)
                qr_file = f"{vehicle_no}.png"
                qr.save(os.path.join(QR_FOLDER, qr_file))

        except Exception as e:
            error = str(e)

    return render_template("index.html", qr_file=qr_file, error=error)


# ---------------- VERIFY VEHICLE ----------------
@app.route("/verify/<vehicle_no>")
def verify(vehicle_no):
    now = datetime.now()

    # Expiry = END OF TOMORROW (11:59:59 PM)
    expiry_datetime = datetime.combine(
        (now + timedelta(days=1)).date(),
        datetime.max.time()
    )

    status = "VALID" if now <= expiry_datetime else "EXPIRED"

    expiry_display = expiry_datetime.strftime("%d %b %Y, 11:59 PM")

    return render_template(
        "verify.html",
        vehicle_no=vehicle_no,
        expiry=expiry_display,
        status=status
    )


# ---------------- RUN ----------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)