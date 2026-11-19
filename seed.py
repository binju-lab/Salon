import secrets
from datetime import date, datetime, time, timedelta

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


def register_seed_command(app):
    @app.cli.command("seed")
    def seed_command():
        """Create and populate an empty local demonstration database."""
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
            password = secrets.token_urlsafe(16)
            users = add_demo_data(password, date.today() + timedelta(days=1))
            accounts = [(user.email, user.role) for user in users]

        click.echo("Local demonstration accounts created:")
        for email, role in accounts:
            click.echo(f"  {email} ({role})")
        click.echo(f"Demo password (shown once): {password}")


def add_demo_data(password, work_date):
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

    for stylist in (stylist1, stylist2):
        db.session.add_all([
            StaffService(stylist=stylist, service=haircut),
            StaffService(stylist=stylist, service=colouring),
            WorkingShift(
                stylist=stylist, work_date=work_date, start_time=time(9), end_time=time(17)
            ),
        ])
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

    starts_at = datetime.combine(work_date, time(10))
    appointment = Appointment(
        customer=customer1,
        stylist=stylist1,
        service=colouring,
        workstation=colour_station,
        starts_at=starts_at,
        ends_at=starts_at + timedelta(minutes=colouring.duration_minutes),
        agreed_price_minor=colouring.price_minor,
        status="confirmed",
    )
    db.session.add(appointment)
    for offset in range(0, colouring.duration_minutes, 15):
        db.session.add(SlotAllocation(
            appointment=appointment,
            stylist=stylist1,
            workstation=colour_station,
            slot_start=starts_at + timedelta(minutes=offset),
        ))
    return users
