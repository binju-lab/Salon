import os
from datetime import datetime, time, timedelta

import click

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

DEFAULT_DEMO_PASSWORD = "SalonDemo123!"
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128


def resolve_demo_password():
    """Return SEED_PASSWORD when set, otherwise the shared local demo default."""
    env_password = os.environ.get("SEED_PASSWORD")
    if env_password is None or env_password == "":
        return DEFAULT_DEMO_PASSWORD
    if not env_password.strip() or not (
        MIN_PASSWORD_LENGTH <= len(env_password) <= MAX_PASSWORD_LENGTH
    ):
        raise click.ClickException(
            f"SEED_PASSWORD must be {MIN_PASSWORD_LENGTH}-{MAX_PASSWORD_LENGTH} non-blank characters."
        )
    return env_password


def register_seed_command(app):
    @app.cli.command("seed")
    def seed_command():
        """Create and populate an empty local demonstration database."""
        password = resolve_demo_password()
        tables = (
            User,
            Service,
            StaffService,
            Workstation,
            WorkingShift,
            Unavailability,
            Appointment,
            SlotAllocation,
        )
        with db.session.begin():
            # Lock before creating or checking tables so only one run can seed an empty DB.
            connection = db.session.connection()
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            db.metadata.create_all(connection)
            if any(db.session.scalar(db.select(model).limit(1)) for model in tables):
                click.echo("Database already contains data. Seed skipped.")
                return
            now = datetime.now().replace(second=0, microsecond=0)
            users = add_demo_data(password, now.date() + timedelta(days=1), now=now)
            accounts = [(user.email, user.role) for user in users]

        click.echo("Local demonstration accounts created:")
        for email, role in accounts:
            click.echo(f"  {email} ({role})")
        click.echo(f"Demo password: {password}")


def _next_grid_after(moment):
    """Return the first 15-minute boundary strictly after ``moment``."""
    minutes = moment.hour * 60 + moment.minute
    next_minutes = ((minutes // 15) + 1) * 15
    return datetime.combine(moment.date(), time()) + timedelta(minutes=next_minutes)


def _soon_appointment_start(now):
    """Pick a 15-minute-aligned future start within the 2-hour cancel window."""
    next_grid = _next_grid_after(now)
    candidate = next_grid + timedelta(minutes=45)
    latest_today_start = datetime.combine(now.date(), time(23, 15))
    if candidate <= latest_today_start:
        return candidate
    if next_grid <= latest_today_start and latest_today_start - now >= timedelta(minutes=15):
        return latest_today_start
    return candidate


def _add_appointment_with_slots(customer, stylist, service, workstation, starts_at):
    appointment = Appointment(
        customer=customer,
        stylist=stylist,
        service=service,
        workstation=workstation,
        starts_at=starts_at,
        ends_at=starts_at + timedelta(minutes=service.duration_minutes),
        agreed_price_minor=service.price_minor,
        status="confirmed",
    )
    db.session.add(appointment)
    for offset in range(0, service.duration_minutes, 15):
        db.session.add(SlotAllocation(
            appointment=appointment,
            stylist=stylist,
            workstation=workstation,
            slot_start=starts_at + timedelta(minutes=offset),
        ))
    return appointment


def add_demo_data(password, work_date, now=None):
    now = (now or datetime.now()).replace(second=0, microsecond=0)
    today = now.date()

    admin = User(name="Demo Admin", email="admin@example.com", role="admin")
    stylist1 = User(name="Demo Stylist 1", email="stylist1@example.com", role="stylist")
    stylist2 = User(name="Demo Stylist 2", email="stylist2@example.com", role="stylist")
    customer1 = User(name="Demo Customer 1", email="customer1@example.com", role="customer")
    customer2 = User(name="Demo Customer 2", email="customer2@example.com", role="customer")
    users = (admin, stylist1, stylist2, customer1, customer2)
    for user in users:
        user.set_password(password)
    db.session.add_all(users)

    haircut = Service(
        name="Haircut",
        description="Standard cut and styling.",
        price_minor=2500,
        duration_minutes=30,
        required_workstation_type="chair",
    )
    colouring = Service(
        name="Colouring",
        description="Single-process colour treatment.",
        price_minor=6000,
        duration_minutes=60,
        required_workstation_type="colour",
    )
    chair = Workstation(label="Chair 1", workstation_type="chair")
    colour_station = Workstation(label="Colour Station 1", workstation_type="colour")
    db.session.add_all([haircut, colouring, chair, colour_station])

    soon_start = _soon_appointment_start(now)
    soon_end = soon_start + timedelta(minutes=haircut.duration_minutes)

    if soon_start.date() == today:
        today_shift_start = min(time(9), soon_start.time())
        padded_end = min(
            soon_end + timedelta(hours=2),
            datetime.combine(today, time(23, 45)),
        )
        today_shift_end = max(time(17), padded_end.time())
        next_day_shift_start = time(9)
    else:
        today_shift_start = time(9)
        today_shift_end = time(23, 45)
        next_day_shift_start = min(time(9), soon_start.time())

    for stylist in (stylist1, stylist2):
        records = [
            StaffService(stylist=stylist, service=haircut),
            StaffService(stylist=stylist, service=colouring),
            WorkingShift(
                stylist=stylist,
                work_date=today,
                start_time=today_shift_start,
                end_time=today_shift_end,
            ),
        ]
        if work_date != today:
            records.append(WorkingShift(
                stylist=stylist,
                work_date=work_date,
                start_time=next_day_shift_start,
                end_time=time(17),
            ))
        db.session.add_all(records)

    db.session.add_all([
        Unavailability(
            stylist=stylist1,
            starts_at=datetime.combine(work_date, time(12)),
            ends_at=datetime.combine(work_date, time(13)),
            reason="break",
        ),
        Unavailability(
            stylist=stylist2,
            starts_at=datetime.combine(work_date, time(15)),
            ends_at=datetime.combine(work_date, time(17)),
            reason="leave",
        ),
    ])

    # Within 2 hours of now: demonstrates CANCEL_WINDOW_CLOSED (reschedule still allowed).
    _add_appointment_with_slots(customer1, stylist2, haircut, chair, soon_start)
    # Tomorrow 10:00 (>2 hours ahead): demonstrates normal cancellation and rescheduling.
    _add_appointment_with_slots(
        customer1, stylist1, colouring, colour_station, datetime.combine(work_date, time(10))
    )
    return users
