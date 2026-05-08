from models import db, User
from werkzeug.security import generate_password_hash
from datetime import datetime, date

def get_all_users():
    users = User.query.order_by(User.created_at.desc()).all()
    return users


def create_user(data):

    employee_number = data["employee_number"]

    user = User(
        employee_number=employee_number,
        full_name=data["full_name"],
        password_hash=generate_password_hash(employee_number),  # 🔥 password = username

        department=data["department"],
        shift=data["shift"],
        role=data["role"],

        start_date=date.today(),
        status="active"
    )

    db.session.add(user)
    db.session.commit()

    return user


def toggle_user_status(user_id):
    user = User.query.get(user_id)
    if not user:
        return None

    user.status = "inactive" if user.status == "active" else "active"
    db.session.commit()
    return user