from flask import Flask, render_template, request
import qrcode
import os
from datetime import datetime

app = Flask(__name__)

QR_FOLDER = "static/qr"
os.makedirs(QR_FOLDER, exist_ok=True)

@app.route("/", methods=["GET", "POST"])
def index():
    qr_image = None
    error = None

    if request.method == "POST":
        vehicle_no = request.form.get("vehicle_no")
        date = request.form.get("date")

        if not vehicle_no or not date:
            error = "All fields are required"
        else:
            filename = f"{vehicle_no}_{datetime.now().strftime('%Y%m%d%H%M%S')}.png"
            filepath = os.path.join(QR_FOLDER, filename)

            data = f"Vehicle Number: {vehicle_no}\nDate: {date}"
            img = qrcode.make(data)
            img.save(filepath)

            qr_image = filepath

    return render_template("index.html", qr_image=qr_image, error=error)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)