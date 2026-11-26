"""Booking rules.

Part 1 (Role B): database-level checks for T3/T4/T6/T7 and the seed command.
Part 2 (Role A, below ``SeedTests``): ``availability.py`` and ``booking.py`` -
slot listing, create, reschedule, cancel, the 60-day and 2-hour rules, the
operational-change guard and the concurrency tests (T1, T2, T5, T8, V-22, V-23).

Evidence level: ``/api/slots`` is tested through real HTTP requests.  The write
routes (``/book``, ``/cancel``, ``/reschedule``) belong to Role C and do not
exist yet, so those rules are tested by calling the booking functions directly
and still count as "pending route integration" in the acceptance table.
"""

from datetime import date, datetime, time, timedelta
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from flask import g
from flask_login import login_user
from sqlalchemy import delete, func, inspect, select, text
from sqlalchemy.exc import IntegrityError
from werkzeug.exceptions import Forbidden, NotFound

import availability
import booking
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


SLOT_LENGTH = timedelta(minutes=15)


class BookingRuleTests(unittest.TestCase):
    def setUp(self):
        app = create_app({
            "TESTING": True,
            "SECRET_KEY": "isolated-rule-test",
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        })
        context = app.app_context()
        context.push()
        self.addCleanup(context.pop)
        self.addCleanup(db.engine.dispose)
        self.addCleanup(db.session.remove)
        db.create_all()

        self.customer = self._add_user("Customer", "customer")
        self.other_customer = self._add_user("Other Customer", "customer")
        self.stylist = self._add_user("Stylist", "stylist")
        self.other_stylist = self._add_user("Other Stylist", "stylist")
        self.service = Service(
            name="Colouring",
            description="A 60-minute service",
            price_minor=5500,
            duration_minutes=60,
            required_workstation_type="colour",
        )
        self.workstation = Workstation(label="Colour 1", workstation_type="colour")
        self.other_workstation = Workstation(label="Colour 2", workstation_type="colour")
        db.session.add_all([self.service, self.workstation, self.other_workstation])
        db.session.commit()
        self.ten = datetime(2030, 1, 2, 10)
        self.eleven = self.ten + timedelta(hours=1)

    def _add_user(self, name, role):
        email = name.lower().replace(" ", ".") + "@example.com"
        user = User(name=name, email=email, role=role)
        user.set_password("database-test-only")
        db.session.add(user)
        return user

    def _stage_booking(self, customer, stylist, workstation, start):
        appointment = Appointment(
            customer_id=customer.id,
            stylist_id=stylist.id,
            service_id=self.service.id,
            workstation_id=workstation.id,
            starts_at=start,
            ends_at=start + timedelta(minutes=self.service.duration_minutes),
            agreed_price_minor=self.service.price_minor,
            status="confirmed",
        )
        db.session.add(appointment)
        db.session.flush()
        self._stage_allocations(appointment)
        return appointment

    def _stage_allocations(self, appointment):
        # Test fixture only. Role A supplies the production scheduling logic.
        for index in range((appointment.ends_at - appointment.starts_at) // SLOT_LENGTH):
            db.session.add(SlotAllocation(
                appointment_id=appointment.id,
                stylist_id=appointment.stylist_id,
                workstation_id=appointment.workstation_id,
                slot_start=appointment.starts_at + index * SLOT_LENGTH,
            ))

    def _occupied_starts(self, appointment_id):
        return db.session.scalars(
            select(SlotAllocation.slot_start)
            .where(SlotAllocation.appointment_id == appointment_id)
            .order_by(SlotAllocation.slot_start)
        ).all()

    def _clear_allocations(self, appointment_id):
        db.session.execute(
            delete(SlotAllocation).where(SlotAllocation.appointment_id == appointment_id)
        )

    def test_t3_partial_overlap_rejects_second_booking(self):
        original = self._stage_booking(self.customer, self.stylist, self.workstation, self.ten)
        db.session.commit()
        original_id = original.id
        original_slots = self._occupied_starts(original_id)

        # A different workstation isolates the stylist uniqueness constraint.
        with self.assertRaisesRegex(IntegrityError, r"UNIQUE constraint failed: slot_allocation.stylist_id"):
            self._stage_booking(
                self.other_customer, self.stylist, self.other_workstation, self.ten + timedelta(minutes=30)
            )
            db.session.commit()
        db.session.rollback()

        self.assertEqual(db.session.scalars(select(Appointment.id)).all(), [original_id])
        self.assertEqual(self._occupied_starts(original_id), original_slots)
        self.assertEqual(db.session.scalar(select(func.count()).select_from(SlotAllocation)), 4)

    def test_t4_back_to_back_appointments_can_both_commit(self):
        first = self._stage_booking(self.customer, self.stylist, self.workstation, self.ten)
        second = self._stage_booking(self.other_customer, self.stylist, self.workstation, self.eleven)
        db.session.commit()

        first_slots = self._occupied_starts(first.id)
        second_slots = self._occupied_starts(second.id)
        self.assertEqual(first.ends_at, second.starts_at)
        self.assertEqual(first_slots, [self.ten + index * SLOT_LENGTH for index in range(4)])
        self.assertEqual(second_slots, [self.eleven + index * SLOT_LENGTH for index in range(4)])

    def test_t6_failed_reschedule_restores_original_appointment_and_slots(self):
        original = self._stage_booking(self.customer, self.stylist, self.workstation, self.ten)
        blocking = self._stage_booking(self.other_customer, self.other_stylist, self.workstation, self.eleven)
        db.session.commit()
        original_id = original.id
        original_slots = self._occupied_starts(original_id)
        blocking_slots = self._occupied_starts(blocking.id)

        self._clear_allocations(original_id)
        original.starts_at = self.eleven
        original.ends_at = self.eleven + timedelta(hours=1)
        db.session.flush()
        self._stage_allocations(original)
        # A different stylist isolates the workstation uniqueness constraint.
        with self.assertRaisesRegex(IntegrityError, r"UNIQUE constraint failed: slot_allocation.workstation_id"):
            db.session.commit()
        db.session.rollback()

        restored = db.session.get(Appointment, original_id)
        self.assertEqual((restored.starts_at, restored.ends_at, restored.status), (self.ten, self.eleven, "confirmed"))
        self.assertEqual(self._occupied_starts(original_id), original_slots)
        self.assertEqual(self._occupied_starts(blocking.id), blocking_slots)

    def test_t7_cancellation_preserves_history_and_releases_slots(self):
        original = self._stage_booking(self.customer, self.stylist, self.workstation, self.ten)
        db.session.commit()
        original_id = original.id
        original_slots = self._occupied_starts(original_id)

        original.status = "cancelled"
        self._clear_allocations(original_id)
        db.session.commit()
        replacement = self._stage_booking(self.other_customer, self.stylist, self.workstation, self.ten)
        db.session.commit()

        self.assertEqual(original.status, "cancelled")
        self.assertEqual(original.customer_id, self.customer.id)
        self.assertEqual(self._occupied_starts(original_id), [])
        self.assertEqual(replacement.customer_id, self.other_customer.id)
        self.assertEqual(self._occupied_starts(replacement.id), original_slots)

    def test_deactivated_service_preserves_appointment_reference(self):
        appointment = self._stage_booking(self.customer, self.stylist, self.workstation, self.ten)
        db.session.commit()
        service_id = self.service.id
        self.service.is_active = False
        db.session.commit()

        self.assertEqual(appointment.service_id, service_id)
        self.assertFalse(db.session.get(Service, service_id).is_active)
        with self.assertRaisesRegex(IntegrityError, "FOREIGN KEY constraint failed"):
            db.session.execute(delete(Service).where(Service.id == service_id))
        db.session.rollback()
        self.assertEqual(appointment.service_id, service_id)


class SeedTests(unittest.TestCase):
    def test_seed_creates_all_tables_and_is_safe_to_rerun(self):
        app = create_app({
            "TESTING": True,
            "SECRET_KEY": "isolated-seed-test",
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        })
        runner = app.test_cli_runner()
        first = runner.invoke(args=["seed"])
        self.assertEqual(first.exit_code, 0, first.output)
        second = runner.invoke(args=["seed"])
        self.assertEqual(second.exit_code, 0, second.output)

        with app.app_context():
            self.assertEqual(
                set(inspect(db.engine).get_table_names()),
                {
                    "user", "service", "staff_service", "workstation", "working_shift",
                    "unavailability", "appointment", "slot_allocation",
                },
            )
            roles = db.session.scalars(select(User.role)).all()
            self.assertCountEqual(roles, ["admin", "stylist", "stylist", "customer", "customer"])
            now = datetime.now()
            bookings = db.session.scalars(select(Appointment).order_by(Appointment.starts_at)).all()
            self.assertEqual(len(bookings), 2)
            soon_booking, next_day_booking = bookings
            self.assertEqual(soon_booking.status, "confirmed")
            self.assertGreater(soon_booking.starts_at, now)
            self.assertLessEqual(soon_booking.starts_at, now + timedelta(hours=2))
            self.assertEqual(soon_booking.ends_at, soon_booking.starts_at + timedelta(minutes=30))
            self.assertEqual(next_day_booking.status, "confirmed")
            self.assertGreater(next_day_booking.starts_at, now + timedelta(hours=2))
            self.assertEqual(next_day_booking.ends_at, next_day_booking.starts_at + timedelta(hours=1))
            for booking, expected_slots in ((soon_booking, 2), (next_day_booking, 4)):
                slots = db.session.scalars(
                    select(SlotAllocation)
                    .where(SlotAllocation.appointment_id == booking.id)
                    .order_by(SlotAllocation.slot_start)
                ).all()
                self.assertEqual(len(slots), expected_slots)
                for index, slot in enumerate(slots):
                    self.assertEqual(slot.appointment_id, booking.id)
                    self.assertEqual(slot.stylist_id, booking.stylist_id)
                    self.assertEqual(slot.workstation_id, booking.workstation_id)
                    self.assertEqual(slot.slot_start, booking.starts_at + index * SLOT_LENGTH)


# ---------------------------------------------------------------------------
# Part 2 (Role A)
# ---------------------------------------------------------------------------

NOW = datetime(2030, 1, 1, 8, 0)  # fixed clock for every Role A test
DAY = date(2030, 1, 2)  # the day most bookings are made on


def at(hour, minute=0, day=DAY):
    return datetime.combine(day, time(hour, minute))


class SalonWorld(unittest.TestCase):
    """A small salon: two stylists, a 60-minute colour service, a 30-minute cut."""

    database_uri = "sqlite:///:memory:"
    engine_options = {}

    def setUp(self):
        self.app = create_app({
            "TESTING": True,
            "SECRET_KEY": "isolated-booking-test",
            "SQLALCHEMY_DATABASE_URI": self.database_uri,
            "SQLALCHEMY_ENGINE_OPTIONS": self.engine_options,
        })
        context = self.app.app_context()
        context.push()
        self.addCleanup(context.pop)
        self.addCleanup(db.engine.dispose)
        self.addCleanup(db.session.remove)
        clock = mock.patch("availability.current_time", return_value=NOW)
        clock.start()
        self.addCleanup(clock.stop)
        db.create_all()
        self.build_world()

    def build_world(self):
        self.c1 = self.user("Customer One", "customer")
        self.c2 = self.user("Customer Two", "customer")
        self.s1 = self.user("Stylist One", "stylist")
        self.s2 = self.user("Stylist Two", "stylist")
        self.colour = Service(
            name="Colouring", description="", price_minor=6000, duration_minutes=60,
            required_workstation_type="colour",
        )
        self.cut = Service(
            name="Haircut", description="", price_minor=2500, duration_minutes=30,
            required_workstation_type="chair",
        )
        self.colour1 = Workstation(label="Colour 1", workstation_type="colour")
        self.chair1 = Workstation(label="Chair 1", workstation_type="chair")
        db.session.add_all([self.colour, self.cut, self.colour1, self.chair1])
        db.session.flush()
        for stylist in (self.s1, self.s2):
            db.session.add_all([
                StaffService(stylist_id=stylist.id, service_id=self.colour.id),
                StaffService(stylist_id=stylist.id, service_id=self.cut.id),
                WorkingShift(stylist_id=stylist.id, work_date=DAY, start_time=time(9), end_time=time(17)),
            ])
        db.session.add(Unavailability(
            stylist_id=self.s1.id, starts_at=at(12), ends_at=at(13), reason="break",
        ))
        db.session.commit()

    def user(self, name, role):
        user = User(name=name, email=name.lower().replace(" ", ".") + "@example.com", role=role)
        user.password_hash = "not-a-real-hash"  # these tests never sign in with a password
        db.session.add(user)
        db.session.flush()
        return user

    def book(self, customer, stylist, service, hour, minute=0, day=DAY):
        return booking.create_appointment(
            customer.id, service.id, stylist.id, day, time(hour, minute)
        )

    def cells(self, appointment_id):
        return db.session.scalars(
            select(SlotAllocation.slot_start)
            .where(SlotAllocation.appointment_id == appointment_id)
            .order_by(SlotAllocation.slot_start)
        ).all()

    def count(self, model):
        return db.session.scalar(select(func.count()).select_from(model))

    def slots(self, service, stylist, day=DAY):
        times, reason = availability.available_slots(service.id, stylist.id, day)
        return [value.strftime("%H:%M") for value in times], reason


class SlotCalculationTests(SalonWorld):
    def test_slots_respect_shift_break_and_duration(self):
        times, reason = self.slots(self.colour, self.s1)
        self.assertIsNone(reason)
        # Shift 09:00-17:00, break 12:00-13:00, 60 minutes long, 15-minute grid.
        expected = (
            [f"{h:02d}:{m:02d}" for h in range(9, 11) for m in (0, 15, 30, 45)] + ["11:00"]
            + [f"{h:02d}:{m:02d}" for h in range(13, 16) for m in (0, 15, 30, 45)] + ["16:00"]
        )
        self.assertEqual(times, expected)

    def test_booked_cells_block_overlaps_but_allow_back_to_back(self):
        self.book(self.c1, self.s1, self.colour, 10)
        times, _ = self.slots(self.colour, self.s1)
        # 09:15 would end at 10:15 (overlap); 09:00 ends at 10:00 and 11:00 starts at 11:00.
        self.assertIn("09:00", times)
        self.assertIn("11:00", times)
        for blocked in ("09:15", "09:30", "09:45", "10:00", "10:15", "10:30", "10:45"):
            self.assertNotIn(blocked, times)

    def test_no_shift_reports_no_shift(self):  # V-12
        self.assertEqual(self.slots(self.colour, self.s1, DAY + timedelta(days=1)), ([], "NO_SHIFT"))

    def test_missing_skill_reports_not_qualified(self):
        db.session.execute(delete(StaffService).where(
            StaffService.stylist_id == self.s2.id, StaffService.service_id == self.colour.id
        ))
        db.session.commit()
        self.assertEqual(self.slots(self.colour, self.s2), ([], "NOT_QUALIFIED"))

    def test_no_compatible_station_in_use_reports_no_workstation(self):  # V-13
        self.colour1.is_active = False
        db.session.commit()
        self.assertEqual(self.slots(self.colour, self.s1), ([], "NO_WORKSTATION"))

    def test_busy_compatible_station_reports_no_workstation(self):
        # The only colour station is used by the other stylist all day.
        for hour in range(9, 17):
            self.book(self.c2, self.s2, self.colour, hour)
        self.assertEqual(self.slots(self.colour, self.s1), ([], "NO_WORKSTATION"))

    def test_stylist_fully_booked_reports_all_taken(self):
        for hour in (9, 10, 11, 13, 14, 15, 16):
            self.book(self.c1, self.s1, self.cut, hour)
            self.book(self.c1, self.s1, self.cut, hour, 30)
        self.assertEqual(self.slots(self.cut, self.s1), ([], "ALL_TAKEN"))

    def test_today_hides_starts_that_are_not_later_than_now(self):
        db.session.add(WorkingShift(
            stylist_id=self.s2.id, work_date=NOW.date(), start_time=time(8), end_time=time(10)
        ))
        db.session.commit()
        with mock.patch("availability.current_time", return_value=datetime(2030, 1, 1, 8, 15)):
            times, reason = availability.available_slots(self.cut.id, self.s2.id, NOW.date())
        # 08:15 is not later than now, so the first start is 08:30; 09:30 is the last that fits.
        self.assertEqual([t.strftime("%H:%M") for t in times], ["08:30", "08:45", "09:00", "09:15", "09:30"])
        self.assertIsNone(reason)

    def test_off_grid_shift_start_rounds_up_to_the_grid(self):
        db.session.execute(delete(WorkingShift).where(WorkingShift.stylist_id == self.s2.id))
        db.session.add(WorkingShift(
            stylist_id=self.s2.id, work_date=DAY, start_time=time(9, 10), end_time=time(10, 30)
        ))
        db.session.commit()
        self.assertEqual(self.slots(self.cut, self.s2)[0], ["09:15", "09:30", "09:45", "10:00"])

    def test_unknown_or_inactive_service_and_stylist_are_not_found(self):
        self.cut.is_active = False
        db.session.commit()
        with self.assertRaises(NotFound):
            availability.available_slots(self.cut.id, self.s1.id, DAY)
        with self.assertRaises(NotFound):
            availability.available_slots(self.colour.id, self.c1.id, DAY)  # a customer, not a stylist
        with self.assertRaises(NotFound):
            availability.available_slots(9999, self.s1.id, DAY)


class CreateAppointmentTests(SalonWorld):
    def test_create_freezes_price_and_end_and_takes_four_cells(self):  # V-21
        appointment = self.book(self.c1, self.s1, self.colour, 10)
        self.assertEqual(appointment.status, "confirmed")
        self.assertEqual(appointment.starts_at, at(10))
        self.assertEqual(appointment.ends_at, at(11))
        self.assertEqual(appointment.agreed_price_minor, 6000)
        self.assertEqual(appointment.workstation_id, self.colour1.id)
        self.assertEqual(self.cells(appointment.id), [at(10) + i * timedelta(minutes=15) for i in range(4)])

    def test_input_rules_raise_validation_failed(self):
        cases = {
            "misaligned start (V-14)": (DAY, time(9, 10)),
            "start in the past (V-15)": (NOW.date(), time(7, 45)),
            "before the shift opens": (DAY, time(8, 0)),
            "ends after the shift closes": (DAY, time(16, 15)),
            "overlaps a break": (DAY, time(11, 30)),
        }
        for label, (day, start) in cases.items():
            with self.subTest(label), self.assertRaises(booking.ValidationFailed) as caught:
                booking.create_appointment(self.c1.id, self.colour.id, self.s1.id, day, start)
            self.assertEqual(caught.exception.error_code, "VALIDATION_FAILED")
        self.assertEqual(self.count(Appointment), 0)
        self.assertEqual(self.count(SlotAllocation), 0)

    def test_stylist_without_the_skill_is_rejected(self):
        db.session.execute(delete(StaffService).where(StaffService.stylist_id == self.s1.id))
        db.session.commit()
        with self.assertRaises(booking.ValidationFailed) as caught:
            self.book(self.c1, self.s1, self.colour, 10)
        self.assertIn("stylist_id", caught.exception.fields)

    def test_no_workstation_of_the_required_type_is_rejected(self):
        self.colour1.is_active = False
        db.session.commit()
        with self.assertRaises(booking.ValidationFailed):
            self.book(self.c1, self.s1, self.colour, 10)

    def test_sixty_day_window_includes_day_sixty_and_rejects_sixty_one(self):  # V-40, V-41
        for offset in (60, 61):
            db.session.add(WorkingShift(
                stylist_id=self.s1.id, work_date=NOW.date() + timedelta(days=offset),
                start_time=time(9), end_time=time(17),
            ))
        db.session.commit()
        accepted = self.book(self.c1, self.s1, self.cut, 10, day=NOW.date() + timedelta(days=60))
        self.assertEqual(accepted.status, "confirmed")
        with self.assertRaises(booking.DateOutOfRange) as caught:
            self.book(self.c1, self.s1, self.cut, 10, day=NOW.date() + timedelta(days=61))
        self.assertEqual((caught.exception.error_code, caught.exception.http_status), ("DATE_OUT_OF_RANGE", 400))

    def test_unknown_or_inactive_targets_are_not_found(self):
        with self.assertRaises(NotFound):
            booking.create_appointment(self.c1.id, 9999, self.s1.id, DAY, time(10))
        with self.assertRaises(NotFound):
            booking.create_appointment(self.c1.id, self.cut.id, 9999, DAY, time(10))

    def test_only_an_active_customer_can_book(self):
        with self.assertRaises(Forbidden):
            booking.create_appointment(self.s1.id, self.cut.id, self.s2.id, DAY, time(10))

    def test_back_to_back_bookings_both_succeed(self):  # V-16
        first = self.book(self.c1, self.s1, self.colour, 10)
        second = self.book(self.c2, self.s1, self.colour, 11)
        self.assertEqual(first.ends_at, second.starts_at)
        self.assertEqual(self.count(SlotAllocation), 8)

    def test_partial_overlap_is_slot_taken(self):  # V-17, T3
        self.book(self.c1, self.s1, self.colour, 10)
        with self.assertRaises(booking.SlotTaken):
            self.book(self.c2, self.s1, self.colour, 10, 30)
        self.assertEqual((self.count(Appointment), self.count(SlotAllocation)), (1, 4))

    def test_same_stylist_same_time_keeps_the_first_booking(self):  # V-18
        first = self.book(self.c1, self.s1, self.cut, 10)
        with self.assertRaises(booking.SlotTaken) as caught:
            self.book(self.c2, self.s1, self.cut, 10)
        self.assertEqual((caught.exception.error_code, caught.exception.http_status), ("SLOT_TAKEN", 409))
        self.assertEqual(db.session.get(Appointment, first.id).status, "confirmed")

    def test_same_only_workstation_different_stylists_is_slot_taken(self):  # V-19, T2
        self.book(self.c1, self.s1, self.colour, 10)
        with self.assertRaises(booking.SlotTaken):
            self.book(self.c2, self.s2, self.colour, 10)
        self.assertEqual(self.count(Appointment), 1)

    def test_a_second_station_lets_two_stylists_work_in_parallel(self):
        second = Workstation(label="Colour 2", workstation_type="colour")
        db.session.add(second)
        db.session.commit()
        first_booking = self.book(self.c1, self.s1, self.colour, 10)
        second_booking = self.book(self.c2, self.s2, self.colour, 10)
        self.assertNotEqual(first_booking.workstation_id, second_booking.workstation_id)

    def test_failed_insert_leaves_no_rows_behind(self):  # V-20, T5
        # A 30-minute cut holds 10:30 and 10:45 for the stylist ...
        self.book(self.c1, self.s1, self.cut, 10, 30)
        before = (self.count(Appointment), self.count(SlotAllocation))
        # ... so the 10:00 colouring gets its first two cells in, then fails on the third.
        with self.assertRaises(booking.SlotTaken):
            self.book(self.c2, self.s1, self.colour, 10)
        self.assertEqual((self.count(Appointment), self.count(SlotAllocation)), before)


class CancelTests(SalonWorld):
    def test_cancel_keeps_history_and_frees_the_time(self):  # V-24, T7
        appointment = self.book(self.c1, self.s1, self.colour, 10)
        appointment_id = appointment.id
        booking.cancel(appointment_id)
        cancelled = db.session.get(Appointment, appointment_id)
        self.assertEqual(cancelled.status, "cancelled")
        self.assertEqual((cancelled.starts_at, cancelled.ends_at, cancelled.agreed_price_minor),
                         (at(10), at(11), 6000))
        self.assertEqual(self.cells(appointment_id), [])
        self.assertIn("10:00", self.slots(self.colour, self.s1)[0])
        self.book(self.c2, self.s1, self.colour, 10)  # the slot really is free again

    def test_second_cancel_is_invalid_state(self):  # V-25
        appointment = self.book(self.c1, self.s1, self.colour, 10)
        booking.cancel(appointment.id)
        with self.assertRaises(booking.InvalidState) as caught:
            booking.cancel(appointment.id)
        self.assertEqual(caught.exception.error_code, "INVALID_STATE")

    def test_two_hour_window(self):  # V-38 and its boundary
        appointment = self.book(self.c1, self.s1, self.colour, 10)
        # 08:00 is exactly two hours before 10:00: the boundary is already closed.
        with mock.patch("availability.current_time", return_value=at(8)):
            with self.assertRaises(booking.CancelWindowClosed) as caught:
                booking.cancel(appointment.id)
        self.assertEqual((caught.exception.error_code, caught.exception.http_status),
                         ("CANCEL_WINDOW_CLOSED", 409))
        self.assertEqual(db.session.get(Appointment, appointment.id).status, "confirmed")
        self.assertEqual(len(self.cells(appointment.id)), 4)
        # One minute earlier it is still allowed.
        with mock.patch("availability.current_time", return_value=at(7, 59)):
            booking.cancel(appointment.id)
        self.assertEqual(db.session.get(Appointment, appointment.id).status, "cancelled")

    def test_finished_appointments_cannot_be_cancelled(self):
        appointment = self.book(self.c1, self.s1, self.colour, 10)
        appointment.status = "completed"
        db.session.commit()
        with self.assertRaises(booking.InvalidState):
            booking.cancel(appointment.id)

    def test_unknown_appointment_is_not_found(self):
        with self.assertRaises(NotFound):
            booking.cancel(9999)

    def test_only_the_owner_may_cancel(self):  # V-08 (service-layer part)
        appointment = self.book(self.c1, self.s1, self.colour, 10)
        for outsider, expected in ((self.c2, Forbidden), (self.s1, Forbidden)):
            with self.app.test_request_context():
                login_user(db.session.get(User, outsider.id))
                with self.assertRaises(expected):
                    booking.cancel(appointment.id)
        self.assertEqual(db.session.get(Appointment, appointment.id).status, "confirmed")
        with self.app.test_request_context():
            login_user(db.session.get(User, self.c1.id))
            booking.cancel(appointment.id)
        self.assertEqual(db.session.get(Appointment, appointment.id).status, "cancelled")


class RescheduleTests(SalonWorld):
    def test_reschedule_moves_booking_and_keeps_price_and_length(self):  # V-28
        appointment = self.book(self.c1, self.s1, self.colour, 10)
        self.colour.price_minor = 9900
        self.colour.duration_minutes = 120
        db.session.commit()
        moved = booking.reschedule(appointment.id, DAY, time(14))
        self.assertEqual((moved.starts_at, moved.ends_at), (at(14), at(15)))
        self.assertEqual(moved.agreed_price_minor, 6000)
        self.assertEqual(self.cells(moved.id), [at(14) + i * timedelta(minutes=15) for i in range(4)])
        self.assertEqual(self.count(SlotAllocation), 4)

    def test_moving_by_one_cell_is_not_blocked_by_its_own_old_cells(self):
        appointment = self.book(self.c1, self.s1, self.colour, 10)
        moved = booking.reschedule(appointment.id, DAY, time(10, 15))
        self.assertEqual(moved.starts_at, at(10, 15))
        self.assertEqual(self.count(SlotAllocation), 4)

    def test_failed_reschedule_leaves_original_untouched(self):  # V-27, T6
        mine = self.book(self.c1, self.s1, self.colour, 10)
        self.book(self.c2, self.s1, self.colour, 14)
        before = self.cells(mine.id)
        with self.assertRaises(booking.SlotTaken):
            booking.reschedule(mine.id, DAY, time(14, 30))
        unchanged = db.session.get(Appointment, mine.id)
        self.assertEqual((unchanged.starts_at, unchanged.ends_at, unchanged.status),
                         (at(10), at(11), "confirmed"))
        self.assertEqual(self.cells(mine.id), before)
        self.assertEqual(self.count(SlotAllocation), 8)

    def test_station_conflict_with_another_stylist_also_restores_everything(self):
        mine = self.book(self.c1, self.s1, self.colour, 10)
        self.book(self.c2, self.s2, self.colour, 14)  # holds the only colour station at 14:00
        with self.assertRaises(booking.SlotTaken):
            booking.reschedule(mine.id, DAY, time(14))
        self.assertEqual(self.cells(mine.id), [at(10) + i * timedelta(minutes=15) for i in range(4)])

    def test_completed_appointment_cannot_move(self):  # V-26
        appointment = self.book(self.c1, self.s1, self.colour, 10)
        appointment.status = "completed"
        db.session.commit()
        with self.assertRaises(booking.InvalidState):
            booking.reschedule(appointment.id, DAY, time(14))

    def test_started_appointment_cannot_move(self):
        appointment = self.book(self.c1, self.s1, self.colour, 10)
        with mock.patch("availability.current_time", return_value=at(10, 30)):
            with self.assertRaises(booking.InvalidState):
                booking.reschedule(appointment.id, DAY, time(14))

    def test_reschedule_is_allowed_inside_the_two_hour_window(self):  # V-39
        appointment = self.book(self.c1, self.s1, self.colour, 10)
        with mock.patch("availability.current_time", return_value=at(9)):
            moved = booking.reschedule(appointment.id, DAY, time(14))
        self.assertEqual(moved.starts_at, at(14))

    def test_same_time_is_a_validation_error(self):
        appointment = self.book(self.c1, self.s1, self.colour, 10)
        with self.assertRaises(booking.ValidationFailed):
            booking.reschedule(appointment.id, DAY, time(10))

    def test_new_time_must_respect_shift_break_and_window(self):
        appointment = self.book(self.c1, self.s1, self.colour, 10)
        for label, day, start, error in (
            ("on a break", DAY, time(11, 30), booking.ValidationFailed),
            ("misaligned", DAY, time(14, 5), booking.ValidationFailed),
            ("beyond 60 days", NOW.date() + timedelta(days=61), time(10), booking.DateOutOfRange),
        ):
            with self.subTest(label), self.assertRaises(error):
                booking.reschedule(appointment.id, day, start)
        self.assertEqual(db.session.get(Appointment, appointment.id).starts_at, at(10))

    def test_ownership_is_checked_before_state(self):
        appointment = self.book(self.c1, self.s1, self.colour, 10)
        with self.app.test_request_context():
            login_user(db.session.get(User, self.c2.id))
            with self.assertRaises(Forbidden):
                booking.reschedule(appointment.id, DAY, time(14))

    def test_reschedule_slots_use_original_length_and_free_the_own_cells(self):
        appointment = self.book(self.c1, self.s1, self.colour, 10)
        self.colour.duration_minutes = 30  # later catalogue edit must not matter
        db.session.commit()
        times, reason = availability.available_slots_for_reschedule(appointment.id, DAY)
        names = [t.strftime("%H:%M") for t in times]
        self.assertIsNone(reason)
        self.assertIn("10:15", names)  # own old cells do not block
        self.assertNotIn("11:30", names)  # 60 minutes from 11:30 would hit the break
        self.assertEqual(self.count(SlotAllocation), 4)  # read only


class BlockingAppointmentsTests(SalonWorld):
    def test_selectors_find_only_future_confirmed_bookings(self):
        future = self.book(self.c1, self.s1, self.colour, 10)
        cancelled = self.book(self.c1, self.s1, self.colour, 14)
        booking.cancel(cancelled.id)
        done = self.book(self.c2, self.s2, self.cut, 9)
        done.status = "completed"
        db.session.commit()
        self.assertEqual(availability.blocking_appointments(service_id=self.colour.id), [future.id])
        self.assertEqual(availability.blocking_appointments(workstation_id=self.colour1.id), [future.id])
        self.assertEqual(availability.blocking_appointments(service_id=self.cut.id), [])

    def test_started_appointments_are_ignored(self):
        past = self.book(self.c1, self.s1, self.colour, 10)
        with mock.patch("availability.current_time", return_value=at(10, 30)):
            self.assertEqual(availability.blocking_appointments(service_id=self.colour.id), [])
        self.assertEqual(availability.blocking_appointments(service_id=self.colour.id), [past.id])

    def test_interval_uses_half_open_overlap(self):
        first = self.book(self.c1, self.s1, self.colour, 10)  # 10:00-11:00
        self.book(self.c2, self.s2, self.colour, 14)  # another stylist, never matched
        def blocked(start, end):
            return availability.blocking_appointments(stylist_id=self.s1.id, interval=(start, end))
        self.assertEqual(blocked(at(10, 30), at(12)), [first.id])
        self.assertEqual(blocked(at(9), at(10, 15)), [first.id])
        self.assertEqual(blocked(at(11), at(13)), [])  # touching only
        self.assertEqual(blocked(at(9), at(10)), [])  # touching only

    def test_selectors_combine_and_stay_sorted(self):
        first = self.book(self.c1, self.s1, self.colour, 10)
        second = self.book(self.c2, self.s1, self.cut, 15)
        result = availability.blocking_appointments(
            service_id=self.cut.id, stylist_id=self.s1.id, interval=(at(10), at(11))
        )
        self.assertEqual(result, sorted([first.id, second.id]))

    def test_misuse_raises_value_error(self):
        for arguments in ({}, {"stylist_id": 1}, {"interval": (at(9), at(10))}):
            with self.subTest(arguments), self.assertRaises(ValueError):
                availability.blocking_appointments(**arguments)

    def test_it_never_writes(self):
        self.book(self.c1, self.s1, self.colour, 10)
        before = (self.count(Appointment), self.count(SlotAllocation))
        availability.blocking_appointments(service_id=self.colour.id)
        self.assertEqual((self.count(Appointment), self.count(SlotAllocation)), before)


class SlotsApiTests(SalonWorld):
    """Real HTTP requests against GET /api/slots (spec section 4.2)."""

    def setUp(self):
        super().setUp()
        if "slots_api" not in self.app.blueprints:  # Role B registers it in app.py later
            self.app.register_blueprint(availability.slots_api)
        self.client = self.app.test_client()

    def login(self, user):
        # The test keeps one app context open, so Flask-Login's per-context user
        # cache (g._login_user) would otherwise survive between requests.
        g.pop("_login_user", None)
        with self.client.session_transaction() as session:
            session["_user_id"] = str(user.id)
            session["_fresh"] = True

    def get(self, **params):
        return self.client.get("/api/slots", query_string=params, headers={"Accept": "application/json"})

    def new_mode(self, **overrides):
        params = {"service_id": self.colour.id, "stylist_id": self.s1.id, "date": DAY.isoformat()}
        params.update(overrides)
        return params

    def test_anonymous_gets_401_json_without_next(self):  # V-02
        response = self.get(**self.new_mode())
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["error"], "AUTH_REQUIRED")
        self.assertEqual(response.get_json()["login_url"], "/auth/login")

    def test_staff_and_admin_roles_are_forbidden(self):
        self.login(self.s1)
        response = self.get(**self.new_mode())
        self.assertEqual((response.status_code, response.get_json()["error"]), (403, "FORBIDDEN"))

    def test_new_mode_success_shape(self):
        self.login(self.c1)
        response = self.get(**self.new_mode())
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["date"], DAY.isoformat())
        self.assertIsNone(body["appointment_id"])
        self.assertEqual((body["service_id"], body["stylist_id"], body["duration_minutes"]),
                         (self.colour.id, self.s1.id, 60))
        self.assertEqual(body["slots"][:3], ["09:00", "09:15", "09:30"])
        self.assertIsNone(body["empty_reason"])
        self.assertEqual(set(body), {
            "date", "appointment_id", "service_id", "stylist_id", "duration_minutes", "slots", "empty_reason",
        })

    def test_empty_day_is_200_with_a_reason(self):  # V-12
        self.login(self.c1)
        response = self.get(**self.new_mode(date=(DAY + timedelta(days=1)).isoformat()))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["slots"], [])
        self.assertEqual(response.get_json()["empty_reason"], "NO_SHIFT")

    def test_chair_free_but_colour_unavailable_reports_no_workstation(self):  # V-13
        self.colour1.is_active = False
        db.session.commit()
        self.login(self.c1)
        body = self.get(**self.new_mode()).get_json()
        self.assertEqual((body["slots"], body["empty_reason"]), ([], "NO_WORKSTATION"))

    def test_mixed_modes_and_missing_parameters_are_400(self):  # V-10
        self.login(self.c1)
        appointment = self.book(self.c1, self.s1, self.colour, 10)
        mixed = self.get(appointment_id=appointment.id, service_id=self.colour.id, date=DAY.isoformat())
        self.assertEqual((mixed.status_code, mixed.get_json()["error"]), (400, "VALIDATION_FAILED"))
        both = self.get(**self.new_mode(appointment_id=appointment.id))
        self.assertEqual(both.status_code, 400)
        missing = self.get(service_id=self.colour.id, date=DAY.isoformat())
        self.assertEqual(missing.status_code, 400)
        self.assertIn("stylist_id", missing.get_json()["fields"])
        self.assertEqual(self.get().status_code, 400)

    def test_malformed_values_are_400(self):
        self.login(self.c1)
        for params in (
            self.new_mode(service_id="abc"), self.new_mode(stylist_id="-1"),
            self.new_mode(service_id="1.5"), self.new_mode(service_id="9" * 25),
            self.new_mode(date="2030-1-2"), self.new_mode(date="2030-02-30"),
            self.new_mode(date="20300102"), self.new_mode(date=""),
        ):
            with self.subTest(params):
                response = self.get(**params)
                self.assertEqual((response.status_code, response.get_json()["error"]), (400, "VALIDATION_FAILED"))

    def test_date_window(self):  # V-40, V-41
        self.login(self.c1)
        past = self.get(**self.new_mode(date="2029-12-31"))
        self.assertEqual((past.status_code, past.get_json()["error"]), (400, "VALIDATION_FAILED"))
        edge = (NOW.date() + timedelta(days=60)).isoformat()
        self.assertEqual(self.get(**self.new_mode(date=edge)).status_code, 200)
        beyond = self.get(**self.new_mode(date=(NOW.date() + timedelta(days=61)).isoformat()))
        self.assertEqual((beyond.status_code, beyond.get_json()["error"]), (400, "DATE_OUT_OF_RANGE"))

    def test_unknown_service_or_stylist_is_404(self):
        self.login(self.c1)
        for params in (self.new_mode(service_id=9999), self.new_mode(stylist_id=9999),
                       self.new_mode(stylist_id=self.c2.id)):
            with self.subTest(params):
                response = self.get(**params)
                self.assertEqual((response.status_code, response.get_json()["error"]), (404, "NOT_FOUND"))

    def test_reschedule_mode_returns_derived_values_and_own_cells_are_free(self):
        appointment = self.book(self.c1, self.s1, self.colour, 10)
        self.login(self.c1)
        response = self.get(appointment_id=appointment.id, date=DAY.isoformat())
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["appointment_id"], appointment.id)
        self.assertEqual((body["service_id"], body["stylist_id"], body["duration_minutes"]),
                         (self.colour.id, self.s1.id, 60))
        self.assertIn("10:00", body["slots"])  # its own old time is offered again

    def test_reschedule_mode_rejects_finished_bookings_and_strangers(self):  # V-11
        appointment = self.book(self.c1, self.s1, self.colour, 10)
        self.login(self.c2)
        stranger = self.get(appointment_id=appointment.id, date=DAY.isoformat())
        self.assertEqual((stranger.status_code, stranger.get_json()["error"]), (403, "FORBIDDEN"))
        self.assertEqual(self.get(appointment_id=9999, date=DAY.isoformat()).status_code, 404)
        appointment.status = "completed"
        db.session.commit()
        self.login(self.c1)
        finished = self.get(appointment_id=appointment.id, date=DAY.isoformat())
        self.assertEqual((finished.status_code, finished.get_json()["error"]), (409, "INVALID_STATE"))

    def test_api_is_read_only(self):
        self.login(self.c1)
        self.book(self.c1, self.s1, self.colour, 10)
        before = (self.count(Appointment), self.count(SlotAllocation))
        self.get(**self.new_mode())
        self.assertEqual((self.count(Appointment), self.count(SlotAllocation)), before)


# ---------------------------------------------------------------------------
# Concurrency (T8, V-22, V-23).  A file database is needed so that every thread
# has its own connection; the shared in-memory database would hide the race.
# ---------------------------------------------------------------------------

class ConcurrencyTests(SalonWorld):
    THREADS = 20
    engine_options = {"pool_size": 40, "max_overflow": 0}

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.database_uri = "sqlite:///" + str(Path(self.folder.name, "race.sqlite3"))
        super().setUp()

    def build_world(self):
        super().build_world()
        self.customers = [self.user(f"Racer {index}", "customer") for index in range(self.THREADS)]
        db.session.commit()
        self.customer_ids = [customer.id for customer in self.customers]
        self.colour_id, self.s1_id, self.s2_id = self.colour.id, self.s1.id, self.s2.id

    def race(self, jobs):
        """Run ``jobs`` (callables) at the same moment; return their outcomes.

        Every thread first picks its workstation and then waits at a barrier, so
        all of them have passed the application-level check before any of them
        writes.  Only the unique constraints can then separate the winners.
        """
        barrier = threading.Barrier(len(jobs))
        real_pick = availability.free_workstation

        def gated_pick(*args, **kwargs):
            choice = real_pick(*args, **kwargs)
            barrier.wait(timeout=30)
            return choice

        outcomes = []

        def run(job):
            with self.app.app_context():
                try:
                    job()
                    outcomes.append("ok")
                except booking.SlotTaken:
                    outcomes.append("conflict")
                except Exception as error:  # a real failure must be visible
                    outcomes.append(f"error: {type(error).__name__}: {error}")
                finally:
                    db.session.remove()

        with mock.patch("availability.free_workstation", gated_pick):
            threads = [threading.Thread(target=run, args=(job,)) for job in jobs]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=60)
        return outcomes

    def same_slot_jobs(self):
        return [
            (lambda cid=cid: booking.create_appointment(cid, self.colour_id, self.s1_id, DAY, time(10)))
            for cid in self.customer_ids
        ]

    def test_twenty_simultaneous_requests_one_winner(self):  # T8, V-22
        outcomes = self.race(self.same_slot_jobs())
        self.assertEqual(outcomes.count("ok"), 1, outcomes)
        self.assertEqual(outcomes.count("conflict"), self.THREADS - 1, outcomes)
        db.session.expire_all()
        self.assertEqual(self.count(Appointment), 1)
        self.assertEqual(self.count(SlotAllocation), 4)

    def test_two_stylists_racing_for_the_only_station_one_winner(self):  # T2
        jobs = [
            (lambda cid=cid, sid=sid: booking.create_appointment(cid, self.colour_id, sid, DAY, time(10)))
            for cid, sid in zip(self.customer_ids, [self.s1_id, self.s2_id] * (self.THREADS // 2))
        ]
        outcomes = self.race(jobs)
        self.assertEqual(outcomes.count("ok"), 1, outcomes)
        self.assertEqual(outcomes.count("conflict"), self.THREADS - 1, outcomes)
        db.session.expire_all()
        self.assertEqual(self.count(SlotAllocation), 4)

    def test_overlapping_starts_race_leaves_a_consistent_schedule(self):
        starts = [time(10), time(10, 15), time(10, 30), time(10, 45)] * (self.THREADS // 4)
        jobs = [
            (lambda cid=cid, start=start: booking.create_appointment(
                cid, self.colour_id, self.s1_id, DAY, start))
            for cid, start in zip(self.customer_ids, starts)
        ]
        outcomes = self.race(jobs)
        self.assertFalse([o for o in outcomes if o.startswith("error")], outcomes)
        winners = outcomes.count("ok")
        self.assertGreaterEqual(winners, 1)
        db.session.expire_all()
        # Every winner owns exactly four distinct cells and no cell has two owners.
        self.assertEqual(self.count(SlotAllocation), 4 * winners)
        duplicates = db.session.execute(
            select(SlotAllocation.slot_start).group_by(SlotAllocation.slot_start)
            .having(func.count() > 1)
        ).all()
        self.assertEqual(duplicates, [])

    def test_control_without_the_constraints_double_books(self):  # V-23
        # Rebuild slot_allocation WITHOUT the two unique constraints (this test's
        # private database only), then repeat the same race.
        db.session.execute(text("DROP TABLE slot_allocation"))
        db.session.execute(text(
            'CREATE TABLE slot_allocation (id INTEGER NOT NULL PRIMARY KEY, '
            'appointment_id INTEGER NOT NULL REFERENCES appointment (id), '
            'stylist_id INTEGER NOT NULL REFERENCES "user" (id), '
            'workstation_id INTEGER NOT NULL REFERENCES workstation (id), '
            'slot_start DATETIME NOT NULL)'
        ))
        db.session.commit()
        outcomes = self.race(self.same_slot_jobs())
        self.assertFalse([o for o in outcomes if o.startswith("error")], outcomes)
        self.assertGreater(outcomes.count("ok"), 1, "without the constraints several bookings succeed")
        db.session.expire_all()
        self.assertGreater(self.count(Appointment), 1)


if __name__ == "__main__":
    unittest.main()
