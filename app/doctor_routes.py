from flask import Blueprint, render_template, request, redirect, url_for
import sqlite3
import os

doctor_bp = Blueprint('doctor', __name__)

# DB path relative to this module
DATABASE = os.path.join(os.path.dirname(__file__), 'hospital_management.db')

_migration_done = False

def ensure_bidirectional_links():
    """Ensure prescription_id column exists on treatments table and medication fields in prescription_items."""
    global _migration_done
    if _migration_done:
        return
    try:
        conn = sqlite3.connect(DATABASE, timeout=30)
        cols = [r[1] for r in conn.execute("PRAGMA table_info(treatments);").fetchall()]
        if 'prescription_id' not in cols:
            conn.execute("ALTER TABLE treatments ADD COLUMN prescription_id INTEGER REFERENCES prescriptions(id) ON DELETE SET NULL;")
            conn.commit()
            print("Runtime migration: Added prescription_id to treatments table.")
        
        pi_cols = [r[1] for r in conn.execute("PRAGMA table_info(prescription_items);").fetchall()]
        if 'medication_name' not in pi_cols:
            conn.execute("ALTER TABLE prescription_items ADD COLUMN medication_name TEXT;")
            conn.commit()
            print("Runtime migration: Added medication_name to prescription_items table.")
        if 'medication_description' not in pi_cols:
            conn.execute("ALTER TABLE prescription_items ADD COLUMN medication_description TEXT;")
            conn.commit()
            print("Runtime migration: Added medication_description to prescription_items table.")
        
        conn.close()
        _migration_done = True
    except Exception as e:
        print(f"Migration check failed: {e}")

def get_conn():
    # increase timeout and allow connections from different threads (dev server may use threads)
    conn = sqlite3.connect(DATABASE, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute('PRAGMA foreign_keys = ON;')
    except Exception:
        pass
    return conn


@doctor_bp.route('/logs')
def view_logs():
    from flask import session, redirect, flash
    # require doctor login
    if not session.get('doctor_logged_in'):
        flash('Please login as doctor')
        return redirect(url_for('doctor.login'))
    did = session.get('doctor_id')
    conn = get_conn()
    # include patient name and limit logs to this doctor
    logs = conn.execute('''
        SELECT t.*, p.first_name || ' ' || p.last_name AS patient_name
        FROM treatments t
        LEFT JOIN patients p ON p.id = t.patient_id
        WHERE t.doctor_id = ?
        ORDER BY t.start_date DESC, t.id DESC
    ''', (did,)).fetchall()
    
    # Get all treatments and prescriptions for each patient
    logs_with_details = []
    for log in logs:
        pid = log['patient_id']
        # Get all treatments for this patient
        treatments = conn.execute('SELECT * FROM treatments WHERE patient_id = ? ORDER BY start_date DESC', (pid,)).fetchall()
        # Get all prescriptions for this patient with treatment_id
        prescriptions = conn.execute('''
            SELECT p.id, p.created_at, p.notes, p.treatment_id,
                   GROUP_CONCAT(pi.medication_name, ', ') AS medications,
                   GROUP_CONCAT(pi.dosage, ', ') AS dosages
            FROM prescriptions p
            LEFT JOIN prescription_items pi ON pi.prescription_id = p.id
            WHERE p.patient_id = ?
            GROUP BY p.id
            ORDER BY p.created_at DESC
        ''', (pid,)).fetchall()
        
        log_dict = dict(log)
        log_dict['treatments'] = treatments
        log_dict['prescriptions'] = prescriptions
        logs_with_details.append(log_dict)
    
    conn.close()
    return render_template('doctor_logs.html', logs=logs_with_details)


@doctor_bp.route('/add_treatment', methods=['GET', 'POST'])
def add_treatment():
    from flask import session, redirect, flash
    if not session.get('doctor_logged_in'):
        flash('Please login as doctor')
        return redirect(url_for('doctor.login'))
    did = session.get('doctor_id')
    conn = get_conn()
    if request.method == 'POST':
        pid = request.form['patient_id']
        # prefer using logged-in doctor id
        if 'doctor_id' in request.form and request.form['doctor_id']:
            did = request.form['doctor_id']
        else:
            did = None
        # if doctor is logged in via session, use that id
        from flask import session
        if session.get('doctor_logged_in') and session.get('doctor_id'):
            did = session.get('doctor_id')

        details = request.form['details']
        conn.execute("INSERT INTO treatments (patient_id, doctor_id, description) VALUES (?, ?, ?)", (pid, did, details))
        conn.commit()
        conn.close()
        return redirect(url_for('doctor.view_logs'))

    # GET: render simple form with patients assigned to this doctor
    patients = conn.execute('''
        SELECT DISTINCT p.id, p.first_name, p.last_name
        FROM patients p
        LEFT JOIN appointments a ON a.patient_id = p.id
        WHERE p.doctor = ? OR a.doctor_id = ?
        ORDER BY p.first_name, p.last_name
    ''', (did, did)).fetchall()
    doctors = conn.execute('SELECT doctor_id, f_name, l_name FROM doctors').fetchall()
    conn.close()
    return render_template('add_treatment.html', patients=patients, doctors=doctors)


@doctor_bp.route('/login', methods=['GET', 'POST'])
def login():
    from flask import session, flash
    conn = get_conn()
    if request.method == 'POST':
        username = request.form.get('username','').strip()
        password = request.form.get('password','')
        # username is f_name + l_name (no space)
        # try to find matching doctor
        row = conn.execute("SELECT * FROM doctors WHERE (f_name || l_name) = ? AND password = ?", (username, password)).fetchone()
        if row:
            session['doctor_logged_in'] = True
            session['doctor_id'] = row['doctor_id']
            session['doctor_name'] = f"{row['f_name']} {row['l_name']}"
            conn.close()
            # after login, go to Manage Patients so the doctor can pick a patient
            return redirect(url_for('doctor.my_patients'))
        else:
            flash('Invalid doctor credentials')
    conn.close()
    return render_template('doctor_login.html')


@doctor_bp.route('/logout')
def logout():
    from flask import session
    session.pop('doctor_logged_in', None)
    session.pop('doctor_id', None)
    session.pop('doctor_name', None)
    return redirect(url_for('doctor.login'))



@doctor_bp.route('/treatment/edit/<int:tid>', methods=['GET', 'POST'])
def edit_treatment(tid):
    from flask import session, flash
    conn = get_conn()
    treatment = conn.execute('SELECT t.*, p.first_name || " " || p.last_name AS patient_name FROM treatments t LEFT JOIN patients p ON p.id = t.patient_id WHERE t.id = ?', (tid,)).fetchone()
    if not treatment:
        conn.close()
        flash('Treatment not found')
        return redirect(url_for('doctor.view_logs'))

    # Only the assigned doctor (or if not logged in, prevent edit)
    if not session.get('doctor_logged_in') or session.get('doctor_id') != treatment['doctor_id']:
        conn.close()
        flash('Not authorized to edit this treatment')
        return redirect(url_for('doctor.view_logs'))

    if request.method == 'POST':
        desc = request.form.get('description')
        conn.execute('UPDATE treatments SET description = ? WHERE id = ?', (desc, tid))
        conn.commit()
        conn.close()
        flash('Treatment updated')
        return redirect(url_for('doctor.view_logs'))

    conn.close()
    return render_template('edit_treatment.html', treatment=treatment)


@doctor_bp.route('/doctors')
def list_doctors():
    conn = get_conn()
    doctors = conn.execute('SELECT * FROM doctors ORDER BY created_at DESC').fetchall()
    conn.close()
    return render_template('doctors.html', doctors=doctors)


@doctor_bp.route('/profile/<int:did>')
def doctor_profile(did):
    conn = get_conn()
    doc = conn.execute('SELECT * FROM doctors WHERE doctor_id = ?', (did,)).fetchone()
    treatments = conn.execute('''
        SELECT COALESCE(t.id, 0) as id, 
               a.patient_id, 
               p.first_name || ' ' || p.last_name as patient_name,
               a.appointment_datetime,
               COALESCE(t.description, '-') as treatment_details
        FROM appointments a
        LEFT JOIN patients p ON p.id = a.patient_id
        LEFT JOIN treatments t ON t.patient_id = a.patient_id AND t.doctor_id = a.doctor_id
        WHERE a.doctor_id = ? AND a.status IN ('confirmed', 'completed')
        ORDER BY a.appointment_datetime DESC
    ''', (did,)).fetchall()
    
    conn.close()
    return render_template('doctor_profile.html', doctor=doc, treatments=treatments)


@doctor_bp.route('/patients')
def my_patients():
    # show patients assigned to logged-in doctor
    from flask import session, redirect, flash
    if not session.get('doctor_logged_in'):
        flash('Please login as doctor')
        return redirect(url_for('doctor.login'))
    did = session.get('doctor_id')
    conn = get_conn()
    patients = conn.execute('''
        SELECT DISTINCT p.id, p.first_name, p.last_name, p.dob, p.phone
        FROM patients p
        LEFT JOIN appointments a ON a.patient_id = p.id
        WHERE p.doctor = ? OR a.doctor_id = ?
        ORDER BY p.first_name, p.last_name
    ''', (did, did)).fetchall()
    conn.close()
    return render_template('doctor_patients.html', patients=patients)


@doctor_bp.route('/dashboard')
def dashboard():
    """Doctor dashboard: show today's schedule (appointments for the day)."""
    from flask import session, flash
    if not session.get('doctor_logged_in'):
        flash('Please login as doctor')
        return redirect(url_for('doctor.login'))
    did = session.get('doctor_id')
    conn = get_conn()
    # select appointments for today for this doctor
    rows = conn.execute('''
        SELECT a.*, p.first_name || ' ' || p.last_name AS patient_name
        FROM appointments a
        LEFT JOIN patients p ON p.id = a.patient_id
        WHERE a.doctor_id = ? AND date(a.appointment_datetime) = date('now') AND a.status IN ('booked','confirmed')
        ORDER BY a.appointment_datetime ASC
    ''', (did,)).fetchall()
    conn.close()
    return render_template('doctor_dashboard.html', rows=rows)


@doctor_bp.route('/appointments')
def view_appointments_doctor():
    """Show appointments assigned to the logged-in doctor that are confirmed."""
    from flask import session, redirect, flash
    if not session.get('doctor_logged_in'):
        flash('Please login as doctor')
        return redirect(url_for('doctor.login'))
    did = session.get('doctor_id')
    conn = get_conn()
    rows = conn.execute('''
        SELECT a.*, p.first_name || ' ' || p.last_name AS patient_name
        FROM appointments a
        LEFT JOIN patients p ON p.id = a.patient_id
        WHERE a.doctor_id = ? AND a.status IN ('booked','confirmed')
        ORDER BY a.appointment_datetime ASC
    ''', (did,)).fetchall()
    conn.close()
    return render_template('doctor_appointments.html', rows=rows)


@doctor_bp.route('/appointment/<int:aid>', methods=['GET', 'POST'])
def open_appointment(aid):
    """Open a single appointment so the assigned doctor can add treatment notes."""
    from flask import session, flash
    if not session.get('doctor_logged_in'):
        flash('Please login as doctor')
        return redirect(url_for('doctor.login'))
    did = session.get('doctor_id')
    conn = get_conn()
    appt = conn.execute('''
        SELECT a.*, p.first_name || ' ' || p.last_name AS patient_name, p.id AS patient_id
        FROM appointments a
        JOIN patients p ON p.id = a.patient_id
        WHERE a.id = ?
    ''', (aid,)).fetchone()
    if not appt:
        conn.close()
        flash('Appointment not found')
        return redirect(url_for('doctor.view_appointments_doctor'))

    # ensure this appointment is assigned to this doctor
    if appt['doctor_id'] is None or appt['doctor_id'] != did:
        conn.close()
        flash('Not authorized to view this appointment')
        return redirect(url_for('doctor.view_appointments_doctor'))

    # handle adding a treatment note
    if request.method == 'POST':
        details = request.form.get('details') or ''
        conn.execute('INSERT INTO treatments (patient_id, doctor_id, description, start_date) VALUES (?, ?, ?, datetime("now"))', (appt['patient_id'], did, details))
        conn.commit()
        flash('Treatment note added')

    # reload treatments for the patient
    treatments = conn.execute('SELECT * FROM treatments WHERE patient_id = ? ORDER BY start_date DESC', (appt['patient_id'],)).fetchall()
    conn.close()
    return render_template('doctor_appointment.html', appointment=appt, treatments=treatments)


@doctor_bp.route('/patient/<int:pid>', methods=['GET', 'POST'])
def view_patient(pid):
    # doctor can add symptoms (as treatment), prescribe (prescription + items)
    from flask import session, flash
    if not session.get('doctor_logged_in'):
        flash('Please login as doctor')
        return redirect(url_for('doctor.login'))
    ensure_bidirectional_links()
    did = session.get('doctor_id')
    conn = get_conn()
    patient = conn.execute('SELECT * FROM patients WHERE id = ?', (pid,)).fetchone()
    if not patient:
        conn.close()
        flash('Patient not found')
        return redirect(url_for('doctor.my_patients'))

    # ensure this patient is accessible to this doctor: either primary doctor or has an appointment assigned to this doctor
    accessible = False
    try:
        if patient['doctor'] == did:
            accessible = True
    except Exception:
        accessible = False
    if not accessible:
        row = conn.execute('SELECT COUNT(1) AS cnt FROM appointments WHERE patient_id = ? AND doctor_id = ?', (pid, did)).fetchone()
        if row and row['cnt'] > 0:
            accessible = True
    if not accessible:
        conn.close()
        flash('Not authorized to view this patient')
        return redirect(url_for('doctor.my_patients'))

    # handle POST actions: add_symptom, add_prescription
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'add_symptom':
            desc = request.form.get('description')
            conn.execute('INSERT INTO treatments (patient_id, doctor_id, description, start_date) VALUES (?, ?, ?, datetime("now"))', (pid, did, desc))
            conn.commit()
            flash('Symptom / treatment note added')
        elif action == 'prescribe':
            # First create the treatment
            description = request.form.get('description') or ''
            cur_treatment = conn.execute('INSERT INTO treatments (patient_id, doctor_id, description, start_date) VALUES (?, ?, ?, datetime("now"))', (pid, did, description))
            treatment_id = cur_treatment.lastrowid
            
            # Now create the prescription linked to the treatment
            med_name = request.form.get('medication_name')
            dosage = request.form.get('dosage')
            duration = request.form.get('duration') or ''
            unit_price = float(request.form.get('unit_price') or 0)
            med_description = request.form.get('medication_description') or ''

            # create prescription with duration in notes and link to treatment
            notes = request.form.get('notes') or ''
            if duration:
                notes = f"Duration: {duration}" + (f" | {notes}" if notes else "")
            cur = conn.execute('INSERT INTO prescriptions (patient_id, doctor_id, notes, treatment_id) VALUES (?, ?, ?, ?)', (pid, did, notes, treatment_id))
            presc_id = cur.lastrowid
            # add item with medication info directly in prescription_items (no medications table)
            conn.execute('INSERT INTO prescription_items (prescription_id, medication_name, medication_description, dosage, quantity, unit_price) VALUES (?, ?, ?, ?, ?, ?)', (presc_id, med_name, med_description, dosage, 1, unit_price))
            
            # Update treatment with prescription_id for bidirectional link
            conn.execute('UPDATE treatments SET prescription_id = ? WHERE id = ?', (presc_id, treatment_id))
            
            conn.commit()
            flash('Treatment and prescription created')

    treatments = conn.execute('SELECT * FROM treatments WHERE patient_id = ? ORDER BY start_date DESC', (pid,)).fetchall()
    prescriptions = conn.execute('''
        SELECT p.id, p.created_at, p.notes, p.treatment_id,
               GROUP_CONCAT(pi.medication_name, ', ') AS medications,
               GROUP_CONCAT(pi.dosage, ', ') AS dosages
        FROM prescriptions p
        LEFT JOIN prescription_items pi ON pi.prescription_id = p.id
        WHERE p.patient_id = ?
        GROUP BY p.id
        ORDER BY p.created_at DESC
    ''', (pid,)).fetchall()
    
    # Fetch appointment notes (reason for booking) for this patient and doctor
    appointments = conn.execute('''
        SELECT appointment_datetime, notes, status
        FROM appointments
        WHERE patient_id = ? AND doctor_id = ?
        ORDER BY appointment_datetime DESC
    ''', (pid, did)).fetchall()
    
    conn.close()
    return render_template('doctor_patient.html', patient=patient, treatments=treatments, prescriptions=prescriptions, appointments=appointments)
