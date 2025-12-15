# Hospital Management System (HMS)

A comprehensive Flask-based Hospital Management System with SQLite backend, featuring role-based access control for **Admin**, **Patient**, and **Doctor** users.

---

## 📋 Overview

The HMS provides a complete workflow for hospital operations:

1. **Admin Portal** - Manages patients, doctors, appointments, treatments, prescriptions, billing, and system operations
2. **Patient Portal** - Allows patients to book appointments and view their medical history
3. **Doctor Portal** - Enables doctors to manage their assigned patients, treatments, and prescriptions

---

## 🏗️ Architecture

### Three-Role Blueprint Architecture
- **Admin Blueprint** (`admin_routes.py`) - Admin portal at `/admin/*`
- **Patient Blueprint** (`patient_routes.py`) - Patient portal at `/patient/*`
- **Doctor Blueprint** (`doctor_routes.py`) - Doctor portal at `/doctor/*`

Each role has isolated authentication, session management, and routes with proper authorization checks.

---

## 🔑 Key Features

### Admin Features
- ✅ **Patient Management** - Add, update, view, and manage patient records with DOB and contact info
- ✅ **Doctor Management** - Add, edit, and manage doctor credentials and profiles
- ✅ **Appointment Management** - Review and confirm appointments, assign doctors, change appointment status
- ✅ **Billing System** - Track bills, view bill items, process payments with automatic trigger-based charges
- ✅ **Dashboard** - Overview of total patients, doctors, appointments, and revenue

### Patient Features
- ✅ **Appointment Booking** - Book appointments without selecting doctors (admin assigns)
- ✅ **Medical History** - View upcoming and past appointments
- ✅ **Appointment Details** - See appointment dates, status, and assigned doctor

### Doctor Features
- ✅ **Patient List** - View all assigned patients with search functionality
- ✅ **Patient Details** - See patient medical history, appointment reasons, treatments, and prescriptions
- ✅ **Treatment Management** - Add treatments for patients with appointment dates and details
- ✅ **Prescription Management** - Create and manage prescriptions with medications
- ✅ **Profile** - View personal profile with assigned appointments and treatments
- ✅ **Treatment Logs** - View complete treatment history and logs

---

## 🚀 Quick Start

### Prerequisites
- Python 3.7+
- Flask
- SQLite3

### Installation & Setup

1. **Clone the repository:**
```bash
git clone https://github.com/DBMS16-954-694-01-HMS/DBMS_HMS_PROJ.git
cd DBMS_HMS_PROJ
```

2. **Install Flask (if not already installed):**
```bash
pip install flask
```

3. **Initialize the database:**
```bash
cd app
python create_hms_db.py
```
This creates `hospital_management.db` with all tables, triggers, and migrations.

4. **Run the application:**
```bash
python app.py
```
The app starts on `http://localhost:5000` (configurable via `PORT` environment variable).

### Default Login Credentials
- **Admin**: Username `admin` / Password `admin123`
- **Patient**: Login with Patient ID (no password required)
- **Doctor**: Login with credentials set by admin during doctor creation

### Access Points
| Role | URL | Credentials |
|------|-----|-------------|
| Admin | http://localhost:5000/admin/login | admin / admin123 |
| Patient | http://localhost:5000/patient/login | Patient ID (any) |
| Doctor | http://localhost:5000/doctor/login | Set by admin |

---

## 📁 Project Structure

```
app/
├── app.py                           # Main Flask application, blueprint registration
├── create_hms_db.py                 # Database schema, triggers, migrations
├── admin_routes.py                  # Admin portal routes (17+ endpoints)
├── doctor_routes.py                 # Doctor portal routes (10+ endpoints)
├── patient_routes.py                # Patient portal routes (5+ endpoints)
├── hospital_management.db           # SQLite database
├── static/
│   ├── css/style.css               # Custom styles
│   └── icons/                      # Background images
└── templates/
    ├── base.html                   # Shared layout with role-based navbar
    ├── login.html                  # Admin login
    ├── patient_login.html          # Patient login
    ├── doctor_login.html           # Doctor login
    ├── dashboard.html              # Admin dashboard
    ├── add_patient.html            # Admin patient list view
    ├── add_patients.html           # Add new patient form
    ├── update_patient.html         # Edit patient info
    ├── add_doctors.html            # Doctor list & add doctor form
    ├── admin_appointments.html     # Manage appointments
    ├── bills.html                  # Billing system
    ├── patient_home.html           # Patient dashboard
    ├── patient_book.html           # Appointment booking
    ├── patient_appointments.html   # Patient's appointments
    ├── doctor_patients.html        # Doctor's patient list with search
    ├── doctor_patient.html         # Detailed patient view with treatments
    ├── doctor_appointments.html    # Doctor's appointments
    ├── doctor_profile.html         # Doctor profile with treatments
    └── doctor_logs.html            # Treatment logs
```

---

## 🗄️ Database Schema Highlights

### Core Tables
- **patients** - Patient demographics (id, name, dob, phone, address)
- **doctors** - Doctor info (id, name, specialization, phone, password)
- **appointments** - Booking records (id, patient_id, doctor_id, appointment_datetime, status, notes)
- **treatments** - Treatment records (id, patient_id, doctor_id, treatment_details, appointment_id)
- **prescriptions** - Medication records (id, treatment_id, medication_name, dosage, duration)
- **bills** - Bill records (id, patient_id, total_amount, paid status)
- **bill_items** - Individual charges (id, bill_id, description, amount, paid_at)

### Key Triggers
- **trg_ensure_open_bill_after_insert_treatment** - Auto-creates bill items for treatments
- **trg_prescription_item_after_insert** - Auto-charges prescriptions to bills
- **trg_lab_test_after_update_completed** - Auto-charges lab tests when completed

---

## 🔐 Authentication & Authorization

### Session-Based Auth
- Admin: `session['admin'] = True`
- Patient: `session['patient_id']`, `session['patient_name']`
- Doctor: `session['doctor_logged_in']`, `session['doctor_id']`, `session['doctor_name']`

### Route Protection
All protected routes check session keys and redirect to login if missing.

---

## 📝 Important Notes

### Database Connection
All modules use `hospital_management.db` via `os.path.join(os.path.dirname(__file__), 'hospital_management.db')`. Never hardcode absolute paths.

### Migration Guards
Schema changes use runtime guards with `_migration_done` flags. New columns are checked at startup using `PRAGMA table_info`.

### Appointment Workflow
1. Patient books → status `'booked'`, doctor_id `NULL`
2. Admin assigns doctor → status `'confirmed'`
3. Doctor views confirmed appointments → can add treatments/prescriptions
4. Status can be changed to `'completed'` or `'cancelled'`

### Billing System
Bills auto-generate via triggers when treatments/prescriptions are created. Never manually insert into `bill_items` - triggers handle it. Process payments via `/admin/payments/process`.

---

## 🛠️ Technologies Used

- **Backend**: Python 3, Flask, Blueprint routing
- **Database**: SQLite3 with WAL mode for concurrent access
- **Frontend**: Jinja2 templates, Bootstrap 5, vanilla JavaScript
- **Date/Time**: Python `datetime` module (mm-dd-yyyy format)
- **Security**: Session-based authentication, SQL prepared statements

---

## 📌 Development Tips

- Debug mode is enabled in `app.py`
- Use `url_for()` with blueprint names: `url_for('admin.dashboard')`
- Always enable `PRAGMA foreign_keys = ON` in new connections
- Test login workflows before building complex features
- Check `create_hms_db.py` for existing triggers/constraints before adding new ones

---

## 📜 License

Internal project - All rights reserved.

---

## 👥 Contributors

- Admin Backend: Hospital Management Team
- UI/Frontend: Design & Development Team
- Database Design: Data Architecture Team

