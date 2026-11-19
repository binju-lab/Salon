from functools import wraps
from urllib.parse import unquote, urlsplit

from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user
from flask_wtf import FlaskForm
from sqlalchemy.exc import IntegrityError
from wtforms import EmailField, PasswordField, StringField
from wtforms.validators import DataRequired, Email, Length

from models import User, db

auth = Blueprint("auth", __name__, url_prefix="/auth")


def _normalize_email(value):
    return value.strip().lower() if value else value


class AccountForm(FlaskForm):
    name = StringField("Name", validators=[DataRequired(), Length(max=100)])
    email = EmailField(
        "Email",
        filters=[_normalize_email],
        validators=[DataRequired(), Length(max=254), Email()],
    )
    password = PasswordField("Password", validators=[DataRequired(), Length(min=8, max=128)])


class LoginForm(FlaskForm):
    email = EmailField(
        "Email",
        filters=[_normalize_email],
        validators=[DataRequired(), Length(max=254)],
    )
    password = PasswordField("Password", validators=[DataRequired(), Length(max=128)])


def roles_required(*allowed_roles):
    """Guard a route by role. Apply record-level checks inside the route."""
    def decorate(view):
        @wraps(view)
        @login_required
        def protected_view(*args, **kwargs):
            if current_user.role not in allowed_roles:
                abort(403)
            return view(*args, **kwargs)

        return protected_view

    return decorate


def require_appointment_access(appointment):
    """Check who may access a record. Routes still restrict the action and status."""
    if current_user.is_authenticated:
        if current_user.role == "admin":
            return
        if current_user.role == "customer" and current_user.id == appointment.customer_id:
            return
        if current_user.role == "stylist" and current_user.id == appointment.stylist_id:
            return
    abort(403)


def _save_account(form, role):
    user = User(name=form.name.data.strip(), email=form.email.data, role=role)
    user.set_password(form.password.data)
    db.session.add(user)
    try:
        db.session.commit()
    except IntegrityError:
        # The unique email constraint also handles simultaneous registrations.
        db.session.rollback()
        existing_id = db.session.scalar(db.select(User.id).where(User.email == user.email))
        if existing_id is None:
            raise
        form.email.errors.append("That email is already in use.")
        return False
    return True


@auth.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("index"))
    form = AccountForm()
    if form.validate_on_submit() and _save_account(form, "customer"):
        flash("Account created. You can now sign in.")
        return redirect(url_for("auth.login"))
    return render_template("auth/form.html", form=form, title="Create customer account")


def is_safe_next(target):
    """Allow only a local absolute path for the post-login redirect.

    Decode percent escapes before checking so encoded protocol-relative or
    backslash-based URLs cannot bypass the same-origin rule.
    """
    if not target:
        return False
    decoded = target
    for _ in range(3):
        decoded = unquote(decoded)
    if any(ord(char) < 32 or ord(char) == 127 for char in decoded) or "\\" in decoded:
        return False
    try:
        parts = urlsplit(decoded)
    except ValueError:
        return False
    return (
        not parts.scheme
        and not parts.netloc
        and parts.path.startswith("/")
        and not parts.path.startswith("//")
        and ".." not in parts.path.split("/")
    )


def _login_destination():
    target = request.args.get("next")
    return target if is_safe_next(target) else url_for("index")


@auth.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(_login_destination())
    form = LoginForm()
    if form.validate_on_submit():
        user = db.session.scalar(db.select(User).where(User.email == form.email.data))
        if user is not None and user.is_active and user.check_password(form.password.data):
            session.clear()
            login_user(user)
            return redirect(_login_destination())
        flash("The email or password is incorrect.")
    # The form has no explicit action, so a safe ?next=... query survives a
    # validation error and is checked again after successful authentication.
    return render_template("auth/form.html", form=form, title="Sign in", is_login=True)


@auth.post("/logout")
@login_required
def logout():
    logout_user()
    session.clear()
    return redirect(url_for("index"))


@auth.route("/staff", methods=["GET", "POST"])
@roles_required("admin")
def create_staff():
    form = AccountForm()
    if form.validate_on_submit() and _save_account(form, "stylist"):
        flash("Stylist account created.")
        return redirect(url_for("auth.create_staff"))
    return render_template("auth/form.html", form=form, title="Create stylist account")
