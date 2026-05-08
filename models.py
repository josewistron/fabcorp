from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

class User(db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)

    employee_number = db.Column(db.String(50), unique=True, nullable=False)
    full_name = db.Column(db.String(150), nullable=False)
    password_hash = db.Column(db.Text, nullable=False)

    start_date = db.Column(db.Date, nullable=False)

    # NEW FIELDS
    department = db.Column(db.String(100), nullable=False, default='MFTE')
    shift = db.Column(db.String(10), nullable=False, default='1')

    role = db.Column(db.String(50), nullable=False, default='tech')
    status = db.Column(db.String(20), nullable=False, default='active')

    failed_attempts = db.Column(db.Integer, nullable=False, default=0)
    locked_until = db.Column(db.DateTime, nullable=True)

    last_login = db.Column(db.DateTime, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)