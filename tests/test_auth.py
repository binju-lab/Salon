"""Request-level checks for Role B's account and access rules."""

from html.parser import HTMLParser
import unittest
from urllib.parse import parse_qs, urlencode, urlsplit

from flask import abort
from flask_login import current_user
from sqlalchemy import select

from app import create_app
from auth import require_appointment_access, roles_required
from models import Appointment, User, db


DEMO_PASSWORD = "CourseTestOnly!42"


class CsrfFieldParser(HTMLParser):
    token = None

    def handle_starttag(self, tag, attrs):
        if tag == "input":
            fields = dict(attrs)
            if fields.get("name") == "csrf_token":
                self.token = fields.get("value")


class AuthenticationTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            "TESTING": True,
            "SECRET_KEY": "isolated-auth-test",
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        })
        with self.app.app_context():
            db.create_all()
            self.addCleanup(db.engine.dispose)

        @self.app.get("/_test/session")
        @roles_required("customer", "stylist", "admin")
        def session_view():
            return {"role": current_user.role}

        @self.app.get("/_test/appointment")
        @roles_required("customer", "stylist", "admin")
        def appointment_view():
            # Test harness for the shared record permission check used by future routes.
            require_appointment_access(self.appointment)
            return "", 204

        @self.app.get("/_test/json/protected")
        @roles_required("customer")
        def json_protected_view():
            return {"role": current_user.role}

        @self.app.post("/_test/json/write")
        @roles_required("customer")
        def json_write_view():
            return {"saved": True}

        @self.app.get("/_test/json/conflict")
        def json_conflict_view():
            abort(409)

        @self.app.get("/_test/json/server-error")
        def json_server_error_view():
            abort(500)

        self.client = self.app.test_client()

    def _add_user(self, name, role):
        email = name.lower().replace(" ", ".") + "@example.com"
        with self.app.app_context():
            user = User(name=name, email=email, role=role)
            user.set_password(DEMO_PASSWORD)
            db.session.add(user)
            db.session.commit()
            return user.id, email

    def _post_form(self, path, *, form_path=None, **fields):
        page = self.client.get(form_path or path)
        self.assertEqual(page.status_code, 200)
        parser = CsrfFieldParser()
        parser.feed(page.get_data(as_text=True))
        self.assertTrue(parser.token, f"Missing CSRF form field on {form_path or path}")
        return self.client.post(path, data={"csrf_token": parser.token, **fields})

    def _login(self, email, password=DEMO_PASSWORD):
        return self._post_form("/auth/login", email=email, password=password)

    def test_registration_always_creates_customer_and_login_and_logout_work(self):
        email = "new.customer@example.com"
        registration = self._post_form(
            "/auth/register", name="New Customer", email="NEW.CUSTOMER@example.com",
            password=DEMO_PASSWORD, role="admin",
        )
        self.assertEqual(registration.status_code, 302)
        with self.app.app_context():
            user = db.session.scalars(select(User)).one()
            self.assertEqual(user.email, email)
            self.assertEqual(user.role, "customer")
            self.assertNotEqual(user.password_hash, DEMO_PASSWORD)
            self.assertTrue(user.check_password(DEMO_PASSWORD))

        self.assertEqual(self._login(email, "wrong-password").status_code, 200)
        self.assertEqual(self.client.get("/_test/session").status_code, 302)
        self.assertEqual(self._login(email).status_code, 302)
        self.assertEqual(self.client.get("/_test/session").get_json(), {"role": "customer"})

        self.assertEqual(self.client.get("/auth/logout").status_code, 405)
        self.assertEqual(self._post_form("/auth/logout", form_path="/").status_code, 302)
        self.assertEqual(self.client.get("/_test/session").status_code, 302)

    def test_duplicate_registration_preserves_existing_user(self):
        user_id, email = self._add_user("Original", "customer")
        response = self._post_form(
            "/auth/register", name="Replacement", email=email.upper(), password=DEMO_PASSWORD
        )
        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            user = db.session.scalars(select(User)).one()
            self.assertEqual((user.id, user.name), (user_id, "Original"))

    def test_missing_and_invalid_csrf_tokens_are_rejected(self):
        _, email = self._add_user("Customer", "customer")
        login_data = {"email": email, "password": DEMO_PASSWORD}
        self.assertEqual(self.client.post("/auth/login", data=login_data).status_code, 400)
        self.assertEqual(
            self.client.post("/auth/login", data={**login_data, "csrf_token": "invalid"}).status_code,
            400,
        )
        self.assertEqual(self.client.get("/_test/session").status_code, 302)

        self.assertEqual(self._login(email).status_code, 302)
        self.assertEqual(self.client.post("/auth/logout").status_code, 400)
        self.assertEqual(self.client.get("/_test/session").status_code, 200)

    def test_only_admin_can_create_staff_account(self):
        _, customer_email = self._add_user("Customer", "customer")
        _, admin_email = self._add_user("Admin", "admin")
        staff_email = "new.stylist@example.com"
        staff_data = {
            "name": "New Stylist", "email": staff_email, "password": DEMO_PASSWORD, "role": "admin",
        }
        self.assertEqual(self.client.get("/auth/staff").status_code, 302)
        self.assertEqual(self._login(customer_email).status_code, 302)
        self.assertEqual(self.client.get("/auth/staff").status_code, 403)
        self.assertEqual(self._post_form("/auth/staff", form_path="/", **staff_data).status_code, 403)
        with self.app.app_context():
            self.assertIsNone(db.session.scalar(select(User).where(User.email == staff_email)))

        self.client = self.app.test_client()
        self.assertEqual(self._login(admin_email).status_code, 302)
        self.assertEqual(self._post_form("/auth/staff", **staff_data).status_code, 302)
        with self.app.app_context():
            self.assertEqual(db.session.scalars(select(User).where(User.email == staff_email)).one().role, "stylist")

    def test_appointment_access_checks_customer_and_stylist_ownership(self):
        customer_id, customer_email = self._add_user("Customer", "customer")
        _, other_customer_email = self._add_user("Other Customer", "customer")
        stylist_id, stylist_email = self._add_user("Stylist", "stylist")
        _, other_stylist_email = self._add_user("Other Stylist", "stylist")
        _, admin_email = self._add_user("Admin", "admin")
        self.appointment = Appointment(customer_id=customer_id, stylist_id=stylist_id)

        for email, status in [
            (customer_email, 204), (other_customer_email, 403),
            (stylist_email, 204), (other_stylist_email, 403),
            (admin_email, 204),
        ]:
            with self.subTest(email=email):
                self.client = self.app.test_client()
                self.assertEqual(self._login(email).status_code, 302)
                self.assertEqual(self.client.get("/_test/appointment").status_code, status)

    def test_deactivation_revokes_session_and_blocks_login(self):
        user_id, email = self._add_user("Customer", "customer")
        self.assertEqual(self._login(email).status_code, 302)
        self.assertEqual(self.client.get("/_test/session").status_code, 200)

        with self.app.app_context():
            db.session.get(User, user_id).is_active = False
            db.session.commit()

        self.assertEqual(self.client.get("/_test/session").status_code, 302)
        self.assertEqual(self._login(email).status_code, 200)
        self.assertEqual(self.client.get("/_test/session").status_code, 302)

    def test_json_authentication_and_csrf_errors_have_stable_contract(self):
        _, email = self._add_user("Json Customer", "customer")
        headers = {"Accept": "application/json"}
        response = self.client.get("/_test/json/protected?from=availability", headers=headers)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.mimetype, "application/json")
        payload = response.get_json()
        self.assertEqual(payload["error"], "AUTH_REQUIRED")
        self.assertIn("message", payload)
        self.assertEqual(urlsplit(payload["login_url"]).path, "/auth/login")
        self.assertEqual(urlsplit(payload["login_url"]).query, "")

        # Use a real login-page token so these writes reach authentication,
        # rather than being rejected by the CSRF middleware first.
        login_page = self.client.get("/auth/login")
        parser = CsrfFieldParser()
        parser.feed(login_page.get_data(as_text=True))
        self.assertTrue(parser.token)
        json_write = self.client.post(
            "/_test/json/write", data={"csrf_token": parser.token}, headers=headers
        )
        self.assertEqual(json_write.status_code, 401)
        self.assertEqual(json_write.get_json()["error"], "AUTH_REQUIRED")
        self.assertEqual(urlsplit(json_write.get_json()["login_url"]).path, "/auth/login")
        self.assertEqual(urlsplit(json_write.get_json()["login_url"]).query, "")

        html_write = self.client.post("/_test/json/write", data={"csrf_token": parser.token})
        self.assertEqual(html_write.status_code, 302)
        self.assertEqual(urlsplit(html_write.headers["Location"]).path, "/auth/login")
        self.assertEqual(urlsplit(html_write.headers["Location"]).query, "")

        self.assertEqual(self._login(email).status_code, 302)
        valid = self.client.get("/_test/json/protected", headers=headers)
        self.assertEqual(valid.status_code, 200)
        self.assertEqual(valid.get_json(), {"role": "customer"})

        csrf = self.client.post("/_test/json/write", data={}, headers=headers)
        self.assertEqual(csrf.status_code, 400)
        self.assertEqual(csrf.mimetype, "application/json")
        self.assertEqual(csrf.get_json(), {
            "error": "CSRF_FAILED",
            "message": "The CSRF token is missing, invalid, or expired.",
            "fields": {"csrf_token": "missing, invalid, or expired"},
        })
        self.assertEqual(self.client.get("/_test/json/protected", headers=headers).status_code, 200)

    def test_json_role_and_record_denials_keep_the_current_403_contract(self):
        customer_id, _ = self._add_user("Owner", "customer")
        _, other_customer_email = self._add_user("Other Json Customer", "customer")
        stylist_id, stylist_email = self._add_user("Json Stylist", "stylist")
        self.appointment = Appointment(customer_id=customer_id, stylist_id=stylist_id)
        headers = {"Accept": "application/json"}

        self.assertEqual(self._login(stylist_email).status_code, 302)
        role_denied = self.client.get("/_test/json/protected", headers=headers)
        self.assertEqual(role_denied.status_code, 403)
        self.assertEqual(role_denied.mimetype, "application/json")
        self.assertEqual(role_denied.get_json()["error"], "FORBIDDEN")

        self.client = self.app.test_client()
        self.assertEqual(self._login(other_customer_email).status_code, 302)
        record_denied = self.client.get("/_test/appointment", headers=headers)
        self.assertEqual(record_denied.status_code, 403)
        self.assertEqual(record_denied.mimetype, "application/json")
        self.assertEqual(record_denied.get_json()["error"], "FORBIDDEN")

        for path, status, code in [
            ("/api/not-implemented", 404, "NOT_FOUND"),
            ("/_test/json/conflict", 409, "CONFLICT"),
            ("/_test/json/server-error", 500, "SERVER_ERROR"),
        ]:
            with self.subTest(path=path):
                response = self.client.get(path, headers=headers)
                self.assertEqual(response.status_code, status)
                self.assertEqual(response.mimetype, "application/json")
                self.assertEqual(response.get_json()["error"], code)
                self.assertIn("message", response.get_json())
                self.assertNotIn("Traceback", response.get_data(as_text=True))

    def test_login_next_redirect_is_limited_to_local_paths(self):
        _, email = self._add_user("Next Customer", "customer")
        protected_get = self.client.get("/_test/session?from=html")
        self.assertEqual(protected_get.status_code, 302)
        login_destination = urlsplit(protected_get.headers["Location"])
        self.assertEqual(login_destination.path, "/auth/login")
        self.assertEqual(
            parse_qs(login_destination.query),
            {"next": ["/_test/session?from=html"]},
        )
        cases = [
            ("/staff/schedule?date=2030-01-02", True),
            ("https://evil.example/", False),
            ("//evil.example/", False),
            ("/\\evil.example", False),
            ("/%2Fevil.example", False),
            ("/%2e%2e//evil.example", False),
        ]
        for target, allowed in cases:
            with self.subTest(target=target):
                self.client = self.app.test_client()
                login_path = "/auth/login?" + urlencode({"next": target})
                response = self._post_form(
                    login_path, form_path=login_path, email=email, password=DEMO_PASSWORD
                )
                self.assertEqual(response.status_code, 302)
                location = urlsplit(response.headers["Location"])
                if allowed:
                    expected = urlsplit(target)
                    self.assertEqual(location.path, expected.path)
                    self.assertEqual(location.query, expected.query)
                else:
                    self.assertEqual(location.path, "/")
                    self.assertNotIn("evil.example", response.headers["Location"])
