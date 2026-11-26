# AGENTS.md

Notes for coding agents. No human-facing prose on purpose.

## Authority

`docs/spec.md` defines every route, field name, enum, time and money format, status code and error code. If code and spec disagree, fix the code. If the spec is wrong, change the spec first, then the code.

Not part of the contract and free to change: folder layout, ORM style, query style, test framework, HTML and CSS.

## Environment

Each clone builds its own virtual environment.

```
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

If `pip` exits with `FileNotFoundError: No usable temporary directory found`, redirect temp and retry:

```
$env:TEMP="$PWD\.tmp"; $env:TMP=$env:TEMP; $env:TMPDIR=$env:TEMP
```

`.gitattributes` enforces LF line endings (`* text=auto eol=lf`) across Windows and macOS contributors.

## Run

```
.\.venv\Scripts\python.exe -m flask --app app seed
.\.venv\Scripts\python.exe -m flask --app app run
```

`seed` fills an empty database only; rerunning is a no-op. Delete `instance/salon.sqlite3` and seed again whenever a fresh demo dataset or a schema change is needed.

Seeded accounts — all five share the password `SalonDemo123!` (override with `SEED_PASSWORD`, 8–128 non-blank characters, before running `seed`):

| Email | Role |
|---|---|
| `admin@example.com` | admin |
| `stylist1@example.com` | stylist |
| `stylist2@example.com` | stylist |
| `customer1@example.com` | customer |
| `customer2@example.com` | customer |

A database seeded before the password became fixed keeps its old random password, because `seed` skips a non-empty database. Deleting `instance/salon.sqlite3` is the only way to reset it.

## Test

```
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

Expect `Ran 138 tests ... OK`. Breakdown: `test_auth.py` 9, `test_contracts.py` 11, `test_booking_rules.py` 68, `test_customer.py` 50. Any other number means the baseline is broken; repair it before adding features.

## File ownership

| Owner | Files |
|---|---|
| B | `app.py`, `auth.py`, `models.py`, `money.py`, `responses.py`, `seed.py`, `templates/base.html`, `templates/auth/*`, `templates/errors/*` |
| A | `availability.py`, `booking.py`, `tests/test_booking_rules.py` |
| C | `customer.py`, `templates/customer/*`, `static/*`, `tests/test_customer.py` |
| D | `staff.py`, `admin.py`, `templates/staff/*`, `templates/admin/*`, `tests/test_staff_admin.py` |

Only B edits `app.py`. A, C and D deliver a blueprint object and tell B its name; B adds the import and the `register_blueprint` line.

Blueprints currently wired: `auth`, `slots_api` (from `availability.py`), `customer`. The `staff` and `admin` slots are still commented out.

## Current gaps

- Role C scope is complete: catalogue, detail, booking form, my appointments, create, cancel and reschedule. Every write goes through `booking.py`; `booking.BookingError` subclasses already carry `error_code` and `http_status`, so views only translate them. Do not duplicate availability or transaction logic in a view.
- `staff.py` and `admin.py` do not exist. Every `/staff/*` and `/admin/*` route is missing.
