"""Role C acceptance tests for C-1 and C-2.

Every test drives a real Flask request through the app, because the contract
only accepts real HTTP evidence (spec section 0.5).

``app.py`` registers the customer blueprint, so the tests run against the wired
application instead of adding the blueprint themselves.
"""

import re
import unittest
from datetime import datetime, time, timedelta

from app import create_app
from models import (
    Appointment,
    Service,
    SlotAllocation,
    StaffService,
    User,
    WorkingShift,
    Workstation,
    db,
)

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

        # C-4 needs a day the stylist actually works on.  Three days out keeps
        # the fixture clear of the appointments created immediately below, and
        # the last day of the booking window exercises the inclusive boundary.
        self.booking_day = (now + timedelta(days=3)).date()
        self.last_bookable_day = (now + timedelta(days=60)).date()
        db.session.add_all(
            [
                WorkingShift(
                    stylist=self.stylist,
                    work_date=self.booking_day,
                    start_time=time(9),
                    end_time=time(17),
                ),
                WorkingShift(
                    stylist=self.stylist,
                    work_date=self.last_bookable_day,
                    start_time=time(9),
                    end_time=time(17),
                ),
            ]
        )

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

    def _row_block(self, html, appointment_id):
        """The whole <tr> element, so cell contents can be asserted too."""
        match = re.search(
            r'<tr[^>]*data-appointment-id="%d".*?</tr>' % appointment_id, html, re.S
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
        # The visible label is human-readable; the machine value stays ISO and
        # lives in the <time datetime="..."> attribute.
        stamps = re.findall(r'<time class="when" datetime="([^"]+)"', body)
        self.assertTrue(stamps)
        for stamp in stamps:
            self.assertRegex(stamp, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$")

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

    # ------------------------------------------------------------------- C-3

    def test_booking_page_renders_the_slot_loader_for_a_bookable_pair(self):
        self._login("alice@example.com")
        response = self.client.get(
            f"/book?service_id={self.haircut.id}&stylist_id={self.stylist.id}"
        )
        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('data-slots-url="/api/slots"', body)
        self.assertIn(f'data-service-id="{self.haircut.id}"', body)
        self.assertIn(f'data-stylist-id="{self.stylist.id}"', body)
        self.assertIn("booking.js", body)

    def test_booking_page_limits_the_date_range_to_the_contract_window(self):
        self._login("alice@example.com")
        body = self.client.get(
            f"/book?service_id={self.haircut.id}&stylist_id={self.stylist.id}"
        ).get_data(as_text=True)
        today = datetime.now().date()
        self.assertIn(f'min="{today.isoformat()}"', body)
        self.assertIn(f'max="{(today + timedelta(days=60)).isoformat()}"', body)

    def test_booking_page_rejects_a_missing_parameter(self):
        self._login("alice@example.com")
        self.assertEqual(self.client.get("/book").status_code, 400)
        self.assertEqual(
            self.client.get(f"/book?service_id={self.haircut.id}").status_code, 400
        )

    def test_booking_page_hides_an_inactive_service(self):
        self._login("alice@example.com")
        self.assertEqual(
            self.client.get(
                f"/book?service_id={self.colouring.id}&stylist_id={self.stylist.id}"
            ).status_code,
            404,
        )

    def test_booking_page_rejects_a_stylist_without_the_skill(self):
        self._login("alice@example.com")
        self.assertEqual(
            self.client.get(
                f"/book?service_id={self.haircut.id}&stylist_id={self.other_stylist.id}"
            ).status_code,
            404,
        )

    def test_booking_page_rejects_an_inactive_stylist(self):
        self._login("alice@example.com")
        self.assertEqual(
            self.client.get(
                f"/book?service_id={self.haircut.id}&stylist_id={self.retired_stylist.id}"
            ).status_code,
            404,
        )

    def test_booking_page_rejects_a_user_who_is_not_a_stylist(self):
        self._login("alice@example.com")
        self.assertEqual(
            self.client.get(
                f"/book?service_id={self.haircut.id}&stylist_id={self.bob.id}"
            ).status_code,
            404,
        )

    def test_booking_page_requires_a_customer_session(self):
        self.assertEqual(
            self.client.get(
                f"/book?service_id={self.haircut.id}&stylist_id={self.stylist.id}"
            ).status_code,
            302,
        )
        self._login("stylist@example.com")
        self.assertEqual(
            self.client.get(
                f"/book?service_id={self.haircut.id}&stylist_id={self.stylist.id}"
            ).status_code,
            403,
        )

    def test_service_detail_links_to_the_booking_page(self):
        body = self.client.get(f"/services/{self.haircut.id}").get_data(as_text=True)
        self.assertIn(
            f"/book?service_id={self.haircut.id}&amp;stylist_id={self.stylist.id}", body
        )

    # ------------------------------------------------------------------- C-4

    def _post_booking(self, date_value, start_value, stylist_id=None):
        return self.client.post(
            "/book",
            data={
                "service_id": str(self.haircut.id),
                "stylist_id": str(stylist_id or self.stylist.id),
                "date": date_value,
                "start": start_value,
            },
        )

    def _appointment(self, appointment_id):
        return db.session.get(Appointment, appointment_id)

    def test_booking_is_created_and_frozen_at_the_quoted_price(self):
        self._login("alice@example.com")
        response = self._post_booking(self.booking_day.isoformat(), "09:00")

        self.assertEqual(response.status_code, 303)
        created = (
            db.session.query(Appointment)
            .filter_by(customer_id=self.alice.id, status="confirmed")
            .order_by(Appointment.id.desc())
            .first()
        )
        self.assertIsNotNone(created)
        self.assertIn(f"/my-appointments?booked={created.id}", response.headers["Location"])
        self.assertEqual(created.agreed_price_minor, 2500)
        self.assertEqual(created.ends_at - created.starts_at, timedelta(minutes=30))
        # A 30-minute service reserves two 15-minute cells.
        cells = db.session.query(SlotAllocation).filter_by(appointment_id=created.id).count()
        self.assertEqual(cells, 2)

    def test_a_taken_slot_returns_409_and_creates_no_second_booking(self):
        self._login("alice@example.com")
        self.assertEqual(self._post_booking(self.booking_day.isoformat(), "09:00").status_code, 303)

        before = db.session.query(Appointment).filter_by(status="confirmed").count()
        response = self._post_booking(self.booking_day.isoformat(), "09:00")
        after = db.session.query(Appointment).filter_by(status="confirmed").count()

        self.assertEqual(response.status_code, 409)
        self.assertIn("data-booking-error", response.get_data(as_text=True))
        self.assertEqual(before, after)

    def test_a_json_caller_gets_the_stable_error_code(self):
        self._login("alice@example.com")
        self._post_booking(self.booking_day.isoformat(), "09:00")
        response = self.client.post(
            "/book",
            data={
                "service_id": str(self.haircut.id),
                "stylist_id": str(self.stylist.id),
                "date": self.booking_day.isoformat(),
                "start": "09:00",
            },
            headers={"Accept": "application/json"},
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["error"], "SLOT_TAKEN")

    def test_a_malformed_date_is_rejected_before_anything_is_saved(self):
        self._login("alice@example.com")
        response = self._post_booking("2026-13-40", "09:00")
        self.assertEqual(response.status_code, 400)
        self.assertIn("data-booking-error", response.get_data(as_text=True))

    def test_a_start_off_the_quarter_hour_is_rejected(self):
        self._login("alice@example.com")
        response = self._post_booking(self.booking_day.isoformat(), "09:10")
        self.assertEqual(response.status_code, 400)

    def test_a_date_beyond_the_window_returns_date_out_of_range(self):
        self._login("alice@example.com")
        too_far = (datetime.now().date() + timedelta(days=61)).isoformat()
        response = self.client.post(
            "/book",
            data={
                "service_id": str(self.haircut.id),
                "stylist_id": str(self.stylist.id),
                "date": too_far,
                "start": "09:00",
            },
            headers={"Accept": "application/json"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], "DATE_OUT_OF_RANGE")

    def test_another_customer_cannot_take_the_same_slot(self):
        self._login("alice@example.com")
        self._post_booking(self.booking_day.isoformat(), "09:00")
        self.client.post("/auth/logout")
        self._login("bob@example.com")

        self.assertEqual(self._post_booking(self.booking_day.isoformat(), "09:00").status_code, 409)

    def test_cancel_releases_the_slot_and_keeps_the_record(self):
        self._login("alice@example.com")
        self._post_booking(self.booking_day.isoformat(), "09:00")
        created = (
            db.session.query(Appointment)
            .filter_by(customer_id=self.alice.id)
            .order_by(Appointment.id.desc())
            .first()
        )

        response = self.client.post(f"/appointments/{created.id}/cancel")
        self.assertEqual(response.status_code, 303)

        db.session.expire_all()
        self.assertEqual(self._appointment(created.id).status, "cancelled")
        self.assertEqual(
            db.session.query(SlotAllocation).filter_by(appointment_id=created.id).count(), 0
        )

    def test_cancel_inside_the_two_hour_window_is_refused(self):
        self._login("alice@example.com")
        response = self.client.post(f"/appointments/{self.soon.id}/cancel")
        self.assertEqual(response.status_code, 409)
        body = response.get_data(as_text=True)
        self.assertIn("data-booking-error", body)
        self.assertEqual(self._appointment(self.soon.id).status, "confirmed")

    def test_cancel_twice_reports_invalid_state(self):
        self._login("alice@example.com")
        self.client.post(f"/appointments/{self.far_future.id}/cancel")
        response = self.client.post(f"/appointments/{self.far_future.id}/cancel")
        self.assertEqual(response.status_code, 409)

    def test_cancel_of_someone_elses_appointment_is_forbidden(self):
        self._login("alice@example.com")
        self.assertEqual(
            self.client.post(f"/appointments/{self.someone_elses.id}/cancel").status_code, 403
        )
        self.assertEqual(self._appointment(self.someone_elses.id).status, "confirmed")

    def test_reschedule_form_uses_the_reschedule_slot_mode(self):
        self._login("alice@example.com")
        response = self.client.get(f"/appointments/{self.far_future.id}/reschedule")
        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('data-mode="reschedule"', body)
        self.assertIn(f'data-appointment-id="{self.far_future.id}"', body)

    def test_reschedule_moves_the_booking_and_keeps_price_and_duration(self):
        self._login("alice@example.com")
        original = self._appointment(self.far_future.id)
        price, span = original.agreed_price_minor, original.ends_at - original.starts_at

        response = self.client.post(
            f"/appointments/{self.far_future.id}/reschedule",
            data={"date": self.booking_day.isoformat(), "start": "11:00"},
        )
        self.assertEqual(response.status_code, 303)

        db.session.expire_all()
        moved = self._appointment(self.far_future.id)
        self.assertEqual(moved.starts_at.time(), time(11, 0))
        self.assertEqual(moved.agreed_price_minor, price)
        self.assertEqual(moved.ends_at - moved.starts_at, span)

    def test_reschedule_onto_a_taken_slot_keeps_the_original_intact(self):
        self._login("alice@example.com")
        self._post_booking(self.booking_day.isoformat(), "09:00")
        before = self._appointment(self.far_future.id)
        original_start = before.starts_at

        response = self.client.post(
            f"/appointments/{self.far_future.id}/reschedule",
            data={"date": self.booking_day.isoformat(), "start": "09:00"},
        )
        self.assertEqual(response.status_code, 409)

        db.session.expire_all()
        after = self._appointment(self.far_future.id)
        self.assertEqual(after.starts_at, original_start)
        self.assertEqual(after.status, "confirmed")

    def test_reschedule_is_refused_once_the_appointment_has_started(self):
        self._login("alice@example.com")
        response = self.client.get(f"/appointments/{self.past.id}/reschedule")
        self.assertEqual(response.status_code, 409)

    def test_writes_require_a_customer_session(self):
        payload = {
            "service_id": str(self.haircut.id),
            "stylist_id": str(self.stylist.id),
            "date": self.booking_day.isoformat(),
            "start": "09:00",
        }
        self.assertEqual(self.client.post("/book", data=payload).status_code, 302)
        self.assertEqual(
            self.client.post(f"/appointments/{self.far_future.id}/cancel").status_code, 302
        )
        self.assertEqual(
            self.client.post(
                f"/appointments/{self.far_future.id}/reschedule",
                data={"date": self.booking_day.isoformat(), "start": "11:00"},
            ).status_code,
            302,
        )

    # ------------------------------------- acceptance checks V-01, V-03, V-15,
    #                                       V-24, V-28, V-39, V-41 and forgery

    def test_v01_anonymous_visitor_is_sent_to_login_with_next(self):
        response = self.client.get(
            f"/book?service_id={self.haircut.id}&stylist_id={self.stylist.id}"
        )
        self.assertEqual(response.status_code, 302)
        location = response.headers["Location"]
        self.assertIn("/auth/login", location)
        self.assertIn("next=", location)

    def test_v03_a_write_without_a_csrf_token_is_rejected(self):
        self._login("alice@example.com")
        self.app.config["WTF_CSRF_ENABLED"] = True
        try:
            response = self.client.post(f"/appointments/{self.far_future.id}/cancel")
        finally:
            self.app.config["WTF_CSRF_ENABLED"] = False
        self.assertEqual(response.status_code, 400)
        db.session.expire_all()
        self.assertEqual(self._appointment(self.far_future.id).status, "confirmed")

    def test_v15_a_start_in_the_past_is_rejected(self):
        self._login("alice@example.com")
        yesterday = (datetime.now().date() - timedelta(days=1)).isoformat()
        self.assertEqual(self._post_booking(yesterday, "09:00").status_code, 400)

    def test_v24_cancelling_puts_the_slot_back_on_the_slots_endpoint(self):
        self._login("alice@example.com")
        day = self.booking_day.isoformat()
        self.assertEqual(self._post_booking(day, "09:00").status_code, 303)

        def slots():
            response = self.client.get(
                f"/api/slots?service_id={self.haircut.id}&stylist_id={self.stylist.id}&date={day}",
                headers={"Accept": "application/json"},
            )
            return response.get_json()["slots"]

        self.assertNotIn("09:00", slots())
        created = (
            db.session.query(Appointment)
            .filter_by(customer_id=self.alice.id)
            .order_by(Appointment.id.desc())
            .first()
        )
        self.client.post(f"/appointments/{created.id}/cancel")
        self.assertIn("09:00", slots())

    def test_v28_a_price_change_does_not_rewrite_an_existing_booking(self):
        self._login("alice@example.com")
        self._post_booking(self.booking_day.isoformat(), "09:00")
        created = (
            db.session.query(Appointment)
            .filter_by(customer_id=self.alice.id)
            .order_by(Appointment.id.desc())
            .first()
        )
        self.haircut.price_minor = 9900
        db.session.commit()

        body = self.client.get("/my-appointments").get_data(as_text=True)
        row = self._row_block(body, created.id)
        self.assertIn("25.00", row)
        self.assertNotIn("99.00", row)

    def test_v39_rescheduling_inside_the_two_hour_window_is_still_allowed(self):
        self._login("alice@example.com")
        response = self.client.post(
            f"/appointments/{self.soon.id}/reschedule",
            data={"date": self.booking_day.isoformat(), "start": "11:00"},
        )
        self.assertEqual(response.status_code, 303)
        db.session.expire_all()
        self.assertEqual(self._appointment(self.soon.id).starts_at.time(), time(11, 0))

    def test_v41_the_last_day_of_the_booking_window_is_accepted(self):
        self._login("alice@example.com")
        response = self._post_booking(self.last_bookable_day.isoformat(), "09:00")
        self.assertEqual(response.status_code, 303)

    def test_forged_fields_never_reach_the_booking(self):
        self._login("alice@example.com")
        self.client.post(
            "/book",
            data={
                "service_id": str(self.haircut.id),
                "stylist_id": str(self.stylist.id),
                "date": self.booking_day.isoformat(),
                "start": "09:00",
                # All of the below are decided by the server and must be ignored.
                "customer_id": str(self.bob.id),
                "price": "0.01",
                "ends_at": "1999-01-01T00:00",
                "workstation_id": "999",
                "status": "cancelled",
            },
        )
        created = (
            db.session.query(Appointment)
            .order_by(Appointment.id.desc())
            .first()
        )
        self.assertEqual(created.customer_id, self.alice.id)
        self.assertEqual(created.agreed_price_minor, 2500)
        self.assertEqual(created.status, "confirmed")
        self.assertEqual(created.workstation_id, self.chair.id)
        self.assertEqual(created.ends_at - created.starts_at, timedelta(minutes=30))

    def test_service_list_reports_the_required_workstation_type(self):
        body = self.client.get("/services").get_data(as_text=True)
        self.assertIn('data-workstation-type="chair"', body)
        self.assertIn("Standard chair", body)

    def test_my_appointments_expose_the_contract_ids(self):
        self._login("alice@example.com")
        body = self.client.get("/my-appointments").get_data(as_text=True)
        row = self._row(body, self.far_future.id)
        self.assertIn(f'data-customer-id="{self.alice.id}"', row)
        self.assertIn(f'data-stylist-id="{self.stylist.id}"', row)
        self.assertIn(f'data-service-id="{self.haircut.id}"', row)
        self.assertIn(f'data-workstation-id="{self.chair.id}"', row)


if __name__ == "__main__":
    unittest.main()
