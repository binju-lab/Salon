import os
import secrets
from pathlib import Path

from flask import Flask, render_template
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect

from auth import auth
from availability import slots_api  # A 交付：/api/slots
from customer import customer  # C 交付
# from staff import staff  # D 交付
# from admin import admin  # D 交付
from models import User, db
from responses import register_error_handlers, register_login_response_handler
from seed import register_seed_command

login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message = "Please sign in first."
csrf = CSRFProtect()


@login_manager.user_loader
def load_user(user_id):
    try:
        user = db.session.get(User, int(user_id))
    except ValueError:
        return None
    return user if user is not None and user.is_active else None


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY") or secrets.token_hex(32),
        SQLALCHEMY_DATABASE_URI="sqlite:///salon.sqlite3",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
    )
    if test_config is not None:
        app.config.update(test_config)

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)
    register_login_response_handler(login_manager)
    app.register_blueprint(auth)
    app.register_blueprint(slots_api)
    app.register_blueprint(customer)
    # app.register_blueprint(staff)
    # app.register_blueprint(admin)
    register_error_handlers(app)
    register_seed_command(app)

    @app.get("/")
    def index():
        return render_template("auth/demo.html")

    return app
