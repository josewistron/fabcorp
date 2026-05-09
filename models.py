from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from sqlalchemy import UniqueConstraint

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

class SlotRepair(db.Model):
    __tablename__ = 'slot_repairs'

    id = db.Column(db.Integer, primary_key=True)
    location = db.Column(db.String(50), nullable=False)
    error_code = db.Column(db.String(100), nullable=True)
    comment = db.Column(db.Text, nullable=False)
    # Si quieres relacionarlo formalmente con User, podrías usar un ForeignKey aquí
    technician_id = db.Column(db.String(50), nullable=True)
    repair_date = db.Column(db.DateTime, default=datetime.utcnow)

class PingFailure(db.Model):
    __tablename__ = 'ping_failures'

    id = db.Column(db.Integer, primary_key=True)
    model_name = db.Column(db.String(100), nullable=True)
    product_name = db.Column(db.String(100), nullable=True)
    serial_number = db.Column(db.String(50), nullable=True)
    location = db.Column(db.String(150), nullable=True)
    start_time = db.Column(db.DateTime, nullable=True)
    end_time = db.Column(db.DateTime, nullable=True)
    error_code = db.Column(db.String(50), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Definición de la restricción UNIQUE compuesta (serial_number, start_time)
    __table_args__ = (
        UniqueConstraint('serial_number', 'start_time', name='unique_serial_start'),
    )

class OpenFailIssue(db.Model):
    __tablename__ = "open_fail_issues"

    id_serial = db.Column(db.BigInteger, primary_key=True)

    employee_id = db.Column(db.Text, nullable=False)
    serial_number = db.Column(db.Text, nullable=False)
    stage = db.Column(db.Text, nullable=False)
    station = db.Column(db.Text, nullable=False)
    error_code = db.Column(db.Text, nullable=False)
    error_description = db.Column(db.Text, nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class FaeRepairQueue(db.Model):
    __tablename__ = "fae_repair_queue"

    id_queue = db.Column(db.BigInteger, primary_key=True)

    serial_number = db.Column(db.Text, nullable=False)
    employee_id = db.Column(db.Text, nullable=False)

    stage = db.Column(db.Text, nullable=True)
    station = db.Column(db.Text, nullable=True)
    error_code = db.Column(db.Text, nullable=True)
    error_desc = db.Column(db.Text, nullable=True)

    status = db.Column(db.Text, nullable=False, default="PENDING")

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    released_at = db.Column(db.DateTime, nullable=True)

    id_serial = db.Column(
        db.BigInteger,
        db.ForeignKey("open_fail_issues.id_serial"),
        nullable=True
    )

