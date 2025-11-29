from flask import Blueprint, render_template, request, redirect, url_for, flash, session
import sqlite3
import os
from datetime import datetime

# runtime migration guard: ensure bill_items has item-level paid columns
_migrations_checked = False

def ensure_bill_items_columns():
    """Add 'paid' and 'paid_at' columns to bill_items if they don't exist yet.
    This runs once per process to avoid SQL errors when selecting these columns.
    """
    global _migrations_checked
    if _migrations_checked:
        return
    try:
        # open a short-lived connection for migration
        mconn = sqlite3.connect(DATABASE, timeout=30)
        cur = mconn.cursor()
        try:
            cols = [r[1] for r in cur.execute("PRAGMA table_info(bill_items);").fetchall()]
        except Exception:
            cols = []
        if 'paid' not in cols:
            try:
                cur.execute("ALTER TABLE bill_items ADD COLUMN paid INTEGER DEFAULT 0;")
                mconn.commit()
            except Exception:
                # ignore if alter fails for any reason
                pass
        if 'paid_at' not in cols:
            try:
                cur.execute("ALTER TABLE bill_items ADD COLUMN paid_at TEXT;")
                mconn.commit()
            except Exception:
                pass
    finally:
        try:
            mconn.close()
        except Exception:
            pass
        _migrations_checked = True

admin_bp = Blueprint('admin', __name__)

# Use a path relative to this file so the app always finds the right DB
DATABASE = os.path.join(os.path.dirname(__file__), 'hospital_management.db')

def get_db_connection():
    # increase timeout and allow connections from different threads (dev server may use threads)
    conn = sqlite3.connect(DATABASE, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # ensure foreign keys are enabled on this connection
    try:
        conn.execute('PRAGMA foreign_keys = ON;')
    except Exception:
        pass
    return conn

# --------------------------
# Admin Login / Logout
# --------------------------
@admin_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        # Simple hardcoded admin login (you can connect to staff table if you want)
        if username == 'admin' and password == 'admin123':
            session['admin'] = True
            flash('Login successful!', 'success')
            return redirect(url_for('admin.dashboard'))
        else:
            flash('Invalid username or password', 'danger')

    return render_template('login.html')


@admin_bp.route('/logout')
def logout():
    session.pop('admin', None)
    flash('Logged out successfully', 'info')
    return redirect(url_for('admin.login'))  # <- added blueprint prefix


# --------------------------
# Admin Dashboard
# --------------------------
@admin_bp.route('/dashboard')
def dashboard():
    if 'admin' not in session:
        return redirect(url_for('admin.login'))  # <- added blueprint prefix

    conn = get_db_connection()
    stats = {
        'patients': conn.execute('SELECT COUNT(*) FROM patients').fetchone()[0],
        'doctors': conn.execute("SELECT COUNT(*) FROM doctors").fetchone()[0],
        'rooms': conn.execute('SELECT COUNT(*) FROM rooms').fetchone()[0],
        'bills': conn.execute('SELECT COUNT(*) FROM bills').fetchone()[0],
    }
    conn.close()
    return render_template('dashboard.html', stats=stats)  # <- corrected template name


# --------------------------
# Patients Management
# --------------------------
@admin_bp.route('/patients')
def patients():
    if 'admin' not in session:
        return redirect(url_for('admin.login'))  # <- added blueprint prefix
    conn = get_db_connection()
    patients = conn.execute('''
        SELECT p.*, d.f_name || ' ' || d.l_name AS doctor_name
        FROM patients p
        LEFT JOIN doctors d ON d.doctor_id = p.doctor
        ORDER BY p.id DESC
    ''').fetchall()
    doctors = conn.execute('SELECT doctor_id, f_name, l_name FROM doctors').fetchall()
    conn.close()
    return render_template('add_patient.html', patients=patients, doctors=doctors)


@admin_bp.route('/patients/add', methods=['GET', 'POST'])
def add_patient():
    if 'admin' not in session:
        return redirect(url_for('admin.login'))  # <- added blueprint prefix
    if request.method == 'POST':
        first = request.form['first_name']
        last = request.form['last_name']
        phone = request.form['phone']
        address = request.form['address']
        doctor = request.form.get('doctor') or None

        conn = get_db_connection()
        conn.execute(
            'INSERT INTO patients (first_name, last_name, phone, address, doctor) VALUES (?, ?, ?, ?, ?)',
            (first, last, phone, address, doctor)
        )
        conn.commit()
        conn.close()
        flash('Patient added successfully!', 'success')
        return redirect(url_for('admin.patients'))  # <- added blueprint prefix

    # GET: provide list of doctors for the select
    conn = get_db_connection()
    doctors = conn.execute('SELECT doctor_id, f_name, l_name FROM doctors').fetchall()
    conn.close()
    return render_template('add_patients.html', doctors=doctors)


@admin_bp.route('/patients/delete/<int:pid>')
def delete_patient(pid):
    if 'admin' not in session:
        return redirect(url_for('admin.login'))  # <- added blueprint prefix
    conn = get_db_connection()
    conn.execute('DELETE FROM patients WHERE id = ?', (pid,))
    conn.commit()
    conn.close()
    flash('Patient deleted successfully!', 'info')
    return redirect(url_for('admin.patients'))  # <- added blueprint prefix


# --------------------------
# View Bills
# --------------------------
@admin_bp.route('/bills')
def bills():
    if 'admin' not in session:
        return redirect(url_for('admin.login'))  # <- added blueprint prefix
    ensure_bill_items_columns()
    conn = get_db_connection()
    bills = conn.execute('''
        SELECT b.id,
               p.id AS patient_id,
               p.first_name || ' ' || p.last_name AS patient_name,
               b.total_amount,
               b.paid,
               b.paid_at,
               b.created_at,
               COALESCE(GROUP_CONCAT(CASE WHEN bi.item_type = 'treatment' THEN bi.description END, '; '), '') AS treatments
        FROM bills b
        JOIN patients p ON p.id = b.patient_id
        LEFT JOIN bill_items bi ON bi.bill_id = b.id
        GROUP BY b.id
        ORDER BY b.created_at DESC
    ''').fetchall()
    # fetch treatment items per bill so template can provide a selectable list
    bill_ids = [str(row['id']) for row in bills]
    bill_items_map = {}
    if bill_ids:
        q = f"SELECT id, bill_id, item_type, description, amount, paid FROM bill_items WHERE bill_id IN ({','.join(bill_ids)}) AND item_type = 'treatment' ORDER BY created_at DESC"
        items = conn.execute(q).fetchall()
        for it in items:
            bill_items_map.setdefault(it['bill_id'], []).append(dict(id=it['id'], description=it['description'], amount=it['amount'], paid=it['paid']))
    conn.close()
    return render_template('bills.html', bills=bills, bill_items_map=bill_items_map)


@admin_bp.route('/payments', methods=['POST'])
def payments():
    if 'admin' not in session:
        return redirect(url_for('admin.login'))
    ensure_bill_items_columns()
    # expected form data: selected_bill (multiple) and for each bill a selected_treatment_<billid>
    selected = request.form.getlist('selected_bill')
    if not selected:
        flash('No bills selected for payment.', 'warning')
        return redirect(url_for('admin.bills'))

    # collect selected treatment item ids and associated bill/patient info
    conn = get_db_connection()
    item_ids = []
    bills_info = {}
    patient_ids = set()
    for bid in selected:
        sel_name = f'selected_treatment_{bid}'
        # support multiple selections per bill
        item_vals = request.form.getlist(sel_name)
        for item_id in item_vals:
            if not item_id:
                continue
            try:
                iid = int(item_id)
            except Exception:
                continue
            # skip items already paid
            paid_row = conn.execute('SELECT paid FROM bill_items WHERE id = ?', (iid,)).fetchone()
            if paid_row and paid_row['paid']:
                # ignore already-paid items
                continue
            item_ids.append(iid)
            row = conn.execute('SELECT bill_id FROM bill_items WHERE id = ?', (iid,)).fetchone()
            if row:
                b_id = row['bill_id']
                b = conn.execute('SELECT id, patient_id, total_amount, paid FROM bills WHERE id = ?', (b_id,)).fetchone()
                if b:
                    bills_info.setdefault(b_id, dict(id=b['id'], patient_id=b['patient_id'], total_amount=b['total_amount'], paid=b['paid']))
                    patient_ids.add(b['patient_id'])

    if not item_ids:
        flash('No treatment items selected for payment.', 'warning')
        conn.close()
        return redirect(url_for('admin.bills'))

    # fetch item details
    placeholders = ','.join('?' for _ in item_ids)
    items = conn.execute(f'SELECT id, bill_id, description, amount FROM bill_items WHERE id IN ({placeholders})', item_ids).fetchall()
    items = [dict(id=i['id'], bill_id=i['bill_id'], description=i['description'], amount=i['amount']) for i in items]
    # determine patient(s)
    patients = {}
    for b in bills_info.values():
        p = conn.execute('SELECT id, first_name, last_name FROM patients WHERE id = ?', (b['patient_id'],)).fetchone()
        if p:
            patients[b['patient_id']] = dict(id=p['id'], name=f"{p['first_name']} {p['last_name']}")

    conn.close()

    return render_template('payment_portal.html', items=items, bills_info=bills_info, patients=patients, patient_ids=list(patient_ids))


@admin_bp.route('/payments/process', methods=['POST'])
def payments_process():
    if 'admin' not in session:
        return redirect(url_for('admin.login'))
    ensure_bill_items_columns()
    # expects 'item_ids' as multiple values
    item_ids = request.form.getlist('item_ids')
    payment_method = request.form.get('payment_method') or 'unknown'
    # normalize to ints
    try:
        item_ids = [int(x) for x in item_ids]
    except Exception:
        item_ids = []
    if not item_ids:
        flash('No items to process.', 'warning')
        return redirect(url_for('admin.bills'))

    conn = get_db_connection()
    # mark each selected item as paid and set paid_at
    placeholders = ','.join('?' for _ in item_ids)
    items = conn.execute(f'SELECT id, bill_id, amount FROM bill_items WHERE id IN ({placeholders})', item_ids).fetchall()
    now = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    paid_bill_ids = set()
    for it in items:
        conn.execute('UPDATE bill_items SET paid = 1, paid_at = ? WHERE id = ? AND (paid IS NULL OR paid = 0)', (now, it['id']))
        paid_bill_ids.add(it['bill_id'])

    # For each affected bill, check if all items are paid; if so, mark bill as paid and set paid_at
    for bid in paid_bill_ids:
        row = conn.execute('SELECT SUM(CASE WHEN paid = 0 OR paid IS NULL THEN 1 ELSE 0 END) AS unpaid_count FROM bill_items WHERE bill_id = ?', (bid,)).fetchone()
        unpaid = row['unpaid_count'] if row else 0
        if unpaid == 0:
            conn.execute('UPDATE bills SET paid = 1, paid_at = ? WHERE id = ?', (now, bid))

    conn.commit()
    conn.close()
    flash(f'Payment processed ({payment_method}) for selected items. Item-level payment recorded.', 'success')
    return redirect(url_for('admin.bills'))



@admin_bp.route('/bills/mark_paid/<int:bid>', methods=['POST'])
def mark_bill_paid(bid):
    if 'admin' not in session:
        return redirect(url_for('admin.login'))
    ensure_bill_items_columns()
    conn = get_db_connection()
    row = conn.execute('SELECT paid FROM bills WHERE id = ?', (bid,)).fetchone()
    if not row:
        conn.close()
        return ('Bill not found', 404)
    if row['paid']:
        conn.close()
        return ('Already paid', 400)
    now = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    conn.execute('UPDATE bills SET paid = 1, paid_at = ? WHERE id = ?', (now, bid))
    conn.commit()
    conn.close()
    return ('', 204)


# --------------------------
# Doctors Management (Admin)
# --------------------------
@admin_bp.route('/doctors')
def doctors():
    if 'admin' not in session:
        return redirect(url_for('admin.login'))
    conn = get_db_connection()
    doctors = conn.execute("SELECT * FROM doctors ORDER BY created_at DESC").fetchall()
    conn.close()
    return render_template('doctors.html', doctors=doctors)


@admin_bp.route('/doctors/add', methods=['GET', 'POST'])
def add_doctor():
    if 'admin' not in session:
        return redirect(url_for('admin.login'))
    if request.method == 'POST':
        f_name = request.form.get('f_name')
        l_name = request.form.get('l_name')
        specialization = request.form.get('specialization')
        contact = request.form.get('contact')
        department = request.form.get('department')
        availability = request.form.get('availability')

        password = request.form.get('password')
        conn = get_db_connection()
        conn.execute(
            "INSERT INTO doctors (f_name, l_name, specialization, contact, department, availability, password) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (f_name, l_name, specialization, contact, department, availability, password)
        )
        conn.commit()
        conn.close()
        flash('Doctor added successfully!', 'success')
        return redirect(url_for('admin.doctors'))
    
    return render_template('add_doctors.html')


@admin_bp.route('/doctors/delete/<int:did>')
def delete_doctor(did):
    if 'admin' not in session:
        return redirect(url_for('admin.login'))
    conn = get_db_connection()
    conn.execute("DELETE FROM doctors WHERE doctor_id = ?", (did,))
    conn.commit()
    conn.close()
    flash('Doctor deleted successfully!', 'info')
    return redirect(url_for('admin.doctors'))

# --------------------------
# Update Patient Logs
# --------------------------
@admin_bp.route('/patients/update/<int:pid>', methods=['GET', 'POST'])
def update_patient(pid):
    if 'admin' not in session:
        return redirect(url_for('admin.login'))

    conn = get_db_connection()
    patient = conn.execute('SELECT * FROM patients WHERE id = ?', (pid,)).fetchone()
    doctors = conn.execute('SELECT doctor_id, f_name, l_name FROM doctors').fetchall()
    # fetch appointments for this patient so admin can edit time/status
    # include doctor info (if assigned) so template can show current assigned doctor name
    appointments = conn.execute('''
        SELECT a.*, d.doctor_id AS assigned_doctor_id, d.f_name || ' ' || d.l_name AS doctor_name
        FROM appointments a
        LEFT JOIN doctors d ON d.doctor_id = a.doctor_id
        WHERE a.patient_id = ?
        ORDER BY a.appointment_datetime DESC
    ''', (pid,)).fetchall()

    if request.method == 'POST':
        first = request.form['first_name']
        last = request.form['last_name']
        phone = request.form['phone']
        address = request.form['address']
        # Patient-level doctor assignment: allow admin to set a primary doctor for the patient
        doctor_raw = request.form.get('doctor')
        # If the template does not include a patient-level doctor select (we moved assignment to per-appointment),
        # don't overwrite the existing patient.doctor. Only update if doctor value was submitted.
        if doctor_raw is None:
            doctor = patient['doctor']
        else:
            doctor = None
            if doctor_raw and doctor_raw.strip() != '':
                try:
                    doctor = int(doctor_raw)
                except Exception:
                    doctor = doctor_raw

        conn.execute(
            'UPDATE patients SET first_name=?, last_name=?, phone=?, address=?, doctor=? WHERE id=?',
            (first, last, phone, address, doctor, pid)
        )
        conn.commit()
        # resolve doctor name for flash
        doc_name = None
        if doctor:
            row = conn.execute('SELECT f_name, l_name FROM doctors WHERE doctor_id = ?', (doctor,)).fetchone()
            if row:
                doc_name = f"Dr. {row['f_name']} {row['l_name']}"
        conn.close()
        if doc_name:
            flash(f'Patient updated and assigned to {doc_name}', 'success')
        else:
            flash('Patient updated successfully!', 'success')
        return redirect(url_for('admin.patients'))

    conn.close()
    return render_template('update_patient.html', patient=patient, doctors=doctors, appointments=appointments)


@admin_bp.route('/appointments/update/<int:aid>', methods=['POST'])
def update_appointment(aid):
    if 'admin' not in session:
        return redirect(url_for('admin.login'))
    # form fields: date, time, status, patient_id (hidden) to redirect back
    date = request.form.get('date')
    time = request.form.get('time')
    status = request.form.get('status') or 'booked'
    patient_id = request.form.get('patient_id')

    # collect actions for per-appointment updates and per-appointment doctor assignment
    actions = request.form.get('actions') or None
    doctor_raw = request.form.get('doctor')
    doctor_id = None
    if doctor_raw and doctor_raw.strip() != '':
        try:
            doctor_id = int(doctor_raw)
        except Exception:
            doctor_id = doctor_raw

    # combine date and time if provided
    appt_dt = date or None
    if date and time:
        appt_dt = f"{date} {time}"

    # debug print for tracing what is being updated
    print(f"[admin.update_appointment] FORM DATA: {dict(request.form)}")
    print(f"[admin.update_appointment] aid={aid} patient_id={patient_id!r} appt_dt={appt_dt!r} status={status!r} actions={actions!r} doctor_id={doctor_id!r}")

    conn = get_db_connection()
    # update appointment fields: actions, optionally datetime, status, and per-appointment doctor assignment
    if appt_dt:
        if doctor_id is not None:
            conn.execute('UPDATE appointments SET appointment_datetime = ?, status = ?, actions = ?, doctor_id = ? WHERE id = ?', (appt_dt, status, actions, doctor_id, aid))
        else:
            conn.execute('UPDATE appointments SET appointment_datetime = ?, status = ?, actions = ? WHERE id = ?', (appt_dt, status, actions, aid))
    else:
        if doctor_id is not None:
            conn.execute('UPDATE appointments SET status = ?, actions = ?, doctor_id = ? WHERE id = ?', (status, actions, doctor_id, aid))
        else:
            conn.execute('UPDATE appointments SET status = ?, actions = ? WHERE id = ?', (status, actions, aid))
    conn.commit()
    # verify update
    row = conn.execute('SELECT id, doctor_id, status, appointment_datetime, actions FROM appointments WHERE id = ?', (aid,)).fetchone()
    print(f"[admin.update_appointment] post-update row={row}")
    conn.close()
    flash('Appointment updated', 'success')
    if patient_id:
        return redirect(url_for('admin.update_patient', pid=patient_id))
    return redirect(url_for('admin.appointments'))


@admin_bp.route('/appointments')
def appointments():
    if 'admin' not in session:
        return redirect(url_for('admin.login'))
    conn = get_db_connection()
    # show appointments that are booked (pending) so admin can assign a doctor and confirm
    rows = conn.execute('''
        SELECT a.*, p.first_name || ' ' || p.last_name AS patient_name, d.doctor_id, d.f_name || ' ' || d.l_name AS doctor_name
        FROM appointments a
        JOIN patients p ON p.id = a.patient_id
        LEFT JOIN doctors d ON d.doctor_id = a.doctor_id
        WHERE a.status = 'booked'
        ORDER BY a.appointment_datetime ASC
    ''').fetchall()
    doctors = conn.execute('SELECT doctor_id, f_name, l_name FROM doctors ORDER BY f_name, l_name').fetchall()
    conn.close()
    return render_template('admin_appointments.html', rows=rows, doctors=doctors)


@admin_bp.route('/appointments/confirm/<int:aid>', methods=['POST'])
def confirm_appointment(aid):
    if 'admin' not in session:
        return redirect(url_for('admin.login'))
    # collect form data: doctor, optional date/time edit, actions text
    doctor_id_raw = request.form.get('doctor')
    doctor_id = None
    if doctor_id_raw and doctor_id_raw.strip() != '':
        try:
            doctor_id = int(doctor_id_raw)
        except Exception:
            doctor_id = doctor_id_raw
    edit_dt = request.form.get('edit_dt')
    date = request.form.get('date')
    time = request.form.get('time')
    actions = request.form.get('actions')

    # if edit_dt is present, combine date/time
    appt_dt = None
    if edit_dt and date:
        appt_dt = date
        if time:
            appt_dt = f"{date} {time}"

    # debug log to help trace why doctor_id may not be set
    print(f"[admin.confirm_appointment] aid={aid} doctor_id={doctor_id!r} edit_dt={edit_dt!r} date={date!r} time={time!r} actions={actions!r}")
    # require a doctor selection on the server side as well
    if doctor_id is None:
        flash('Please select a doctor before confirming.', 'danger')
        return redirect(url_for('admin.appointments'))

    conn = get_db_connection()
    # build update fields dynamically
    if appt_dt is not None:
        conn.execute('UPDATE appointments SET doctor_id = ?, status = ?, appointment_datetime = ?, actions = ? WHERE id = ?', (doctor_id, 'confirmed', appt_dt, actions, aid))
    else:
        conn.execute('UPDATE appointments SET doctor_id = ?, status = ?, actions = ? WHERE id = ?', (doctor_id, 'confirmed', actions, aid))

    conn.commit()
    # verify update: fetch appointment row and confirm doctor_id
    row = conn.execute('SELECT id, doctor_id, status, appointment_datetime, actions FROM appointments WHERE id = ?', (aid,)).fetchone()
    conn.close()
    print(f"[admin.confirm_appointment] post-update row={row}")
    if not row or (row['doctor_id'] is None):
        flash('Failed to assign doctor to appointment — please check logs.', 'danger')
    else:
        flash('Appointment confirmed and assigned to doctor', 'success')
    return redirect(url_for('admin.appointments'))
