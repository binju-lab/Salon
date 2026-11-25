"""Role A: which times can be booked (steps A-1 and A-3 of the spec).

This module answers read-only questions.  Writing bookings is ``booking.py``.

* ``available_slots`` / ``available_slots_for_reschedule`` - spec section 13.
* ``blocking_appointments`` - the operational-change guard used by Role D.
* ``slots_api`` - the ``GET /api/slots`` route (spec section 4.2).  The route
  table gives it to Role A, but only Role B edits ``app.py``, so Role B must add
  ``from availability import slots_api`` and ``app.register_blueprint(slots_api)``.

The helpers below are shared with ``booking.py`` so that the page that lists
times and the code that saves a booking apply exactly the same rules.  The
listing is only a convenience; the two unique constraints on
``slot_allocation`` decide a real conflict (spec section 10).
"""

import re
from datetime import date as date_type
from datetime import datetime, time, timedelta

from flask import Blueprint, abort, has_request_context, jsonify, request
from flask_login import current_user

from auth import roles_required
from models import (
    Appointment,
    Service,
    SlotAllocation,
    StaffService,
    Unavailability,
    User,
    WorkingShift,
    Workstation,
    db,
)
from responses import json_error

SLOT = timedelta(minutes=15)
CANCEL_WINDOW = timedelta(hours=2)  # decision D2
BOOKING_WINDOW_DAYS = 60  # decision D2: today + 60 days is still allowed

slots_api = Blueprint("slots_api", __name__)


def current_time():
    """Server local time.  Tests patch this single function to fix the clock."""
    return datetime.now().replace(second=0, microsecond=0)


# ---------------------------------------------------------------------------
# Small pure helpers
# ---------------------------------------------------------------------------

def slot_starts(start, minutes):
    """The 15-minute grid cells covered by an appointment (60 min -> 4 cells)."""
    return [start + index * SLOT for index in range(minutes // 15)]


def _overlaps(first_start, first_end, second_start, second_end):
    """Half-open intervals: 10:00-11:00 and 11:00-12:00 only touch."""
    return first_start < second_end and second_start < first_end


def _ceil_to_grid(moment):
    """First 15-minute grid point that is not before ``moment``."""
    minutes = moment.hour * 60 + moment.minute + (1 if moment.second or moment.microsecond else 0)
    minutes = -(-minutes // 15) * 15
    return datetime.combine(moment.date(), time()) + timedelta(minutes=minutes)


def _booking():
    # booking.py imports this module, so import it lazily to avoid a cycle.
    import booking

    return booking


def require_customer_owner(appointment):
    """Re-check ownership inside the service layer (spec section 8.2, step 4).

    Calls made without an HTTP request (scripts, unit tests) have no identity
    to check, so only request-bound calls are restricted.
    """
    if not has_request_context():
        return
    user = current_user
    if not (user.is_authenticated and user.role == "customer" and user.id == appointment.customer_id):
        abort(403)


# ---------------------------------------------------------------------------
# Rule queries shared with booking.py
# ---------------------------------------------------------------------------

def stylist_has_skill(stylist_id, service_id):
    return db.session.get(StaffService, (stylist_id, service_id)) is not None


def shift_covers(stylist_id, start, end):
    """True when one working shift contains the whole interval."""
    shifts = db.session.scalars(
        db.select(WorkingShift).where(
            WorkingShift.stylist_id == stylist_id, WorkingShift.work_date == start.date()
        )
    ).all()
    return any(
        datetime.combine(start.date(), shift.start_time) <= start
        and end <= datetime.combine(start.date(), shift.end_time)
        for shift in shifts
    )


def unavailable_during(stylist_id, start, end):
    """True when a break or leave overlaps the interval."""
    return db.session.scalar(
        db.select(Unavailability.id)
        .where(
            Unavailability.stylist_id == stylist_id,
            Unavailability.starts_at < end,
            Unavailability.ends_at > start,
        )
        .limit(1)
    ) is not None


def compatible_workstation_ids(workstation_type):
    """Active workstations of the required type, lowest id first."""
    return db.session.scalars(
        db.select(Workstation.id)
        .where(Workstation.workstation_type == workstation_type, Workstation.is_active.is_(True))
        .order_by(Workstation.id)
    ).all()


def free_workstation(workstation_type, starts, exclude_appointment_id=None, prefer=None):
    """Pick an active workstation that is free for every cell, or ``None``.

    ``prefer`` is tried first (a reschedule keeps its station when possible);
    otherwise the lowest id wins so the choice is predictable.  The caller must
    not retry with another station after a conflict (spec section 10).
    """
    candidates = compatible_workstation_ids(workstation_type)
    if not candidates:
        return None
    query = db.select(SlotAllocation.workstation_id).where(
        SlotAllocation.workstation_id.in_(candidates), SlotAllocation.slot_start.in_(starts)
    )
    if exclude_appointment_id is not None:
        query = query.where(SlotAllocation.appointment_id != exclude_appointment_id)
    busy = set(db.session.scalars(query))
    ordered = ([prefer] if prefer in candidates else []) + [c for c in candidates if c != prefer]
    return next((station for station in ordered if station not in busy), None)


# ---------------------------------------------------------------------------
# Slot calculation
# ---------------------------------------------------------------------------

def _compute_slots(service, stylist_id, day, duration_minutes, now, exclude_appointment_id=None):
    """Return ``(times, empty_reason)`` for one stylist, one day, one duration."""
    if not stylist_has_skill(stylist_id, service.id):
        return [], "NOT_QUALIFIED"

    shifts = db.session.scalars(
        db.select(WorkingShift).where(
            WorkingShift.stylist_id == stylist_id, WorkingShift.work_date == day
        )
    ).all()
    if not shifts:
        return [], "NO_SHIFT"

    stations = compatible_workstation_ids(service.required_workstation_type)
    if not stations:
        return [], "NO_WORKSTATION"

    day_start = datetime.combine(day, time())
    day_end = day_start + timedelta(days=1)
    duration = timedelta(minutes=duration_minutes)

    breaks = db.session.execute(
        db.select(Unavailability.starts_at, Unavailability.ends_at).where(
            Unavailability.stylist_id == stylist_id,
            Unavailability.starts_at < day_end,
            Unavailability.ends_at > day_start,
        )
    ).all()

    def occupied(column, value):
        query = db.select(SlotAllocation.slot_start).where(
            column == value, SlotAllocation.slot_start >= day_start, SlotAllocation.slot_start < day_end
        )
        if exclude_appointment_id is not None:
            query = query.where(SlotAllocation.appointment_id != exclude_appointment_id)
        return set(db.session.scalars(query))

    stylist_busy = occupied(SlotAllocation.stylist_id, stylist_id)
    station_busy = {station: occupied(SlotAllocation.workstation_id, station) for station in stations}

    remaining = []  # passed everything except the workstation test
    chosen = []
    for shift in shifts:
        start = _ceil_to_grid(datetime.combine(day, shift.start_time))
        shift_end = datetime.combine(day, shift.end_time)
        while start + duration <= shift_end:
            end = start + duration
            cells = slot_starts(start, duration_minutes)
            if (
                start > now
                and not any(_overlaps(start, end, b_start, b_end) for b_start, b_end in breaks)
                and not stylist_busy.intersection(cells)
            ):
                remaining.append(start)
                if any(not station_busy[station].intersection(cells) for station in stations):
                    chosen.append(start)
            start += SLOT

    times = sorted({moment.time() for moment in chosen})
    if times:
        return times, None
    # Candidates ran out before the workstation test -> ALL_TAKEN;
    # candidates remained but every station was busy -> NO_WORKSTATION.
    return [], ("NO_WORKSTATION" if remaining else "ALL_TAKEN")


def _require_active_service(service_id):
    service = db.session.get(Service, service_id)
    if service is None or not service.is_active:
        abort(404)
    return service


def _require_active_stylist(stylist_id):
    stylist = db.session.get(User, stylist_id)
    if stylist is None or stylist.role != "stylist" or not stylist.is_active:
        abort(404)
    return stylist


def available_slots(service_id, stylist_id, date, now=None):
    """Return ``(ascending start times, empty_reason)`` for a new booking.

    ``empty_reason`` is ``None`` when the list is not empty.  ``now`` exists
    only so tests can inject the clock.
    """
    now = now or current_time()
    service = _require_active_service(service_id)
    _require_active_stylist(stylist_id)
    return _compute_slots(service, stylist_id, date, service.duration_minutes, now)


def reschedulable_appointment(appointment_id, now=None):
    """Load a booking the signed-in customer may still move, else raise.

    Order follows spec section 8.2: 404, then 403, then 409.
    """
    now = now or current_time()
    appointment = db.session.get(Appointment, appointment_id)
    if appointment is None:
        abort(404)
    require_customer_owner(appointment)
    if appointment.status != "confirmed" or now >= appointment.starts_at:
        raise _booking().InvalidState("Only a confirmed appointment that has not started can be moved.")
    return appointment


def available_slots_for_reschedule(appointment_id, date, now=None):
    """Slots for moving an existing booking.  Read-only.

    Service, stylist and length come from the booking itself (never from the
    request or the current service length), and the booking's own old cells
    do not block the new times.
    """
    now = now or current_time()
    appointment = reschedulable_appointment(appointment_id, now)
    minutes = int((appointment.ends_at - appointment.starts_at).total_seconds() // 60)
    return _compute_slots(
        appointment.service, appointment.stylist_id, date, minutes, now,
        exclude_appointment_id=appointment.id,
    )


# ---------------------------------------------------------------------------
# Operational-change protection (used by Role D before every admin write)
# ---------------------------------------------------------------------------

def blocking_appointments(*, service_id=None, workstation_id=None, stylist_id=None, interval=None):
    """IDs of future confirmed appointments that a change would invalidate.

    Selectors combine with OR.  ``stylist_id`` and ``interval`` only make sense
    together (the interval being removed from that stylist's availability).
    An empty list means the change may be saved.  Read-only.
    """
    if (stylist_id is None) != (interval is None):
        raise ValueError("stylist_id and interval must be given together")
    if service_id is None and workstation_id is None and stylist_id is None:
        raise ValueError("give at least one selector")

    conditions = []
    if service_id is not None:
        conditions.append(Appointment.service_id == service_id)
    if workstation_id is not None:
        conditions.append(Appointment.workstation_id == workstation_id)
    if stylist_id is not None:
        interval_start, interval_end = interval
        conditions.append(db.and_(
            Appointment.stylist_id == stylist_id,
            Appointment.starts_at < interval_end,
            Appointment.ends_at > interval_start,
        ))
    return list(db.session.scalars(
        db.select(Appointment.id)
        .where(
            Appointment.status == "confirmed",
            Appointment.starts_at > current_time(),
            db.or_(*conditions),
        )
        .order_by(Appointment.id)
    ))


# ---------------------------------------------------------------------------
# GET /api/slots
# ---------------------------------------------------------------------------

_ID = re.compile(r"[0-9]{1,18}")
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


def _bad_request(**fields):
    return json_error("VALIDATION_FAILED", "The request could not be validated.", 400, fields=fields)


@slots_api.get("/api/slots")
@roles_required("customer")
def api_slots():
    args = request.args
    reschedule_mode = "appointment_id" in args
    required = ["appointment_id", "date"] if reschedule_mode else ["service_id", "stylist_id", "date"]
    forbidden = ["service_id", "stylist_id"] if reschedule_mode else ["appointment_id"]

    errors = {name: "required" for name in required if name not in args}
    errors.update({name: "not allowed with this mode" for name in forbidden if name in args})
    for name in required:
        if name in args and name != "date" and not _ID.fullmatch(args[name]):
            errors[name] = "must be a positive integer"
    if "date" in args:
        try:
            if not _DATE.fullmatch(args["date"]):
                raise ValueError
            day = date_type.fromisoformat(args["date"])
        except ValueError:
            errors["date"] = "must be YYYY-MM-DD"
    if errors:
        return _bad_request(**errors)

    now = current_time()
    if day < now.date():
        return _bad_request(date="must not be in the past")
    if day > now.date() + timedelta(days=BOOKING_WINDOW_DAYS):
        return json_error(
            "DATE_OUT_OF_RANGE",
            f"The date must be within {BOOKING_WINDOW_DAYS} days from today.",
            400,
            fields={"date": f"at most {BOOKING_WINDOW_DAYS} days ahead"},
        )

    try:
        if reschedule_mode:
            appointment_id = int(args["appointment_id"])
            times, reason = available_slots_for_reschedule(appointment_id, day, now)
            appointment = db.session.get(Appointment, appointment_id)
            service_id, stylist_id = appointment.service_id, appointment.stylist_id
            minutes = int((appointment.ends_at - appointment.starts_at).total_seconds() // 60)
        else:
            appointment_id = None
            service_id, stylist_id = int(args["service_id"]), int(args["stylist_id"])
            times, reason = available_slots(service_id, stylist_id, day, now)
            minutes = db.session.get(Service, service_id).duration_minutes
    except _booking().InvalidState as error:
        return json_error(error.error_code, str(error), error.http_status)

    return jsonify({
        "date": day.isoformat(),
        "appointment_id": appointment_id,
        "service_id": service_id,
        "stylist_id": stylist_id,
        "duration_minutes": minutes,
        "slots": [moment.strftime("%H:%M") for moment in times],
        "empty_reason": reason if not times else None,
    })
