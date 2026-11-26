"""Customer-facing pages (Role C).

Covers C-1 (public service catalogue) and C-2 (my appointments).  Both steps
depend only on the B-0 baseline, so they do not wait for Role A.

C-3 (the booking page with ``fetch /api/slots``) and C-4 (the three write
routes) are added later, once Role A exposes its six functions.

Only this module, ``templates/customer/*``, ``static/*`` and
``tests/test_customer.py`` are owned by Role C.  Nothing here edits the shared
baseline files.
"""

from datetime import datetime, timedelta

from flask import Blueprint, abort, render_template, request
from flask_login import current_user

from auth import roles_required
from models import Appointment, Service, StaffService, User, db
from money import price_from_minor

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
    """One row for the customer list, with the two server-computed flags."""
    confirmed = appointment.status == "confirmed"
    return {
        "id": appointment.id,
        "service_name": appointment.service.name,
        "stylist_name": appointment.stylist.name,
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
    now = datetime.now()
    appointments = (
        db.session.query(Appointment)
        .filter(Appointment.customer_id == current_user.id)
        .order_by(Appointment.starts_at.desc())
        .all()
    )
    return render_template(
        "customer/my-appointments.html",
        appointments=[_appointment_payload(row, now) for row in appointments],
        booked=request.args.get("booked", type=int),
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

    today = datetime.now().date()
    last_bookable_day = today + timedelta(days=BOOKING_WINDOW_DAYS)
    return render_template(
        "customer/book.html",
        service=_service_payload(service),
        stylist={"id": stylist.id, "name": stylist.name},
        today=today.isoformat(),
        last_bookable_day=last_bookable_day.isoformat(),
    )
