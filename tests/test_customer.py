"""Role C acceptance tests for C-1 and C-2.

Every test drives a real Flask request through the app, because the contract
only accepts real HTTP evidence (spec section 0.5).

``app.py`` registers the customer blueprint, so the tests run against the wired
application instead of adding the blueprint themselves.
"""

import re
import unittest
from datetime import datetime, timedelta

from app import create_app
from models import Appointment, Service, StaffService, User, Workstation, db

PASSWORD = "Passw0rd!"


class CustomerPagesTest(unittest.TestCase):
    def setUp(self):
        self.app = create_app(
            {
                "TESTING": True,
                "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
                "WTF_CSRF_ENABLED": False,
            }
        )
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        self.client = self.app.test_client()
        self._build_fixtures()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    # ------------------------------------------------------------------ setup

    def _build_fixtures(self):
        now = datetime.now()

        def make_user(email, name, role, active=True):
            user = User(name=name, email=email, role=role, is_active=active)
            user.set_password(PASSWORD)
            db.session.add(user)
            return user

        self.stylist = make_user("stylist@example.com", "Qualified Stylist", "stylist")
        self.other_stylist = make_user("other@example.com", "Unrelated Stylist", "stylist")
        self.retired_stylist = make_user("retired@example.com", "Retired Stylist", "stylist", active=False)
        self.alice = make_user("alice@example.com", "Alice Customer", "customer")
        self.bob = make_user("bob@example.com", "Bob Customer", "customer")

        self.haircut = Service(
            name="Haircut",
            description="Cut and finish.",
            price_minor=2500,
            duration_minutes=30,
            required_workstation_type="chair",
        )
        self.colouring = Service(
            name="Colouring",
            description="Single process colour.",
            price_minor=6000,
            duration_minutes=60,
            required_workstation_type="colour",
            is_active=False,
        )
        self.chair = Workstation(label="Chair 1", workstation_type="chair")
        db.session.add_all([self.haircut, self.colouring, self.chair])
        db.session.flush()

        # Only the qualified stylist is linked to the haircut; the retired one
        # is linked too but must be filtered out because it is inactive.
        db.session.add_all(
            [
                StaffService(stylist=self.stylist, service=self.haircut),
                StaffService(stylist=self.retired_stylist, service=self.haircut),
            ]
        )

        def make_appointment(customer, start, status="confirmed"):
            row = Appointment(
                customer=customer,
                stylist=self.stylist,
                service=self.haircut,
                workstation=self.chair,
                starts_at=start,
                ends_at=start + timedelta(minutes=30),
                agreed_price_minor=2500,
                status=status,
            )
            db.session.add(row)
            return row

        self.far_future = make_appointment(self.alice, now + timedelta(hours=5))
        self.soon = make_appointment(self.alice, now + timedelta(hours=1))
        self.past = make_appointment(self.alice, now - timedelta(hours=2), status="completed")
        self.someone_elses = make_appointment(self.bob, now + timedelta(hours=5))
        db.session.commit()

    # ----------------------------------------------------------------- helpers

    def _login(self, email):
        return self.client.post(
            "/auth/login",
            data={"email": email, "password": PASSWORD},
            follow_redirects=False,
        )

    def _row(self, html, appointment_id):
        match = re.search(
            r'<tr[^>]*data-appointment-id="%d"[^>]*>' % appointment_id, html
        )
        self.assertIsNotNone(match, "appointment %d missing from the page" % appointment_id)
        return match.group(0)

    @staticmethod
    def _row_ids(html):
        return sorted(int(value) for value in re.findall(r'data-appointment-id="(\d+)"', html))

    # ------------------------------------------------------------------- C-1

    def test_service_list_shows_only_active_services(self):
        response = self.client.get("/services")
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("Haircut", body)
        self.assertNotIn("Colouring", body)

    def test_service_list_renders_price_as_two_decimal_string(self):
        body = self.client.get("/services").get_data(as_text=True)
        self.assertIn(">25.00<", body)
        self.assertNotIn("2500", body)

    def test_service_detail_lists_qualified_active_stylists_only(self):
        body = self.client.get(f"/services/{self.haircut.id}").get_data(as_text=True)
        self.assertIn("Qualified Stylist", body)
        self.assertNotIn("Unrelated Stylist", body)
        self.assertNotIn("Retired Stylist", body)

    def test_service_detail_reports_duration_and_price(self):
        body = self.client.get(f"/services/{self.haircut.id}").get_data(as_text=True)
        self.assertIn('data-duration="30"', body)
        self.assertIn('data-price="25.00"', body)

    def test_unknown_service_returns_404(self):
        self.assertEqual(self.client.get("/services/9999").status_code, 404)

    def test_inactive_service_is_not_advertised(self):
        self.assertEqual(self.client.get(f"/services/{self.colouring.id}").status_code, 404)

    # ------------------------------------------------------------------- C-2

    def test_my_appointments_redirects_anonymous_visitor_to_login(self):
        response = self.client.get("/my-appointments")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/auth/login", response.headers["Location"])

    def test_my_appointments_rejects_a_non_customer_role(self):
        self._login("stylist@example.com")
        self.assertEqual(self.client.get("/my-appointments").status_code, 403)

    def test_my_appointments_lists_only_the_signed_in_customer_records(self):
        self._login("alice@example.com")
        body = self.client.get("/my-appointments").get_data(as_text=True)
        self.assertEqual(
            self._row_ids(body),
            sorted([self.far_future.id, self.soon.id, self.past.id]),
        )
        self.assertNotIn(str(self.someone_elses.id), self._row_ids(body))

    def test_booking_window_flags_allow_cancel_and_reschedule_when_far_ahead(self):
        self._login("alice@example.com")
        body = self.client.get("/my-appointments").get_data(as_text=True)
        row = self._row(body, self.far_future.id)
        self.assertIn('data-can-cancel="true"', row)
        self.assertIn('data-can-reschedule="true"', row)

    def test_two_hour_window_blocks_cancel_but_still_allows_reschedule(self):
        self._login("alice@example.com")
        body = self.client.get("/my-appointments").get_data(as_text=True)
        row = self._row(body, self.soon.id)
        self.assertIn('data-can-cancel="false"', row)
        self.assertIn('data-can-reschedule="true"', row)

    def test_finished_appointment_cannot_be_changed(self):
        self._login("alice@example.com")
        body = self.client.get("/my-appointments").get_data(as_text=True)
        row = self._row(body, self.past.id)
        self.assertIn('data-can-cancel="false"', row)
        self.assertIn('data-can-reschedule="false"', row)

    def test_timestamps_use_the_contract_format(self):
        self._login("alice@example.com")
        body = self.client.get("/my-appointments").get_data(as_text=True)
        stamps = re.findall(r'class="when">([^<]+)<', body)
        self.assertTrue(stamps)
        for stamp in stamps:
            self.assertRegex(stamp.strip(), r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$")

    def test_booked_parameter_highlights_the_new_booking(self):
        self._login("alice@example.com")
        body = self.client.get(
            f"/my-appointments?booked={self.far_future.id}"
        ).get_data(as_text=True)
        self.assertIn(f'data-booked="{self.far_future.id}"', body)

    def test_customer_without_bookings_sees_the_empty_state(self):
        self._login("bob@example.com")
        self.client.post("/auth/logout")
        carol = User(name="Carol Customer", email="carol@example.com", role="customer")
        carol.set_password(PASSWORD)
        db.session.add(carol)
        db.session.commit()

        self._login("carol@example.com")
        response = self.client.get("/my-appointments")
        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("You have no appointments yet.", body)
        self.assertEqual(self._row_ids(body), [])


if __name__ == "__main__":
    unittest.main()
