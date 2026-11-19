# AGENTS.md

Notes for coding agents. No human-facing prose on purpose.

## Authority

`docs/spec.md` defines every route, field name, enum, time and money format, status code and error code. If code and spec disagree, fix the code. If the spec is wrong, change the spec first, then the code.

Not part of the contract and free to change: folder layout, ORM style, query style, test framework, HTML and CSS.

`README.md` links to `docs/role-b-handoff.md` and `docs/spec/README.md`. None of those exist in this repo. Ignore the links.

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

Add a `.gitattributes` containing `* text=auto eol=lf` before a macOS contributor joins; without it every file shows as modified after each pull.

## Run

```
.\.venv\Scripts\python.exe -m flask --app app seed
.\.venv\Scripts\python.exe -m flask --app app run
```

`seed` fills an empty database only; rerunning is a no-op. It prints the demo password once and never stores it elsewhere. Delete `instance/salon.sqlite3` to start from scratch.

## Test

```
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

Expect `Ran 37 tests ... OK`. Twenty-two belong to the shared baseline, fifteen to the customer pages. Any other number means the baseline is broken; repair it before adding features.

## File ownership

| Owner | Files |
|---|---|
| B | `app.py`, `auth.py`, `models.py`, `money.py`, `responses.py`, `seed.py`, `templates/base.html`, `templates/auth/*`, `templates/errors/*` |
| A | `availability.py`, `booking.py`, `tests/test_booking_rules.py` |
| C | `customer.py`, `templates/customer/*`, `static/*`, `tests/test_customer.py` |
| D | `staff.py`, `admin.py`, `templates/staff/*`, `templates/admin/*`, `tests/test_staff_admin.py` |

Only B edits `app.py`. A, C and D deliver a blueprint object and tell B its name; B uncomments the matching import and `register_blueprint` line.

## Current gaps

- `app.py` registers `auth` only. The `customer`, `staff` and `admin` imports and registrations are commented out. Uncomment one only after its module exists.
- `templates/base.html` has no stylesheet link and no customer navigation. Customer pages therefore carry a local sub-nav and a body-level `<link rel="stylesheet">` in `templates/customer/layout.html`. Move both into `base.html` when B next edits it.
- `availability.py` and `booking.py` do not exist yet, so `/book` and the three write routes are missing. The customer pages currently stop at the catalogue and the personal list.
