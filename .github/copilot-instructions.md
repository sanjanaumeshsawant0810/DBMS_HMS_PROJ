# Hospital Management System (HMS) - AI Coding Agent Instructions

## Architecture Overview

This is a Flask-based Hospital Management System using SQLite with a **three-role architecture**:
- **Admin**: Manages patients, doctors, appointments, and billing (`/admin/*`)
- **Patient**: Books appointments and views their records (`/patient/*`)
- **Doctor**: Views assigned patients, manages treatments and prescriptions (`/doctor/*`)

Each role is isolated into a separate Flask Blueprint (`admin_routes.py`, `patient_routes.py`, `doctor_routes.py`) registered with URL prefixes in `app/app.py`.

## Critical Database Patterns

### Single Shared Database
All modules use `hospital_management.db` in the `app/` directory via `DATABASE = os.path.join(os.path.dirname(__file__), 'hospital_management.db')`. Never hardcode absolute paths.

### Runtime Schema Migrations
This project uses **runtime migration guards** instead of traditional migration tools. Schema changes are applied on startup via:
- `ensure_bill_items_columns()` in `admin_routes.py` - adds `paid`/`paid_at` columns to `bill_items`
- `ensure_bidirectional_links()` in `doctor_routes.py` - adds `prescription_id`, `medication_name`, `medication_description`
- `create_hms_db.py` contains migrations at bottom (line ~248+) using `PRAGMA table_info` checks

**When adding new columns**: Follow this pattern with global `_migration_done` flag to run once per process.

### Database Connection Standards
```python
conn = sqlite3.connect(DATABASE, timeout=30, check_same_thread=False)
conn.row_factory = sqlite3.Row
conn.execute('PRAGMA foreign_keys = ON;')  # ALWAYS enable
```

WAL mode (`PRAGMA journal_mode = WAL`) is set in `create_hms_db.py` for concurrent read/write support.

### Trigger-Driven Billing System
Bills are **automatically generated** via SQLite triggers when treatments/prescriptions/lab tests are created:
- `trg_ensure_open_bill_after_insert_treatment` - adds treatment costs to bill
- `trg_prescription_item_after_insert` - adds medication costs
- `trg_lab_test_after_update_completed` - adds lab test costs when marked complete

**Do not manually insert bill_items** - triggers handle this. Bill workflow: open bill (paid=0) per patient → items accumulate → mark paid via `/admin/payments/process`.

## Authentication & Session Management

### Three Separate Login Flows
- **Admin**: Hardcoded credentials (`admin`/`admin123`) at `/admin/login`, stores `session['admin'] = True`
- **Patient**: ID-based login (no password) at `/patient/login`, stores `session['patient_id']` and `session['patient_name']`
- **Doctor**: Password-based login at `/doctor/login`, stores `session['doctor_logged_in']`, `session['doctor_id']`, `session['doctor_name']`

### Route Protection Pattern
```python
if 'admin' not in session:
    return redirect(url_for('admin.login'))
```
Apply this guard at the start of every protected route. Use `session.pop()` for logout.

## Appointment Workflow (Critical Business Logic)

1. **Patient books** appointment at `/patient/book` with `doctor_id=NULL` and `status='booked'`
2. **Admin reviews** at `/admin/appointments`, assigns a doctor, changes status to `'confirmed'`
3. **Doctor sees** confirmed appointments at `/doctor/appointments` filtered by their `doctor_id`

**Never** let patients select doctors directly - admin assignment is mandatory.

## Development Workflow

### Starting the App
```bash
# From project root
python app/app.py
```
Runs on `http://localhost:5000` (port configurable via `PORT` env var). Debug mode is enabled.

### Database Initialization
```bash
# From app/ directory
python create_hms_db.py
```
Creates `hospital_management.db` with schema, triggers, and migrations. Safe to re-run (uses `CREATE TABLE IF NOT EXISTS`).

### No Dependencies File
Flask is the only external dependency. Install manually: `pip install flask`. The README mentions `myenv` but it's not committed.

## Code Conventions

### Blueprint URL Generation
Always use `url_for()` with blueprint prefix:
```python
redirect(url_for('admin.dashboard'))  # Correct
redirect(url_for('dashboard'))        # Wrong - missing blueprint
```

### Template Context
`base.html` checks `request.endpoint` to hide navbar on login pages and customize nav based on `session` keys. Flash messages use Bootstrap toast notifications.

### Database Row Access
Use `sqlite3.Row` factory (already configured):
```python
row = conn.execute('SELECT * FROM patients WHERE id = ?', (pid,)).fetchone()
patient_name = row['first_name']  # Dict-style access
```

### Appointment Status Values
Strict constraint: `CHECK(status IN ('booked','confirmed','cancelled','completed'))`. Use these exact strings.

## Key Files Reference

- `app/app.py` - Main Flask app, blueprint registration, startup logging
- `app/create_hms_db.py` - Schema definition (line 15-150), triggers (line 170-240), migrations (line 248+)
- `app/admin_routes.py` - 17 routes including payment processing (`/payments/process`), appointment confirmation
- `app/doctor_routes.py` - Treatment/prescription management, bidirectional linking between treatments and prescriptions
- `app/patient_routes.py` - Simple appointment booking (no doctor selection)
- `app/templates/base.html` - Shared layout with role-based navbar

## Common Pitfalls

1. **Forgetting `PRAGMA foreign_keys = ON`** - relationships won't be enforced
2. **Not using blueprint prefixes in `url_for()`** - causes 404s
3. **Manually creating bill_items** - triggers will duplicate charges
4. **Letting patients select doctors** - breaks the admin-assignment workflow
5. **Hardcoding database paths** - use `os.path.join(os.path.dirname(__file__), ...)`

## Extending the System

- **New columns**: Add to schema in `create_hms_db.py` + create migration guard function
- **New routes**: Add to appropriate blueprint file, maintain session-based auth pattern
- **New triggers**: Add to `create_hms_db.py` schema string using `CREATE TRIGGER IF NOT EXISTS`
- **New role**: Create new blueprint file, register in `app.py`, add session keys and login template
