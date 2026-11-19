"""Database-level checks for T3/T4/T6/T7 before Role A route integration."""

from datetime import datetime, timedelta
import unittest

from sqlalchemy import delete, func, inspect, select
from sqlalchemy.exc import IntegrityError

from app import create_app
from models import Appointment, Service, SlotAllocation, User, Workstation, db


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
            booking = db.session.scalars(select(Appointment)).one()
            slots = db.session.scalars(select(SlotAllocation).order_by(SlotAllocation.slot_start)).all()
            self.assertEqual(booking.status, "confirmed")
            self.assertGreater(booking.starts_at, datetime.now())
            self.assertEqual(booking.ends_at, booking.starts_at + timedelta(hours=1))
            self.assertEqual(len(slots), 4)
            for index, slot in enumerate(slots):
                self.assertEqual(slot.appointment_id, booking.id)
                self.assertEqual(slot.stylist_id, booking.stylist_id)
                self.assertEqual(slot.workstation_id, booking.workstation_id)
                self.assertEqual(slot.slot_start, booking.starts_at + index * SLOT_LENGTH)
