import sqlite3

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import event
from sqlalchemy.engine import Engine
from werkzeug.security import check_password_hash, generate_password_hash


db = SQLAlchemy()


@event.listens_for(Engine, "connect")
def enable_sqlite_foreign_keys(connection, _record):
    if isinstance(connection, sqlite3.Connection):
        connection.execute("PRAGMA foreign_keys = ON").close()


class User(UserMixin, db.Model):
    __tablename__ = "user"
    __table_args__ = (
        db.CheckConstraint("role IN ('customer', 'stylist', 'admin')", name="ck_user_role"),
    )

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(254, collation="NOCASE"), nullable=False, unique=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(16), nullable=False, default="customer")
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Service(db.Model):
    __tablename__ = "service"
    __table_args__ = (
        db.CheckConstraint("price_minor >= 0", name="ck_service_price"),
        db.CheckConstraint(
            "duration_minutes > 0 AND duration_minutes % 15 = 0",
            name="ck_service_duration",
        ),
        db.CheckConstraint(
            "required_workstation_type IN ('chair','colour')",
            name="ck_service_ws_type",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=False)
    price_minor = db.Column(db.Integer, nullable=False)
    duration_minutes = db.Column(db.Integer, nullable=False)
    required_workstation_type = db.Column(db.String(40), nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)


class StaffService(db.Model):
    __tablename__ = "staff_service"

    stylist_id = db.Column(db.ForeignKey("user.id"), primary_key=True)
    service_id = db.Column(db.ForeignKey("service.id"), primary_key=True)

    stylist = db.relationship(User)
    service = db.relationship(Service)


class Workstation(db.Model):
    __tablename__ = "workstation"
    __table_args__ = (
        db.CheckConstraint("workstation_type IN ('chair','colour')", name="ck_workstation_type"),
    )

    id = db.Column(db.Integer, primary_key=True)
    label = db.Column(db.String(80), nullable=False)
    workstation_type = db.Column(db.String(40), nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)


class WorkingShift(db.Model):
    __tablename__ = "working_shift"
    __table_args__ = (
        db.CheckConstraint("end_time > start_time", name="ck_working_shift_interval"),
    )

    id = db.Column(db.Integer, primary_key=True)
    stylist_id = db.Column(db.ForeignKey("user.id"), nullable=False)
    work_date = db.Column(db.Date, nullable=False)
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)

    stylist = db.relationship(User)


class Unavailability(db.Model):
    __tablename__ = "unavailability"
    __table_args__ = (
        db.CheckConstraint("ends_at > starts_at", name="ck_unavailability_interval"),
        db.CheckConstraint("reason IN ('break','leave')", name="ck_unavailability_reason"),
    )

    id = db.Column(db.Integer, primary_key=True)
    stylist_id = db.Column(db.ForeignKey("user.id"), nullable=False)
    starts_at = db.Column(db.DateTime, nullable=False)
    ends_at = db.Column(db.DateTime, nullable=False)
    reason = db.Column(db.String(100), nullable=False)

    stylist = db.relationship(User)


class Appointment(db.Model):
    __tablename__ = "appointment"
    __table_args__ = (
        db.CheckConstraint("ends_at > starts_at", name="ck_appointment_interval"),
        db.CheckConstraint("agreed_price_minor >= 0", name="ck_appointment_price"),
        db.CheckConstraint(
            "status IN ('confirmed', 'cancelled', 'completed', 'no_show')",
            name="ck_appointment_status",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.ForeignKey("user.id"), nullable=False)
    stylist_id = db.Column(db.ForeignKey("user.id"), nullable=False)
    service_id = db.Column(db.ForeignKey("service.id"), nullable=False)
    workstation_id = db.Column(db.ForeignKey("workstation.id"), nullable=False)
    starts_at = db.Column(db.DateTime, nullable=False)
    ends_at = db.Column(db.DateTime, nullable=False)
    agreed_price_minor = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(16), nullable=False, default="confirmed")
    arrived_at = db.Column(db.DateTime)

    customer = db.relationship(User, foreign_keys=[customer_id])
    stylist = db.relationship(User, foreign_keys=[stylist_id])
    service = db.relationship(Service)
    workstation = db.relationship(Workstation)
    slot_allocations = db.relationship(
        "SlotAllocation", back_populates="appointment", passive_deletes="all"
    )


class SlotAllocation(db.Model):
    __tablename__ = "slot_allocation"
    __table_args__ = (
        db.UniqueConstraint("stylist_id", "slot_start", name="uq_slot_stylist_start"),
        db.UniqueConstraint("workstation_id", "slot_start", name="uq_slot_workstation_start"),
    )

    id = db.Column(db.Integer, primary_key=True)
    appointment_id = db.Column(db.ForeignKey("appointment.id"), nullable=False)
    stylist_id = db.Column(db.ForeignKey("user.id"), nullable=False)
    workstation_id = db.Column(db.ForeignKey("workstation.id"), nullable=False)
    slot_start = db.Column(db.DateTime, nullable=False)

    appointment = db.relationship(Appointment, back_populates="slot_allocations")
    stylist = db.relationship(User)
    workstation = db.relationship(Workstation)
