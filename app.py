from flask import Flask, render_template, request
import qrcode
import os
from datetime import datetime

app = Flask(__name__)

QR_FOLDER = "static/qr"
os.makedirs(QR_FOLDER, exist_ok=True)

@app.route("/", methods=["GET", "POST"])
def index():
    qr_file = None
    error = None

    if request.method == "POST":
        try:
            vehicle_no = request.form.get("vehicle_no")
            expiry_date = request.form.get("expiry_date")

            if not vehicle_no or not expiry_date:
                error = "Vehicle number and expiry date are required"
            else:
                verify_url = request.url_root + f"verify/{vehicle_no}/{expiry_date}"

                qr = qrcode.make(verify_url)
                qr_file = f"{vehicle_no}.png"
                qr.save(os.path.join(QR_FOLDER, qr_file))

        except Exception as e:
            error = str(e)

    return render_template("index.html", qr_file=qr_file, error=error)


@app.route("/verify/<vehicle_no>/<expiry_date>")
def verify(vehicle_no, expiry_date):
    today = datetime.today().date()
    expiry = datetime.strptime(expiry_date, "%Y-%m-%d").date()

    status = "VALID" if expiry >= today else "EXPIRED"

    return render_template(
        "verify.html",
        vehicle_no=vehicle_no,
        expiry_date=expiry_date,
        status=status
    )


if __name__ == "__main__":
    app.run()