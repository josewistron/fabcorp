from flask import Flask, render_template, request, jsonify, redirect, session, Response, send_file, flash
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, date
from werkzeug.security import check_password_hash
from sqlalchemy.orm import contains_eager
from rack_monitor import get_server_data

import io
from models import db, User
app = Flask(__name__)
app.secret_key = "super-secret-change-this"
app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://guillermo:mfte@10.121.161.225:5432/mfte_crm'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)

@app.route("/", methods=["GET", "POST"])
def admin_login():
    return render_template("login.html")
    
@app.route("/login", methods=["POST"])
def login():

    username = request.form.get("username")
    password = request.form.get("password")

    user = User.query.filter_by(employee_number=username).first()

    if not user:
        flash("User does not exist")
        return redirect("/")

    # check if inactive
    if user.status != "active":
        flash("User is inactive")
        return redirect("/")

    # check lock status
    if user.locked_until and user.locked_until > datetime.utcnow():
        flash("Account is temporarily locked")
        return redirect("/")

    # validate password
    if not check_password_hash(user.password_hash, password):
        user.failed_attempts += 1

        # lock account after too many attempts
        if user.failed_attempts >= 5:
            user.locked_until = datetime.utcnow()

        db.session.commit()

        flash("Incorrect password")
        return redirect("/")

    # LOGIN SUCCESS
    user.failed_attempts = 0
    user.locked_until = None
    user.last_login = datetime.utcnow()

    db.session.commit()

    session["user_id"] = user.id
    session["user_name"] = user.full_name

    flash(f"Welcome {user.full_name}")

    return redirect("/index")

def login_required(f):
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return redirect("/")
        return f(*args, **kwargs)
    wrapper.__name__ = f.__name__
    return wrapper

@app.route("/index")
@login_required
def index():
    if "user_id" not in session:
        return redirect("/")

    return render_template("index.html", name=session["user_name"])

@app.route("/logout")
def logout():
    session.clear()
    flash("Session closed")
    return redirect("/")

@app.route("/rack-monitor")
@login_required
def rack_monitor():

    data = get_server_data()

    bay_options = ["Bay 1", "Bay 2", "Bay 3"]
    rack_numbers = list(range(1, 11))

    return render_template(
    "rack_monitor.html",
    bay_options=bay_options,
    rack_numbers=rack_numbers,
    rack_data=data["data"],
    config_counts=data["configs"],
    summary_data=data.get("summary", []),
    bay_view=data.get("bay_view", {})
)

@app.route("/api/rack-debug")
@login_required
def rack_debug():

    data = get_server_data()

    return jsonify(data)
# RUN SERVER
# =========================
if __name__ == "__main__":

    with app.app_context():
        db.create_all()

    app.run(host="0.0.0.0", debug=True, port=4321)