# BEAC Vehicle QR System

Web app for **Bhutan Exporters Association** (Phuentsholing) to manage parking/vehicle entry: generate QR codes for trucks, verify them at the gate, and view daily statistics.

## Features

- **Admin** (username: `admin`): Generate QR codes (vehicle, date, Bhutan/India truck type, load type, amount), export CSV by day/week/month.
- **Stats** (username: `beac`): View daily counts of Bhutanese vs Indian trucks.
- **Verify**: Scan QR → see VALID/EXPIRED, vehicle, truck type, load type, expiry.

## Tech

- **Backend:** Flask, PostgreSQL (psycopg2), qrcode, Pillow  
- **Frontend:** HTML templates + CSS

## Local setup

1. **PostgreSQL**  
   Create DB and table:
   ```bash
   createdb beac_db
   psql beac_db -c "
   CREATE TABLE vehicle_qr (
       id SERIAL PRIMARY KEY,
       vehicle_number TEXT NOT NULL,
       truck_type VARCHAR(20),
       load_type TEXT,
       amount_collected NUMERIC(10,2),
       generated_date DATE NOT NULL,
       expires_date DATE NOT NULL,
       daily_token INTEGER NOT NULL,
       UNIQUE (vehicle_number, generated_date)
   );
   "
   ```

2. **Run the app**
   ```bash
   python -m venv venv
   source venv/bin/activate   # Windows: venv\Scripts\activate
   pip install -r requirements.txt
   export DATABASE_URL="postgresql://localhost/beac_db"
   python app.py
   ```
   Open http://127.0.0.1:5001 and log in.

3. **QR works on phone (same WiFi)**  
   Set your machine’s IP so the QR link is reachable from the phone:
   ```bash
   export BASE_URL="http://YOUR_IP:5001"   # e.g. http://192.168.1.7:5001
   python app.py
   ```
   Then open admin at `http://YOUR_IP:5001/admin`, generate a new QR, and scan it.

## Deploy on Render

1. **New → PostgreSQL** on Render; copy the **Internal Database URL**.
2. **New → Web Service**; connect this GitHub repo.
   - Build: `pip install -r requirements.txt`
   - Start: `gunicorn app:app`
   - Env: `DATABASE_URL` = the Postgres URL.
3. In the Render Postgres **Connect** tab, run the `CREATE TABLE vehicle_qr (...)` SQL above (e.g. via psql).
4. Open your Render service URL; log in with `admin`/`admin123` or `beac`/`beac`.

QR codes will use the Render URL automatically (no `BASE_URL` needed).
