"""Role A: saving bookings (steps A-2 and A-3 of the spec).

Three functions change data: ``create_appointment``, ``reschedule`` and
``cancel``.  Each is one database transaction.  The final judge of a conflict
is the pair of unique constraints on ``slot_allocation``; a violation is turned
into ``SlotTaken`` after a rollback, so no half-saved booking can remain.
There is deliberately no automatic retry (it could silently pick another
workstation the customer never agreed to).

Views only call these functions and translate the exceptions.  Every exception
carries ``error_code`` and ``http_status`` so a view can answer with
``json_error(exc.error_code, str(exc), exc.http_status)``.
"""

from datetime import datetime, timedelta

from flask import abort, has_request_context
from flask_login import current_user
from sqlalchemy import delete, update
from sqlalchemy.exc import IntegrityError

import availability
from models import Appointment, Service, SlotAllocation, User, db


class BookingError(Exception):
    """Base class: ``error_code`` is one of the stable codes in spec section 7."""

    error_code = "SERVER_ERROR"
    http_status = 500


class SlotTaken(BookingError):
    """占用冲突，由唯一约束触发。视图层映射为 409 SLOT_TAKEN。"""

    error_code = "SLOT_TAKEN"
    http_status = 409


class InvalidState(BookingError):
    """状态或时间前置不满足。视图层映射为 409 INVALID_STATE。"""

    error_code = "INVALID_STATE"
    http_status = 409


class CancelWindowClosed(InvalidState):
    """Less than two hours before the start (decision D2): 409 CANCEL_WINDOW_CLOSED."""

    error_code = "CANCEL_WINDOW_CLOSED"


class ValidationFailed(BookingError):
    """Input rule broken: 400 VALIDATION_FAILED.  ``fields`` is ready for json_error."""

    error_code = "VALIDATION_FAILED"
    http_status = 400

    def __init__(self, field, message):
        super().__init__(message)
        self.field = field
        self.message = message
        self.fields = {field: message}


class DateOutOfRange(ValidationFailed):
    """More than 60 days ahead (decision D2): 400 DATE_OUT_OF_RANGE."""

    error_code = "DATE_OUT_OF_RANGE"


# ---------------------------------------------------------------------------
# Shared checks
# ---------------------------------------------------------------------------

def _check_start_input(day, start, now):
    """Alignment, 60-day window and not-in-the-past; return the start datetime."""
    if start.minute % 15 or start.second or start.microsecond:
        raise ValidationFailed("start", "must be on a 15-minute boundary")
    if day > now.date() + timedelta(days=availability.BOOKING_WINDOW_DAYS):
        raise DateOutOfRange("date", f"at most {availability.BOOKING_WINDOW_DAYS} days ahead")
    starts_at = datetime.combine(day, start)
    if starts_at <= now:
        raise ValidationFailed("start", "must be in the future")
    return starts_at


def _check_stylist_can_serve(stylist_id, service_id, starts_at, ends_at):
    """Skill, working shift and break/leave rules (spec 4.4, all 400)."""
    if not availability.stylist_has_skill(stylist_id, service_id):
        raise ValidationFailed("stylist_id", "this stylist does not offer the service")
    if not availability.shift_covers(stylist_id, starts_at, ends_at):
        raise ValidationFailed("start", "outside the stylist's working hours")
    if availability.unavailable_during(stylist_id, starts_at, ends_at):
        raise ValidationFailed("start", "the stylist is on a break or leave")


def _is_slot_conflict(error):
    # Only the two slot_allocation unique constraints mean "someone got there first".
    return "UNIQUE constraint failed: slot_allocation" in str(error.orig)


def _add_allocations(appointment_id, stylist_id, workstation_id, starts_at, minutes):
    for cell in availability.slot_starts(starts_at, minutes):
        db.session.add(SlotAllocation(
            appointment_id=appointment_id,
            stylist_id=stylist_id,
            workstation_id=workstation_id,
            slot_start=cell,
        ))


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

def create_appointment(customer_id, service_id, stylist_id, date, start):
    """创建 confirmed 预约并占用全部 15 分钟格。

    服务端计算 ends_at、agreed_price_minor、workstation_id。
    违反 §4.4 的任一输入规则抛 ValidationFailed；
    占用冲突抛 SlotTaken（事务已回滚，库内无残留）。
    """
    now = availability.current_time()

    customer = db.session.get(User, customer_id)
    if customer is None or customer.role != "customer" or not customer.is_active:
        abort(403)
    if has_request_context() and current_user.is_authenticated and current_user.id != customer_id:
        abort(403)
    service = db.session.get(Service, service_id)
    stylist = db.session.get(User, stylist_id)
    if (
        service is None or not service.is_active
        or stylist is None or stylist.role != "stylist" or not stylist.is_active
    ):
        abort(404)

    starts_at = _check_start_input(date, start, now)
    ends_at = starts_at + timedelta(minutes=service.duration_minutes)
    _check_stylist_can_serve(stylist.id, service.id, starts_at, ends_at)

    cells = availability.slot_starts(starts_at, service.duration_minutes)
    if not availability.compatible_workstation_ids(service.required_workstation_type):
        raise ValidationFailed("service_id", "no workstation of the required type is in use")
    workstation_id = availability.free_workstation(service.required_workstation_type, cells)
    if workstation_id is None:
        # Compatible stations exist but all are busy at this time.
        raise SlotTaken("That time has just been taken. Please choose another.")

    appointment = Appointment(
        customer_id=customer_id,
        stylist_id=stylist.id,
        service_id=service.id,
        workstation_id=workstation_id,
        starts_at=starts_at,
        ends_at=ends_at,
        agreed_price_minor=service.price_minor,
        status="confirmed",
    )
    try:
        db.session.add(appointment)
        db.session.flush()
        _add_allocations(appointment.id, stylist.id, workstation_id, starts_at, service.duration_minutes)
        db.session.commit()
    except IntegrityError as error:
        db.session.rollback()
        if _is_slot_conflict(error):
            raise SlotTaken("That time has just been taken. Please choose another.") from error
        raise
    except Exception:
        db.session.rollback()
        raise
    return appointment


# ---------------------------------------------------------------------------
# Reschedule
# ---------------------------------------------------------------------------

def reschedule(appointment_id, date, start):
    """在同一事务内替换全部占用并更新 starts_at/ends_at。

    保持原 agreed_price_minor 与原时长。
    失败时原预约与旧占用必须完好。
    """
    now = availability.current_time()
    # 404 -> 403 -> 409 (not confirmed, or already started)
    appointment = availability.reschedulable_appointment(appointment_id, now)

    old_start = appointment.starts_at
    minutes = int((appointment.ends_at - old_start).total_seconds() // 60)
    new_start = _check_start_input(date, start, now)
    if new_start == old_start:
        raise ValidationFailed("start", "is the same as the current time")
    new_end = new_start + timedelta(minutes=minutes)
    stylist_id = appointment.stylist_id
    _check_stylist_can_serve(stylist_id, appointment.service_id, new_start, new_end)

    # The booking's own old cells do not block it; it keeps its station if free.
    workstation_id = availability.free_workstation(
        appointment.service.required_workstation_type,
        availability.slot_starts(new_start, minutes),
        exclude_appointment_id=appointment.id,
        prefer=appointment.workstation_id,
    )
    if workstation_id is None:
        raise SlotTaken("That time has just been taken. Please choose another.")

    try:
        db.session.execute(delete(SlotAllocation).where(SlotAllocation.appointment_id == appointment_id))
        moved = db.session.execute(
            update(Appointment)
            .where(
                Appointment.id == appointment_id,
                Appointment.status == "confirmed",
                Appointment.starts_at == old_start,
            )
            .values(starts_at=new_start, ends_at=new_end, workstation_id=workstation_id)
        )
        if moved.rowcount != 1:
            # Someone cancelled or moved it between our read and our write.
            raise InvalidState("The appointment changed in the meantime.")
        _add_allocations(appointment_id, stylist_id, workstation_id, new_start, minutes)
        db.session.commit()
    except IntegrityError as error:
        db.session.rollback()
        if _is_slot_conflict(error):
            raise SlotTaken("That time has just been taken. Please choose another.") from error
        raise
    except Exception:
        db.session.rollback()
        raise
    return db.session.get(Appointment, appointment_id)


# ---------------------------------------------------------------------------
# Cancel
# ---------------------------------------------------------------------------

def cancel(appointment_id):
    """status = cancelled 并删除全部占用行，同事务。

    改期、取消都必须自己再校验归属、状态与时间前置。
    """
    now = availability.current_time()
    appointment = db.session.get(Appointment, appointment_id)
    if appointment is None:
        abort(404)
    availability.require_customer_owner(appointment)
    if appointment.status != "confirmed":
        raise InvalidState("Only a confirmed appointment can be cancelled.")
    if now >= appointment.starts_at - availability.CANCEL_WINDOW:
        raise CancelWindowClosed("Appointments cannot be cancelled within 2 hours of the start.")

    try:
        cancelled = db.session.execute(
            update(Appointment)
            .where(Appointment.id == appointment_id, Appointment.status == "confirmed")
            .values(status="cancelled")
        )
        if cancelled.rowcount != 1:
            raise InvalidState("Only a confirmed appointment can be cancelled.")
        db.session.execute(delete(SlotAllocation).where(SlotAllocation.appointment_id == appointment_id))
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
