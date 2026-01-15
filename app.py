from flask import Flask, render_template, request, redirect, session

app = Flask(__name__)
app.secret_key = "super-secret-key"  # required for session

@app.route("/", methods=["GET"])
def home():
    return render_template("login.html")

@app.route("/login", methods=["POST"])
def login():
    username = request.form.get("username")
    password = request.form.get("password")

    print("LOGIN ATTEMPT:", username, password)

    # TEMP login logic (replace later with DB)
    if username == "admin" and password == "admin":
        session["user"] = username
        return redirect("/admin")

    return redirect("/")

@app.route("/admin")
def admin():
    if "user" not in session:
        return redirect("/")
    return "Login Successful – Admin Panel"

if __name__ == "__main__":
    app.run(debug=True)