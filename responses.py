"""Shared response conventions for HTML pages and JSON/fetch requests."""

from flask import jsonify, redirect, render_template, request, url_for
from flask_wtf.csrf import CSRFError
from werkzeug.exceptions import HTTPException


_HTTP_ERROR_CODES = {
    400: "BAD_REQUEST",
    401: "AUTH_REQUIRED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    500: "SERVER_ERROR",
}


def wants_json():
    """Return whether the current request is an API/fetch interaction.

    API paths are JSON by contract.  Other fetch callers must send either an
    ``Accept: application/json`` header, a JSON content type, or the explicit
    XMLHttpRequest marker.  Ordinary browser form requests remain HTML.
    """
    accept = request.accept_mimetypes
    return (
        request.path.startswith("/api/")
        or request.is_json
        or request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or accept.best == "application/json"
    )


def json_error(code, message, status, **extra):
    """Build the stable flat JSON error shape used by all API handlers."""
    payload = {"error": code, "message": message}
    payload.update(extra)
    return jsonify(payload), status


def _request_path_with_query():
    query = request.query_string.decode("utf-8", errors="replace")
    return request.path + (f"?{query}" if query else "")


def register_login_response_handler(login_manager):
    """Keep HTML login redirects and make API authentication machine-readable."""

    @login_manager.unauthorized_handler
    def unauthorized():
        is_json = wants_json()
        login_url = url_for("auth.login")
        if not is_json and request.method in {"GET", "HEAD"}:
            # Only a safe local page GET can be replayed after authentication.
            # APIs would return JSON, and replaying a write as GET can cause 405.
            next_path = _request_path_with_query()
            login_url = url_for("auth.login", next=next_path)
        if is_json:
            return json_error(
                "AUTH_REQUIRED",
                "Authentication is required.",
                401,
                login_url=login_url,
            )
        # Use a local path rather than request.url so the login redirect never
        # carries a user-controlled scheme or host into the next parameter.
        return redirect(login_url)


def register_error_handlers(app):
    """Return one JSON media type/shape for API errors, without exposing internals."""

    @app.errorhandler(CSRFError)
    def handle_csrf_error(_error):
        if wants_json():
            return json_error(
                "CSRF_FAILED",
                "The CSRF token is missing, invalid, or expired.",
                400,
                fields={"csrf_token": "missing, invalid, or expired"},
            )
        return render_template("errors/csrf.html"), 400

    @app.errorhandler(HTTPException)
    def handle_http_error(error):
        if wants_json():
            code = _HTTP_ERROR_CODES.get(error.code, "HTTP_ERROR")
            messages = {
                400: "The request could not be validated.",
                401: "Authentication is required.",
                403: "You do not have permission to perform this action.",
                404: "The requested resource was not found.",
                405: "The HTTP method is not allowed for this resource.",
                409: "The request conflicts with the current state.",
            }
            return json_error(code, messages.get(error.code, "The request failed."), error.code)
        # Browser requests get the shared styled error page so a 404 or 403 does
        # not fall back to Flask's bare default. The status code is unchanged.
        return render_template("errors/error.html", status=error.code), error.code

    @app.errorhandler(500)
    def handle_internal_error(_error):
        if wants_json():
            return json_error("SERVER_ERROR", "An unexpected server error occurred.", 500)
        return render_template("errors/error.html", status=500), 500
