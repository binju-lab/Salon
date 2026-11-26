"""Customer-facing pages (Role C).

C-1 service catalogue, C-2 my appointments, C-3 booking form with a live
``fetch /api/slots``, C-4 the three write routes.

Only this module, ``templates/customer/*``, ``static/*`` and
``tests/test_customer.py`` are owned by Role C.  Nothing here edits the shared
baseline files, and no availability or transaction logic is duplicated here:
every write goes through ``booking.py``.
"""

from datetime import datetime, timedelta

from flask import Blueprint, abort, redirect, render_template, request, url_for
from flask_login import current_user

import booking
from auth import roles_required
from booking import BookingError, ValidationFailed
from models import Appointment, Service, StaffService, User, db
from money import price_from_minor
from responses import json_error, wants_json

customer = Blueprint("customer", __name__)

# Team decision D2: a cancellation must be at least 2 hours before the start.
CANCEL_WINDOW = timedelta(hours=2)

# Team decision D2: bookings are accepted between today and today + 60 days.
BOOKING_WINDOW_DAYS = 60


def _format_datetime(value):
    """Contract format: YYYY-MM-DDTHH:MM, minute precision, no timezone."""
    if value is None:
        return None
    return value.strftime("%Y-%m-%dT%H:%M")


def _format_time(value):
    return value.strftime("%H:%M") if value is not None else None


def _service_payload(service):
    return {
        "id": service.id,
        "name": service.name,
        "description": service.description,
        "price": price_from_minor(service.price_minor),
        "duration_minutes": service.duration_minutes,
        "required_workstation_type": service.required_workstation_type,
        "is_active": service.is_active,
    }


def _qualified_stylists(service_id):
    """Active stylists who are linked to this service through staff_service."""
    return (
        db.session.query(User)
        .join(StaffService, StaffService.stylist_id == User.id)
        .filter(
            StaffService.service_id == service_id,
            User.role == "stylist",
            User.is_active.is_(True),
        )
        .order_by(User.name)
        .all()
    )


def _appointment_payload(appointment, now):
    """One row for the customer list, with the two server-computed flags.

    Field names follow spec section 5.2 exactly, including the raw ids.
    """
    confirmed = appointment.status == "confirmed"
    return {
        "id": appointment.id,
        "customer_id": appointment.customer_id,
        "customer_name": appointment.customer.name,
        "stylist_id": appointment.stylist_id,
        "stylist_name": appointment.stylist.name,
        "service_id": appointment.service_id,
        "service_name": appointment.service.name,
        "workstation_id": appointment.workstation_id,
        "workstation_label": appointment.workstation.label,
        "starts_at": _format_datetime(appointment.starts_at),
        "ends_at": _format_datetime(appointment.ends_at),
        "price": price_from_minor(appointment.agreed_price_minor),
        "status": appointment.status,
        "arrived_at": _format_datetime(appointment.arrived_at),
        # Rescheduling only needs the booking to be in the future; cancelling
        # is stricter because a late cancellation loses the slot and the money.
        "can_cancel": confirmed and now < appointment.starts_at - CANCEL_WINDOW,
        "can_reschedule": confirmed and now < appointment.starts_at,
    }


@customer.get("/services")
def service_list():
    """C-1: public catalogue. Inactive services are never shown."""
    services = (
        db.session.query(Service)
        .filter(Service.is_active.is_(True))
        .order_by(Service.name)
        .all()
    )
    return render_template(
        "customer/services.html",
        services=[_service_payload(service) for service in services],
    )


@customer.get("/services/<int:service_id>")
def service_detail(service_id):
    """C-1: detail page plus the stylists who can actually perform it."""
    service = db.session.get(Service, service_id)
    if service is None or not service.is_active:
        # A withdrawn service is treated as not found rather than advertised.
        abort(404)
    return render_template(
        "customer/service_detail.html",
        service=_service_payload(service),
        stylists=_qualified_stylists(service.id),
    )


@customer.get("/my-appointments")
@roles_required("customer")
def my_appointments():
    """C-2: the signed-in customer's own bookings, newest first."""
    return (
        render_template(
            "customer/my-appointments.html",
            appointments=_appointments_payload(),
            booked=request.args.get("booked", type=int),
            error=None,
        ),
        200,
    )


def _require_bookable(service_id, stylist_id):
    """Reject anything the booking form could not honestly offer."""
    service = db.session.get(Service, service_id)
    if service is None or not service.is_active:
        abort(404)

    stylist = db.session.get(User, stylist_id)
    if stylist is None or stylist.role != "stylist" or not stylist.is_active:
        abort(404)

    if db.session.get(StaffService, (stylist_id, service_id)) is None:
        abort(404)

    return service, stylist


@customer.get("/book")
@roles_required("customer")
def book():
    """C-3: booking form. Slots arrive later from GET /api/slots over fetch.

    The form itself only renders; the slot list is filled by static/js/booking.js
    so the page keeps working while the availability query is slow.
    """
    service_id = request.args.get("service_id", type=int)
    stylist_id = request.args.get("stylist_id", type=int)
    if service_id is None or stylist_id is None:
        abort(400)

    service, stylist = _require_bookable(service_id, stylist_id)
    return _render_book(service, stylist)


# ---------------------------------------------------------------------------
# C-4: write routes
# ---------------------------------------------------------------------------

def _today():
    return datetime.now().date()


def _render_book(service, stylist, form_date=None, error=None):
    """One place for the booking page, used by both GET and a failed POST."""
    today = _today()
    return render_template(
        "customer/book.html",
        service=_service_payload(service),
        stylist={"id": stylist.id, "name": stylist.name},
        today=today.isoformat(),
        last_bookable_day=(today + timedelta(days=BOOKING_WINDOW_DAYS)).isoformat(),
        form_date=form_date or today.isoformat(),
        error=error,
    )


def _appointments_payload():
    now = datetime.now()
    rows = (
        db.session.query(Appointment)
        .filter(Appointment.customer_id == current_user.id)
        .order_by(Appointment.starts_at.desc())
        .all()
    )
    return [_appointment_payload(row, now) for row in rows]


def _render_appointments(error=None, status=200, booked=None):
    return (
        render_template(
            "customer/my-appointments.html",
            appointments=_appointments_payload(),
            booked=booked,
            error=error,
        ),
        status,
    )


def _error_message(exc):
    return getattr(exc, "message", None) or str(exc)


def _json_error(exc):
    extra = {}
    fields = getattr(exc, "fields", None)
    if fields:
        extra["fields"] = fields
    return json_error(exc.error_code, _error_message(exc), exc.http_status, **extra)


def _parse_date(value):
    try:
        return datetime.strptime((value or "").strip(), "%Y-%m-%d").date()
    except ValueError:
        raise ValidationFailed("date", "must be a YYYY-MM-DD date") from None


def _parse_time(value):
    try:
        return datetime.strptime((value or "").strip(), "%H:%M").time()
    except ValueError:
        raise ValidationFailed("start", "must be an HH:MM time") from None


@customer.post("/book")
@roles_required("customer")
def create_booking():
    """C-4: create one booking through booking.create_appointment."""
    service_id = request.form.get("service_id", type=int)
    stylist_id = request.form.get("stylist_id", type=int)
    if service_id is None or stylist_id is None:
        abort(400)

    service, stylist = _require_bookable(service_id, stylist_id)
    raw_date = request.form.get("date", "")

    try:
        day = _parse_date(raw_date)
        start = _parse_time(request.form.get("start"))
        appointment = booking.create_appointment(
            current_user.id, service.id, stylist.id, day, start
        )
    except BookingError as exc:
        if wants_json():
            return _json_error(exc)
        # Keep the customer's choices; the page reloads its own slot list.
        return _render_book(service, stylist, form_date=raw_date, error=_error_message(exc)), exc.http_status

    return redirect(url_for("customer.my_appointments", booked=appointment.id), code=303)


@customer.post("/appointments/<int:appointment_id>/cancel")
@roles_required("customer")
def cancel_appointment(appointment_id):
    """C-4: cancel through booking.cancel; ownership and window are checked there."""
    try:
        booking.cancel(appointment_id)
    except BookingError as exc:
        if wants_json():
            return _json_error(exc)
        return _render_appointments(error=_error_message(exc), status=exc.http_status)

    return redirect(url_for("customer.my_appointments"), code=303)


@customer.get("/appointments/<int:appointment_id>/reschedule")
@roles_required("customer")
def reschedule_form(appointment_id):
    """C-4: reschedule form. The slot list uses /api/slots in reschedule mode."""
    appointment = db.session.get(Appointment, appointment_id)
    if appointment is None:
        abort(404)
    if appointment.customer_id != current_user.id:
        abort(403)
    if appointment.status != "confirmed" or datetime.now() >= appointment.starts_at:
        return _render_appointments(
            error="That appointment can no longer be moved.", status=409
        )

    today = _today()
    return render_template(
        "customer/reschedule.html",
        appointment=_appointment_payload(appointment, datetime.now()),
        today=today.isoformat(),
        last_bookable_day=(today + timedelta(days=BOOKING_WINDOW_DAYS)).isoformat(),
        form_date=appointment.starts_at.strftime("%Y-%m-%d"),
        error=None,
    )


@customer.post("/appointments/<int:appointment_id>/reschedule")
@roles_required("customer")
def reschedule_submit(appointment_id):
    """C-4: move the appointment through booking.reschedule."""
    appointment = db.session.get(Appointment, appointment_id)
    if appointment is None:
        abort(404)
    if appointment.customer_id != current_user.id:
        abort(403)

    raw_date = request.form.get("date", "")
    try:
        day = _parse_date(raw_date)
        start = _parse_time(request.form.get("start"))
        booking.reschedule(appointment_id, day, start)
    except BookingError as exc:
        if wants_json():
            return _json_error(exc)
        if exc.error_code in {"INVALID_STATE", "CANCEL_WINDOW_CLOSED"}:
            # The booking itself is unusable now; send the customer back to the list.
            return _render_appointments(error=_error_message(exc), status=exc.http_status)
        today = _today()
        return (
            render_template(
                "customer/reschedule.html",
                appointment=_appointment_payload(appointment, datetime.now()),
                today=today.isoformat(),
                last_bookable_day=(today + timedelta(days=BOOKING_WINDOW_DAYS)).isoformat(),
                form_date=raw_date,
                error=_error_message(exc),
            ),
            exc.http_status,
        )

    return redirect(url_for("customer.my_appointments"), code=303)
