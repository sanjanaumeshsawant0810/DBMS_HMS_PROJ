import sqlite3

def create_hms_db(db_name="hospital_management.db"):
    conn = sqlite3.connect(db_name)
    c = conn.cursor()

    # Enable foreign keys
    c.execute("PRAGMA foreign_keys = ON;")
    # Use WAL journal mode to reduce locking contention (allows concurrent reads/writes)
    try:
        c.execute("PRAGMA journal_mode = WAL;")
        c.execute("PRAGMA synchronous = NORMAL;")
    except Exception:
        pass

    schema = """
    -- -----------------------
    -- doctors table (replaces staff)
    -- -----------------------
    CREATE TABLE IF NOT EXISTS doctors (
        doctor_id INTEGER PRIMARY KEY AUTOINCREMENT,
        f_name TEXT NOT NULL,
        l_name TEXT NOT NULL,
        specialization TEXT,
        contact TEXT,
        department TEXT,
        availability TEXT,
        password TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    );

    -- -----------------------
    -- patients
    -- -----------------------
    CREATE TABLE IF NOT EXISTS patients (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        first_name TEXT NOT NULL,
        last_name TEXT NOT NULL,
        dob DATE,
        phone TEXT,
        address TEXT,
        doctor INTEGER REFERENCES doctors(doctor_id) ON DELETE SET NULL,
        department TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    );

    -- -----------------------
    -- rooms and room_assignments
    -- -----------------------
    CREATE TABLE IF NOT EXISTS rooms (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        room_number TEXT UNIQUE NOT NULL,
        type TEXT,
        rate_per_day REAL DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS room_assignments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
        room_id INTEGER NOT NULL REFERENCES rooms(id) ON DELETE SET NULL,
        start_date TEXT NOT NULL,
        end_date TEXT,
        notes TEXT
    );

    -- -----------------------
    -- medications
    -- -----------------------
    CREATE TABLE IF NOT EXISTS medications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        description TEXT,
        price REAL DEFAULT 0
    );

    -- -----------------------
    -- appointments
    -- -----------------------
    CREATE TABLE IF NOT EXISTS appointments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    doctor_id INTEGER REFERENCES doctors(doctor_id) ON DELETE SET NULL,
        appointment_datetime TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('booked','confirmed','cancelled','completed')) DEFAULT 'booked',
        notes TEXT,
        fee REAL DEFAULT 0
    );

    -- -----------------------
    -- treatments
    -- -----------------------
    CREATE TABLE IF NOT EXISTS treatments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    doctor_id INTEGER REFERENCES doctors(doctor_id) ON DELETE SET NULL,
        description TEXT,
        start_date TEXT DEFAULT (datetime('now')),
        end_date TEXT,
        room_id INTEGER REFERENCES rooms(id) ON DELETE SET NULL,
        cost REAL DEFAULT 0,
        notes TEXT
    );

    -- -----------------------
    -- prescriptions
    -- -----------------------
    CREATE TABLE IF NOT EXISTS prescriptions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    doctor_id INTEGER REFERENCES doctors(doctor_id) ON DELETE SET NULL,
    pharmacist_id INTEGER,
        created_at TEXT DEFAULT (datetime('now')),
        notes TEXT
    );

    CREATE TABLE IF NOT EXISTS prescription_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        prescription_id INTEGER NOT NULL REFERENCES prescriptions(id) ON DELETE CASCADE,
        medication_id INTEGER NOT NULL REFERENCES medications(id) ON DELETE SET NULL,
        dosage TEXT,
        quantity INTEGER DEFAULT 1,
        unit_price REAL DEFAULT 0,
        fulfilled INTEGER DEFAULT 0,
        fulfilled_at TEXT
    );

    -- -----------------------
    -- med dispense
    -- -----------------------
    CREATE TABLE IF NOT EXISTS med_dispense (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
    prescription_item_id INTEGER NOT NULL REFERENCES prescription_items(id) ON DELETE CASCADE,
    pharmacist_id INTEGER,
        dispensed_at TEXT DEFAULT (datetime('now')),
        quantity INTEGER NOT NULL,
        notes TEXT
    );

    -- -----------------------
    -- lab tests
    -- -----------------------
    CREATE TABLE IF NOT EXISTS lab_tests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    doctor_id INTEGER REFERENCES doctors(doctor_id) ON DELETE SET NULL,
    phlebotomist_id INTEGER,
        test_name TEXT NOT NULL,
        requested_at TEXT DEFAULT (datetime('now')),
        performed_at TEXT,
        result TEXT,
        status TEXT NOT NULL CHECK(status IN ('ordered','in_progress','completed','cancelled')) DEFAULT 'ordered',
        cost REAL DEFAULT 0,
        notes TEXT
    );

    -- -----------------------
    -- bills
    -- -----------------------
    CREATE TABLE IF NOT EXISTS bills (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
        total_amount REAL DEFAULT 0,
        paid INTEGER DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now')),
        paid_at TEXT
    );

    CREATE TABLE IF NOT EXISTS bill_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        bill_id INTEGER NOT NULL REFERENCES bills(id) ON DELETE CASCADE,
        item_type TEXT NOT NULL,
        item_ref INTEGER,
        description TEXT,
        amount REAL NOT NULL DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now'))
    );

    -- add paid flag and paid_at for item-level payments (migration-friendly)
    -- Note: If the columns already exist, migration below will skip adding them.

    -- -----------------------
    -- Triggers
    -- -----------------------
    CREATE TRIGGER IF NOT EXISTS trg_ensure_open_bill_after_insert_treatment
    AFTER INSERT ON treatments
    BEGIN
        INSERT INTO bills(patient_id, total_amount, paid, created_at)
        SELECT NEW.patient_id, 0, 0, datetime('now')
        WHERE NOT EXISTS (SELECT 1 FROM bills b WHERE b.patient_id = NEW.patient_id AND b.paid = 0);

        INSERT INTO bill_items(bill_id, item_type, item_ref, description, amount, created_at)
        VALUES (
            (SELECT id FROM bills WHERE patient_id = NEW.patient_id AND paid = 0 ORDER BY created_at DESC LIMIT 1),
            'treatment',
            NEW.id,
            COALESCE(NEW.description,'Treatment'),
            COALESCE(NEW.cost,0),
            datetime('now')
        );

        UPDATE bills
        SET total_amount = total_amount + COALESCE(NEW.cost,0)
        WHERE id = (SELECT id FROM bills WHERE patient_id = NEW.patient_id AND paid = 0 ORDER BY created_at DESC LIMIT 1);
    END;

    CREATE TRIGGER IF NOT EXISTS trg_prescription_item_after_insert
    AFTER INSERT ON prescription_items
    BEGIN
        INSERT INTO bills(patient_id, total_amount, paid, created_at)
        SELECT p.patient_id, 0, 0, datetime('now')
        FROM prescriptions p
        WHERE p.id = NEW.prescription_id
          AND NOT EXISTS (SELECT 1 FROM bills b WHERE b.patient_id = p.patient_id AND b.paid = 0);

        INSERT INTO bill_items(bill_id, item_type, item_ref, description, amount, created_at)
        VALUES (
            (SELECT id FROM bills WHERE patient_id = (SELECT patient_id FROM prescriptions WHERE id = NEW.prescription_id) AND paid = 0 ORDER BY created_at DESC LIMIT 1),
            'medication',
            NEW.id,
            (SELECT m.name FROM medications m WHERE m.id = NEW.medication_id),
            COALESCE(NEW.unit_price,0) * COALESCE(NEW.quantity,1),
            datetime('now')
        );

        UPDATE bills
        SET total_amount = total_amount + (COALESCE(NEW.unit_price,0) * COALESCE(NEW.quantity,1))
        WHERE id = (SELECT id FROM bills WHERE patient_id = (SELECT patient_id FROM prescriptions WHERE id = NEW.prescription_id) AND paid = 0 ORDER BY created_at DESC LIMIT 1);
    END;

    CREATE TRIGGER IF NOT EXISTS trg_lab_test_after_update_completed
    AFTER UPDATE OF status ON lab_tests
    WHEN NEW.status = 'completed' AND (OLD.status IS NULL OR OLD.status != 'completed')
    BEGIN
        INSERT INTO bills(patient_id, total_amount, paid, created_at)
        SELECT NEW.patient_id, 0, 0, datetime('now')
        WHERE NOT EXISTS (SELECT 1 FROM bills b WHERE b.patient_id = NEW.patient_id AND b.paid = 0);

        INSERT INTO bill_items(bill_id, item_type, item_ref, description, amount, created_at)
        VALUES (
            (SELECT id FROM bills WHERE patient_id = NEW.patient_id AND paid = 0 ORDER BY created_at DESC LIMIT 1),
            'lab_test',
            NEW.id,
            NEW.test_name,
            COALESCE(NEW.cost,0),
            datetime('now')
        );

        UPDATE bills
        SET total_amount = total_amount + COALESCE(NEW.cost,0)
        WHERE id = (SELECT id FROM bills WHERE patient_id = NEW.patient_id AND paid = 0 ORDER BY created_at DESC LIMIT 1);
    END;
    """

    c.executescript(schema)
    # --- Migration: ensure 'password' column exists on doctors for older DBs ---
    try:
        cols = [r[1] for r in c.execute("PRAGMA table_info(doctors);").fetchall()]
        if 'password' not in cols:
            c.execute("ALTER TABLE doctors ADD COLUMN password TEXT;")
            print("Added 'password' column to doctors table (migration).")
    except Exception:
        # If doctors table doesn't exist yet or other issue, ignore here — schema creation above will handle it
        pass
    # --- Migration: ensure 'doctor' and 'department' columns exist on patients for older DBs ---
    try:
        pcols = [r[1] for r in c.execute("PRAGMA table_info(patients);").fetchall()]
        if 'doctor' not in pcols:
            c.execute("ALTER TABLE patients ADD COLUMN doctor INTEGER;")
            print("Added 'doctor' column to patients table (migration).")
        if 'department' not in pcols:
            c.execute("ALTER TABLE patients ADD COLUMN department TEXT;")
            print("Added 'department' column to patients table (migration).")
    except Exception:
        pass
    # --- Migration: make appointments.doctor_id nullable if older DB has NOT NULL constraint ---
    try:
        ap_cols = c.execute("PRAGMA table_info(appointments);").fetchall()
        # PRAGMA table_info returns rows: (cid, name, type, notnull, dflt_value, pk)
        doctor_col = None
        for col in ap_cols:
            if col[1] == 'doctor_id':
                doctor_col = col
                break
        if doctor_col is not None and doctor_col[3] == 1:
            print("Found NOT NULL constraint on appointments.doctor_id — migrating to allow NULLs...")
            # Disable foreign keys temporarily for table rebuild
            c.execute('PRAGMA foreign_keys = OFF;')
            # Rename old table
            c.execute('ALTER TABLE appointments RENAME TO appointments_old;')
            # Create new appointments table with doctor_id nullable
            c.execute('''
                CREATE TABLE IF NOT EXISTS appointments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    patient_id INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
                    doctor_id INTEGER REFERENCES doctors(doctor_id) ON DELETE SET NULL,
                    appointment_datetime TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('booked','confirmed','cancelled','completed')) DEFAULT 'booked',
                    notes TEXT,
                    fee REAL DEFAULT 0
                );
            ''')
            # Copy data across (keep existing doctor_id values)
            c.execute('''
                INSERT INTO appointments (id, patient_id, doctor_id, appointment_datetime, status, notes, fee)
                SELECT id, patient_id, doctor_id, appointment_datetime, status, notes, fee FROM appointments_old;
            ''')
            # Drop old table
            c.execute('DROP TABLE appointments_old;')
            # Re-enable foreign keys
            c.execute('PRAGMA foreign_keys = ON;')
            print('Migrated appointments table to allow NULL doctor_id.')
    except Exception as ex:
        # If appointments table doesn't exist yet or migration fails, print and continue
        print('appointments migration skipped or failed:', ex)
    # --- Migration: ensure 'actions' column exists on appointments for older DBs ---
    try:
        acols = [r[1] for r in c.execute("PRAGMA table_info(appointments);").fetchall()]
        if 'actions' not in acols:
            c.execute("ALTER TABLE appointments ADD COLUMN actions TEXT;")
            print("Added 'actions' column to appointments table (migration).")
    except Exception:
        # ignore if appointments table doesn't exist yet
        pass
    # --- Migration: ensure 'paid' and 'paid_at' exist on bill_items for item-level payments ---
    try:
        bi_cols = [r[1] for r in c.execute("PRAGMA table_info(bill_items);").fetchall()]
        if 'paid' not in bi_cols:
            c.execute("ALTER TABLE bill_items ADD COLUMN paid INTEGER DEFAULT 0;")
            print("Added 'paid' column to bill_items table (migration).")
        if 'paid_at' not in bi_cols:
            c.execute("ALTER TABLE bill_items ADD COLUMN paid_at TEXT;")
            print("Added 'paid_at' column to bill_items table (migration).")
    except Exception:
        pass
    conn.commit()
    conn.close()
    print(f"✅ Database '{db_name}' created successfully with all tables and triggers.")


if __name__ == "__main__":
    create_hms_db()
