"""Contract tests for field mapping, exact money conversion, and seed safety."""

from datetime import datetime, timedelta
from decimal import Decimal
import unittest

from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError

from app import create_app
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
from money import MAX_PRICE_MINOR, PriceValidationError, price_from_minor, price_to_minor


class MoneyContractTests(unittest.TestCase):
    def test_display_price_and_minor_units_round_trip_exactly(self):
        cases = (
            ("180.00", 18000), ("12.5", 1250), (" 0.01 ", 1), (Decimal("0"), 0),
            ("92233720368547758.07", MAX_PRICE_MINOR),
        )
        for display, minor in cases:
            with self.subTest(display=display):
                self.assertEqual(price_to_minor(display), minor)
                self.assertEqual(price_from_minor(minor), f"{minor // 100}.{minor % 100:02d}")
        self.assertEqual(price_to_minor(price_from_minor(18000)), 18000)

    def test_invalid_price_precision_sign_and_float_are_rejected(self):
        for value in (
            "1.234", "1.000", "-0.01", "NaN", "Infinity", "", None, 0.1, True,
            "92233720368547758.08", "1E+1000000",
        ):
            with self.subTest(value=value):
                with self.assertRaises(PriceValidationError):
                    price_to_minor(value)

    def test_minor_unit_formatter_requires_a_non_negative_integer(self):
        self.assertEqual(price_from_minor(0), "0.00")
        self.assertEqual(price_from_minor(1250), "12.50")
        for value in (-1, 1.0, True, "100", MAX_PRICE_MINOR + 1):
            with self.subTest(value=value):
                with self.assertRaises(PriceValidationError):
                    price_from_minor(value)


class DatabaseContractTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            "TESTING": True,
            "SECRET_KEY": "isolated-contract-test",
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        })
        self.context = self.app.app_context()
        self.context.push()
        self.addCleanup(self.context.pop)
        self.addCleanup(db.engine.dispose)
        self.addCleanup(db.session.remove)
        db.create_all()

    def _user(self, name, role):
        user = User(name=name, email=f"{name.lower()}@example.com", role=role)
        user.set_password("contract-test-only")
        db.session.add(user)
        return user

    def test_arrival_description_and_appointment_snapshot_are_persistent(self):
        customer = self._user("contract-customer", "customer")
        stylist = self._user("contract-stylist", "stylist")
        service = Service(
            name="Colour",
            description="A readable service description.",
            price_minor=18000,
            duration_minutes=60,
            required_workstation_type="colour",
        )
        workstation = Workstation(label="Contract colour station", workstation_type="colour")
        db.session.add_all([service, workstation])
        db.session.flush()
        arrived_at = datetime(2030, 1, 2, 10, 5)
        appointment = Appointment(
            customer=customer,
            stylist=stylist,
            service=service,
            workstation=workstation,
            starts_at=datetime(2030, 1, 2, 10),
            ends_at=datetime(2030, 1, 2, 11),
            agreed_price_minor=18000,
            status="completed",
            arrived_at=arrived_at,
        )
        db.session.add(appointment)
        db.session.commit()
        appointment_id = appointment.id
        db.session.expire_all()

        saved = db.session.get(Appointment, appointment_id)
        self.assertEqual(saved.arrived_at, arrived_at)
        self.assertEqual(saved.service.description, "A readable service description.")
        self.assertEqual(saved.ends_at, datetime(2030, 1, 2, 11))
        self.assertEqual(saved.agreed_price_minor, 18000)
        self.assertEqual(price_from_minor(saved.agreed_price_minor), "180.00")

    def test_staff_service_is_located_by_its_composite_key(self):
        stylist = self._user("skill-stylist", "stylist")
        service = Service(
            name="Cut",
            description="Cut description",
            price_minor=2500,
            duration_minutes=30,
            required_workstation_type="chair",
        )
        db.session.add(service)
        db.session.flush()
        db.session.add(StaffService(stylist_id=stylist.id, service_id=service.id))
        db.session.commit()

        key = (stylist.id, service.id)
        self.assertIsNotNone(db.session.get(StaffService, key))
        self.assertIsNone(db.session.get(StaffService, (stylist.id, service.id + 1)))
        self.assertEqual(
            [column.name for column in inspect(StaffService).primary_key],
            ["stylist_id", "service_id"],
        )

    def test_enum_check_constraints_reject_out_of_domain_values(self):
        stylist = self._user("enum-stylist", "stylist")
        db.session.flush()

        with self.assertRaises(IntegrityError):
            db.session.add(
                Service(
                    name="Invalid WS Service",
                    description="Invalid workstation type",
                    price_minor=1000,
                    duration_minutes=30,
                    required_workstation_type="colouring",
                )
            )
            db.session.flush()
        db.session.rollback()

        with self.assertRaises(IntegrityError):
            db.session.add(
                Workstation(label="Invalid Workstation", workstation_type="colouring")
            )
            db.session.flush()
        db.session.rollback()

        stylist = self._user("enum-stylist-valid", "stylist")
        db.session.flush()
        starts_at = datetime(2030, 1, 2, 12)
        with self.assertRaises(IntegrityError):
            db.session.add(
                Unavailability(
                    stylist_id=stylist.id,
                    starts_at=starts_at,
                    ends_at=starts_at + timedelta(hours=1),
                    reason="vacation",
                )
            )
            db.session.flush()
        db.session.rollback()

        stylist = self._user("enum-stylist-ok", "stylist")
        db.session.flush()
        db.session.add_all([
            Service(
                name="Valid Service",
                description="Valid workstation type",
                price_minor=1000,
                duration_minutes=30,
                required_workstation_type="chair",
            ),
            Workstation(label="Valid Colour", workstation_type="colour"),
            Unavailability(
                stylist_id=stylist.id,
                starts_at=starts_at,
                ends_at=starts_at + timedelta(hours=1),
                reason="break",
            ),
            Unavailability(
                stylist_id=stylist.id,
                starts_at=starts_at + timedelta(hours=2),
                ends_at=starts_at + timedelta(hours=3),
                reason="leave",
            ),
        ])
        db.session.commit()


class SeedPreservationTests(unittest.TestCase):
    def test_seed_rerun_preserves_passwords_appointments_and_all_related_rows(self):
        app = create_app({
            "TESTING": True,
            "SECRET_KEY": "isolated-seed-preservation-test",
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        })
        runner = app.test_cli_runner()
        first = runner.invoke(args=["seed"])
        self.assertEqual(first.exit_code, 0, first.output)
        models = (
            User, Service, StaffService, Workstation, WorkingShift,
            Unavailability, Appointment, SlotAllocation,
        )

        def snapshot():
            db.session.remove()
            result = {}
            for model in models:
                primary_key = list(model.__table__.primary_key.columns)
                rows = db.session.scalars(select(model).order_by(*primary_key)).all()
                result[model.__tablename__] = [
                    tuple(getattr(row, column.name) for column in model.__table__.columns)
                    for row in rows
                ]
            return result

        with app.app_context():
            before = snapshot()
            self.assertTrue(before["user"])
            self.assertTrue(before["appointment"])
            self.assertTrue(before["slot_allocation"])
        second = runner.invoke(args=["seed"])
        self.assertEqual(second.exit_code, 0, second.output)
        self.assertIn("Seed skipped", second.output)
        with app.app_context():
            self.assertEqual(snapshot(), before)
            self.assertTrue(all(row[3] for row in before["user"]))
            db.session.remove()
            db.engine.dispose()
