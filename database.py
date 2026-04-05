import os
import psycopg2
from psycopg2.extras import RealDictCursor

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://neondb_owner:npg_7nHiMWjXbue3@ep-quiet-term-a18iejjt-pooler.ap-southeast-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"
)

def get_db():
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    return conn

def init_db():
    conn = get_db()
    cur  = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS societies (
            id           SERIAL PRIMARY KEY,
            name         TEXT NOT NULL,
            address      TEXT,
            username     TEXT UNIQUE NOT NULL,
            password     TEXT NOT NULL,
            regd_no      TEXT,
            active       BOOLEAN DEFAULT TRUE,
            created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS notice_batches (
            id          SERIAL PRIMARY KEY,
            society_id  INTEGER REFERENCES societies(id) ON DELETE CASCADE,
            batch_name  TEXT NOT NULL,
            notice_type TEXT DEFAULT '1st',
            issued_date TEXT NOT NULL,
            total       INTEGER DEFAULT 0,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS notices (
            id              SERIAL PRIMARY KEY,
            batch_id        INTEGER REFERENCES notice_batches(id) ON DELETE CASCADE,
            society_id      INTEGER REFERENCES societies(id) ON DELETE CASCADE,
            flat_no         TEXT NOT NULL,
            ref_no          TEXT NOT NULL,
            member_name     TEXT NOT NULL,
            amount          INTEGER NOT NULL,
            notice_type     TEXT DEFAULT '1st',
            issued_date     TEXT NOT NULL,
            payment_status  TEXT DEFAULT 'Pending',
            payment_date    TEXT,
            payment_amount  INTEGER,
            payment_remark  TEXT,
            prev_ref_no     TEXT,
            created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # Insert default admin society if not exists
    cur.execute("""
        INSERT INTO societies (name, address, username, password, regd_no)
        VALUES ('Shreeji Iconic CHS Ltd', 'New Panvel Highway Link Road, Badlapur', 'shreeji', 'shreeji2026', 'TNA/AMB/HSG/TC/35985')
        ON CONFLICT (username) DO NOTHING;
    """)

    # Society members directory (for WhatsApp lookup)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS society_members (
            id           SERIAL PRIMARY KEY,
            society_id   INTEGER REFERENCES societies(id) ON DELETE CASCADE,
            building_no  TEXT NOT NULL,
            flat_no      TEXT NOT NULL,
            flat_combo   TEXT NOT NULL,
            name         TEXT NOT NULL,
            phone        TEXT NOT NULL,
            email        TEXT,
            created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(society_id, flat_combo)
        );
    """)

    conn.commit()
    cur.close()
    conn.close()

# ── Society functions ──────────────────────────────────────────
def get_society_by_username(username):
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("SELECT * FROM societies WHERE username=%s AND active=TRUE", (username,))
    row = cur.fetchone()
    cur.close(); conn.close()
    return dict(row) if row else None

def get_all_societies():
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("SELECT * FROM societies ORDER BY created_at DESC")
    rows = cur.fetchall()
    cur.close(); conn.close()
    return [dict(r) for r in rows]

def create_society(name, address, username, password, regd_no):
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("""
        INSERT INTO societies (name, address, username, password, regd_no)
        VALUES (%s, %s, %s, %s, %s) RETURNING id
    """, (name, address, username, password, regd_no))
    sid = cur.fetchone()['id']
    conn.commit(); cur.close(); conn.close()
    return sid

def delete_society(society_id):
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("DELETE FROM societies WHERE id=%s", (society_id,))
    conn.commit(); cur.close(); conn.close()

# ── Batch functions ────────────────────────────────────────────
def save_batch(batch_name, notice_type, issued_date, members, society_id):
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("""
        INSERT INTO notice_batches (society_id, batch_name, notice_type, issued_date, total)
        VALUES (%s, %s, %s, %s, %s) RETURNING id
    """, (society_id, batch_name, notice_type, issued_date, len(members)))
    batch_id = cur.fetchone()['id']
    for m in members:
        cur.execute("""
            INSERT INTO notices (batch_id, society_id, flat_no, ref_no, member_name, amount, notice_type, issued_date, prev_ref_no)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (batch_id, society_id, m['flat_no'], m['ref_no'], m['name'],
              m['amount'], notice_type, issued_date, m.get('prev_ref_no', '')))
    conn.commit(); cur.close(); conn.close()
    return batch_id

def get_batches(society_id):
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("""
        SELECT b.*,
               COUNT(CASE WHEN n.payment_status='Paid'    THEN 1 END) as paid_count,
               COUNT(CASE WHEN n.payment_status='Pending' THEN 1 END) as pending_count
        FROM notice_batches b
        LEFT JOIN notices n ON n.batch_id = b.id
        WHERE b.society_id=%s
        GROUP BY b.id
        ORDER BY b.created_at DESC
    """, (society_id,))
    rows = cur.fetchall()
    cur.close(); conn.close()
    return [dict(r) for r in rows]

def get_batch_notices(batch_id):
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("SELECT * FROM notices WHERE batch_id=%s ORDER BY flat_no", (batch_id,))
    rows = cur.fetchall()
    cur.close(); conn.close()
    return [dict(r) for r in rows]

def update_payment(notice_id, status, payment_date, payment_amount, remark):
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("""
        UPDATE notices SET payment_status=%s, payment_date=%s, payment_amount=%s, payment_remark=%s
        WHERE id=%s
    """, (status, payment_date, payment_amount, remark, notice_id))
    conn.commit(); cur.close(); conn.close()

def get_eligible_for_2nd(batch_id):
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("SELECT * FROM notices WHERE batch_id=%s AND payment_status='Pending' ORDER BY flat_no", (batch_id,))
    rows = cur.fetchall()
    cur.close(); conn.close()
    return [dict(r) for r in rows]

def get_paid_members(batch_id):
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("SELECT * FROM notices WHERE batch_id=%s AND payment_status='Paid' ORDER BY payment_date DESC", (batch_id,))
    rows = cur.fetchall()
    cur.close(); conn.close()
    return [dict(r) for r in rows]

def delete_batch(batch_id):
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("DELETE FROM notices        WHERE batch_id=%s", (batch_id,))
    cur.execute("DELETE FROM notice_batches WHERE id=%s",       (batch_id,))
    conn.commit(); cur.close(); conn.close()

def get_society_stats(society_id):
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("SELECT COUNT(*) as total FROM notice_batches WHERE society_id=%s", (society_id,))
    batches = cur.fetchone()['total']
    cur.execute("SELECT COUNT(*) as total FROM notices WHERE society_id=%s", (society_id,))
    members = cur.fetchone()['total']
    cur.execute("SELECT COUNT(*) as total FROM notices WHERE society_id=%s AND payment_status='Paid'", (society_id,))
    paid = cur.fetchone()['total']
    cur.execute("SELECT COUNT(*) as total FROM notices WHERE society_id=%s AND payment_status='Pending'", (society_id,))
    pending = cur.fetchone()['total']
    cur.close(); conn.close()
    return {'batches': batches, 'members': members, 'paid': paid, 'pending': pending}

# ── Society Members (WhatsApp directory) ──────────────────────

def upsert_members(society_id, members):
    """Insert or update members from Excel upload. Keyed on (society_id, flat_combo)."""
    conn = get_db()
    cur  = conn.cursor()
    for m in members:
        cur.execute("""
            INSERT INTO society_members (society_id, building_no, flat_no, flat_combo, name, phone, email)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (society_id, flat_combo)
            DO UPDATE SET name=EXCLUDED.name, phone=EXCLUDED.phone,
                          email=EXCLUDED.email, building_no=EXCLUDED.building_no,
                          flat_no=EXCLUDED.flat_no
        """, (society_id, m['building_no'], m['flat_no'], m['flat_combo'],
              m['name'], m['phone'], m.get('email', '')))
    conn.commit()
    cur.close(); conn.close()

def get_members(society_id):
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("""
        SELECT * FROM society_members
        WHERE society_id=%s ORDER BY building_no, flat_no
    """, (society_id,))
    rows = cur.fetchall()
    cur.close(); conn.close()
    return [dict(r) for r in rows]

def get_member_by_flat(society_id, flat_combo):
    """Lookup a member by their flat combination code (e.g. B01-001)."""
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("""
        SELECT * FROM society_members
        WHERE society_id=%s AND UPPER(flat_combo)=UPPER(%s)
    """, (society_id, flat_combo.strip()))
    row = cur.fetchone()
    cur.close(); conn.close()
    return dict(row) if row else None

def delete_all_members(society_id):
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("DELETE FROM society_members WHERE society_id=%s", (society_id,))
    conn.commit()
    cur.close(); conn.close()


init_db()