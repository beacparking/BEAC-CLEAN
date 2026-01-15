from flask import Flask, render_template, request, redirect, url_for, session
from functools import wraps

app = Flask(__name__)
app.secret_key = "super-secret-key"

# ---------------- LOGIN REQUIRED DECORATOR ----------------
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function


# ---------------- LOGIN PAGE ----------------
@app.route("/", methods=["GET"])
def root():
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        # 🔐 SIMPLE AUTH (change later if needed)
        if username == "admin" and password == "admin123":
            session["logged_in"] = True
            session["username"] = username
            return redirect(url_for("admin"))

        return render_template("login.html", error="Invalid credentials")

    return render_template("login.html")


# ---------------- ADMIN DASHBOARD ----------------
@app.route("/admin")
@login_required
def admin():
    return render_template("admin.html")


# ---------------- LOGOUT ----------------
@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


if __name__ == "__main__":
    app.run(debug=True)