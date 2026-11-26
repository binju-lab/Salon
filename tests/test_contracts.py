"""Contract tests for field mapping, exact money conversion, and seed safety."""

from datetime import datetime, timedelta
from decimal import Decimal
from html.parser import HTMLParser
import os
import unittest
from unittest import mock

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
from seed import DEFAULT_DEMO_PASSWORD, add_demo_data


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


class _CsrfTokenParser(HTMLParser):
    token = None

    def handle_starttag(self, tag, attrs):
        if tag == "input":
            fields = dict(attrs)
            if fields.get("name") == "csrf_token":
                self.token = fields.get("value")


class SeedPreservationTests(unittest.TestCase):
    def _make_isolated_app(self, secret_key):
        return create_app({
            "TESTING": True,
            "SECRET_KEY": secret_key,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        })

    def _dispose_app(self, app):
        with app.app_context():
            db.session.remove()
            db.engine.dispose()

    def _login_as(self, app, email, password):
        client = app.test_client()
        page = client.get("/auth/login")
        self.assertEqual(page.status_code, 200)
        parser = _CsrfTokenParser()
        parser.feed(page.get_data(as_text=True))
        self.assertTrue(parser.token, "Missing CSRF token on /auth/login")
        response = client.post(
            "/auth/login",
            data={"csrf_token": parser.token, "email": email, "password": password},
        )
        return client, response

    def test_seed_rerun_preserves_passwords_appointments_and_all_related_rows(self):
        app = self._make_isolated_app("isolated-seed-preservation-test")
        try:
            runner = app.test_cli_runner()
            with mock.patch.dict(os.environ, {"SEED_PASSWORD": ""}, clear=False):
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
            with mock.patch.dict(os.environ, {"SEED_PASSWORD": "DifferentPass99!"}, clear=False):
                second = runner.invoke(args=["seed"])
            self.assertEqual(second.exit_code, 0, second.output)
            self.assertIn("Seed skipped", second.output)
            with app.app_context():
                self.assertEqual(snapshot(), before)
                self.assertTrue(all(row[3] for row in before["user"]))
        finally:
            self._dispose_app(app)

    def test_seed_uses_fixed_default_password_and_allows_real_login(self):
        for env_override in (None, ""):
            with self.subTest(seed_password=env_override):
                app = self._make_isolated_app("isolated-seed-default-password-test")
                try:
                    runner = app.test_cli_runner()
                    patched_env = dict(os.environ)
                    if env_override is None:
                        patched_env.pop("SEED_PASSWORD", None)
                    else:
                        patched_env["SEED_PASSWORD"] = env_override
                    with mock.patch.dict(os.environ, patched_env, clear=True):
                        result = runner.invoke(args=["seed"])
                    self.assertEqual(result.exit_code, 0, result.output)
                    self.assertIn(f"Demo password: {DEFAULT_DEMO_PASSWORD}", result.output)

                    with app.app_context():
                        users = db.session.scalars(select(User).order_by(User.id)).all()
                        self.assertEqual(len(users), 5)
                        for user in users:
                            self.assertNotEqual(user.password_hash, DEFAULT_DEMO_PASSWORD)
                            self.assertTrue(user.check_password(DEFAULT_DEMO_PASSWORD))

                    client, response = self._login_as(app, "admin@example.com", DEFAULT_DEMO_PASSWORD)
                    self.assertEqual(response.status_code, 302)
                    self.assertEqual(response.headers["Location"], "/")
                    home = client.get("/")
                    self.assertEqual(home.status_code, 200)
                    self.assertIn("Signed in as Demo Admin (admin).", home.get_data(as_text=True))
                finally:
                    self._dispose_app(app)

    def test_seed_supports_seed_password_env_override_and_rejects_invalid_values(self):
        custom_password = "TeamCustomPass!99"
        app = self._make_isolated_app("isolated-seed-custom-password-test")
        try:
            runner = app.test_cli_runner()
            with mock.patch.dict(os.environ, {"SEED_PASSWORD": custom_password}, clear=False):
                result = runner.invoke(args=["seed"])
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIn(f"Demo password: {custom_password}", result.output)

            with app.app_context():
                users = db.session.scalars(select(User).order_by(User.id)).all()
                self.assertEqual(len(users), 5)
                for user in users:
                    self.assertNotEqual(user.password_hash, custom_password)
                    self.assertTrue(user.check_password(custom_password))
                    self.assertFalse(user.check_password(DEFAULT_DEMO_PASSWORD))

            client, response = self._login_as(app, "customer1@example.com", custom_password)
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response.headers["Location"], "/")
            self.assertIn("Signed in as Demo Customer 1 (customer).", client.get("/").get_data(as_text=True))
        finally:
            self._dispose_app(app)

        for bad_value in ("short7!", "        ", "a" * 129):
            with self.subTest(bad_value=repr(bad_value)):
                bad_app = self._make_isolated_app("isolated-seed-bad-password-test")
                try:
                    bad_runner = bad_app.test_cli_runner()
                    with mock.patch.dict(os.environ, {"SEED_PASSWORD": bad_value}, clear=False):
                        bad_result = bad_runner.invoke(args=["seed"])
                    self.assertNotEqual(bad_result.exit_code, 0)
                    self.assertIn("SEED_PASSWORD", bad_result.output)
                    with bad_app.app_context():
                        self.assertEqual(inspect(db.engine).get_table_names(), [])
                finally:
                    self._dispose_app(bad_app)

    def test_seed_provides_d2_demo_data_for_cancel_window_and_today_booking(self):
        app = self._make_isolated_app("isolated-seed-d2-test")
        try:
            runner = app.test_cli_runner()
            with mock.patch.dict(os.environ, {"SEED_PASSWORD": ""}, clear=False):
                result = runner.invoke(args=["seed"])
            self.assertEqual(result.exit_code, 0, result.output)

            now = datetime.now().replace(second=0, microsecond=0)
            today = now.date()
            tomorrow = today + timedelta(days=1)

            with app.app_context():
                shift_dates = set(db.session.scalars(select(WorkingShift.work_date)).all())
                self.assertIn(today, shift_dates)
                self.assertIn(tomorrow, shift_dates)

                appointments = db.session.scalars(
                    select(Appointment).order_by(Appointment.starts_at)
                ).all()
                self.assertEqual(len(appointments), 2)
                soon, later = appointments
                self.assertGreater(soon.starts_at, now)
                self.assertLessEqual(soon.starts_at, now + timedelta(hours=2))
                self.assertGreater(later.starts_at, now + timedelta(hours=2))
                for appointment in appointments:
                    self.assertLessEqual(appointment.starts_at.date(), today + timedelta(days=60))
                soon_id, later_id = soon.id, later.id

            client, login_response = self._login_as(app, "customer1@example.com", DEFAULT_DEMO_PASSWORD)
            self.assertEqual(login_response.status_code, 302)

            page = client.get("/my-appointments")
            self.assertEqual(page.status_code, 200)
            body = page.get_data(as_text=True)
            self.assertIn(f'data-appointment-id="{soon_id}"', body)
            self.assertIn('data-can-cancel="false"', body)
            self.assertIn('data-can-reschedule="true"', body)
            self.assertIn(f'data-appointment-id="{later_id}"', body)
            self.assertIn('data-can-cancel="true"', body)

            parser = _CsrfTokenParser()
            parser.feed(body)
            self.assertTrue(parser.token)

            blocked = client.post(
                f"/appointments/{soon_id}/cancel",
                headers={"Accept": "application/json", "X-CSRFToken": parser.token},
            )
            self.assertEqual(blocked.status_code, 409)
            self.assertEqual(blocked.get_json()["error"], "CANCEL_WINDOW_CLOSED")

            allowed = client.post(
                f"/appointments/{later_id}/cancel",
                data={"csrf_token": parser.token},
            )
            self.assertEqual(allowed.status_code, 303)
            with app.app_context():
                self.assertEqual(db.session.get(Appointment, soon_id).status, "confirmed")
                self.assertEqual(db.session.get(Appointment, later_id).status, "cancelled")
        finally:
            self._dispose_app(app)

        for fixed_now in (
            datetime(2030, 5, 1, 10, 0),
            datetime(2030, 5, 1, 19, 7),
            datetime(2030, 5, 1, 22, 45),
            datetime(2030, 5, 1, 23, 30),
        ):
            with self.subTest(fixed_now=fixed_now.isoformat()):
                clock_app = self._make_isolated_app("isolated-seed-clock-edge-test")
                try:
                    with clock_app.app_context():
                        db.create_all()
                        add_demo_data(
                            DEFAULT_DEMO_PASSWORD,
                            fixed_now.date() + timedelta(days=1),
                            now=fixed_now,
                        )
                        db.session.commit()
                        soon, later = db.session.scalars(
                            select(Appointment).order_by(Appointment.starts_at)
                        ).all()
                        self.assertGreater(soon.starts_at, fixed_now)
                        self.assertLessEqual(soon.starts_at, fixed_now + timedelta(hours=2))
                        self.assertEqual(soon.starts_at.minute % 15, 0)
                        self.assertGreater(later.starts_at, fixed_now + timedelta(hours=2))
                        shifts = db.session.scalars(
                            select(WorkingShift).where(
                                WorkingShift.stylist_id == soon.stylist_id,
                                WorkingShift.work_date == soon.starts_at.date(),
                            )
                        ).all()
                        self.assertTrue(
                            any(
                                shift.start_time <= soon.starts_at.time()
                                and soon.ends_at.time() <= shift.end_time
                                for shift in shifts
                            )
                        )
                finally:
                    self._dispose_app(clock_app)

    def test_base_template_includes_stylesheet_and_role_appropriate_navigation(self):
        app = self._make_isolated_app("isolated-base-template-test")
        try:
            runner = app.test_cli_runner()
            with mock.patch.dict(os.environ, {"SEED_PASSWORD": ""}, clear=False):
                self.assertEqual(runner.invoke(args=["seed"]).exit_code, 0)

            anon = app.test_client()
            for path in ("/", "/auth/login", "/services"):
                html = anon.get(path).get_data(as_text=True)
                head, body = html.split("</head>", 1)
                self.assertIn('href="/static/css/app.css"', head)
                self.assertNotIn('href="/static/css/app.css"', body)
                self.assertNotIn('class="subnav"', body)
                self.assertIn('href="/services"', body)
                self.assertNotIn('href="/my-appointments"', body)

            customer_client, response = self._login_as(app, "customer1@example.com", DEFAULT_DEMO_PASSWORD)
            self.assertEqual(response.status_code, 302)
            for path in ("/", "/services", "/my-appointments"):
                html = customer_client.get(path).get_data(as_text=True)
                head, body = html.split("</head>", 1)
                self.assertIn('href="/static/css/app.css"', head)
                self.assertNotIn('href="/static/css/app.css"', body)
                self.assertNotIn('class="subnav"', body)
                self.assertIn('href="/services"', body)
                self.assertIn('href="/my-appointments"', body)

            admin_client, response = self._login_as(app, "admin@example.com", DEFAULT_DEMO_PASSWORD)
            self.assertEqual(response.status_code, 302)
            admin_html = admin_client.get("/").get_data(as_text=True)
            self.assertIn('href="/services"', admin_html)
            self.assertIn('href="/auth/staff"', admin_html)
            self.assertNotIn('href="/my-appointments"', admin_html)
        finally:
            self._dispose_app(app)
