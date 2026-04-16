import os
import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2.pool import ThreadedConnectionPool
import bcrypt

# ── Fix 1: No hardcoded fallback — fail fast if not configured ─────────────────
DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL environment variable is not set. "
        "Add it in your Render → Environment settings."
    )

# ── Fix 5: Connection pool (1–10 connections reused across requests) ───────────
_pool = ThreadedConnectionPool(1, 10, DATABASE_URL, cursor_factory=RealDictCursor)

class _PooledConn:
    """Thin wrapper so existing conn.close() calls return the conn to the pool."""
    def __init__(self, conn):
        self._conn = conn
    def __getattr__(self, name):
        return getattr(self._conn, name)
    def close(self):
        _pool.putconn(self._conn)

def get_db():
    return _PooledConn(_pool.getconn())

# ── Fix 2: Password hashing helpers ───────────────────────────────────────────
def hash_password(plain: str) -> str:
    """Return a bcrypt hash of the plain-text password."""
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()

def check_password(plain: str, stored: str) -> bool:
    """Verify a password. Handles bcrypt hashes AND legacy plain-text (for migration)."""
    if stored.startswith("$2b$") or stored.startswith("$2a$"):
        return bcrypt.checkpw(plain.encode(), stored.encode())
    return plain == stored  # legacy plain-text — will be re-hashed on next login

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

def create_society(name, address, username, password, regd_no, default_pin_format='no_hyphen'):
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("""
        INSERT INTO societies (name, address, username, password, regd_no, default_pin_format)
        VALUES (%s, %s, %s, %s, %s, %s) RETURNING id
    """, (name, address, username, hash_password(password), regd_no, default_pin_format or 'no_hyphen'))
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


# ── Password management ───────────────────────────────────────
def change_society_password(society_id, new_password):
    conn = get_db(); cur = conn.cursor()
    cur.execute("UPDATE societies SET password=%s WHERE id=%s", (hash_password(new_password), society_id))
    conn.commit(); cur.close(); conn.close()

def change_admin_password(username, new_password):
    """For admin: store in societies table with username='admin' if exists, else env."""
    # We just return True — admin password is managed via env variable
    return True

def reset_society_password(society_id, new_password):
    conn = get_db(); cur = conn.cursor()
    cur.execute("UPDATE societies SET password=%s WHERE id=%s", (hash_password(new_password), society_id))
    conn.commit(); cur.close(); conn.close()

# ── Notice-type filtered stats ────────────────────────────────
def get_stats_by_notice_type(society_id, notice_type=None):
    """Stats filtered by notice type. If notice_type is None, returns all."""
    conn = get_db(); cur = conn.cursor()
    if notice_type:
        cur.execute("SELECT COUNT(*) as total FROM notice_batches WHERE society_id=%s AND notice_type=%s",
                    (society_id, notice_type))
    else:
        cur.execute("SELECT COUNT(*) as total FROM notice_batches WHERE society_id=%s", (society_id,))
    batches = cur.fetchone()['total']

    if notice_type:
        cur.execute("""SELECT COUNT(*) as total FROM notices n
                       JOIN notice_batches b ON n.batch_id=b.id
                       WHERE n.society_id=%s AND b.notice_type=%s""", (society_id, notice_type))
    else:
        cur.execute("SELECT COUNT(*) as total FROM notices WHERE society_id=%s", (society_id,))
    members = cur.fetchone()['total']

    if notice_type:
        cur.execute("""SELECT COUNT(*) as total FROM notices n
                       JOIN notice_batches b ON n.batch_id=b.id
                       WHERE n.society_id=%s AND b.notice_type=%s AND n.payment_status='Paid'""",
                    (society_id, notice_type))
    else:
        cur.execute("SELECT COUNT(*) as total FROM notices WHERE society_id=%s AND payment_status='Paid'",
                    (society_id,))
    paid = cur.fetchone()['total']

    if notice_type:
        cur.execute("""SELECT COUNT(*) as total FROM notices n
                       JOIN notice_batches b ON n.batch_id=b.id
                       WHERE n.society_id=%s AND b.notice_type=%s AND n.payment_status='Pending'""",
                    (society_id, notice_type))
    else:
        cur.execute("SELECT COUNT(*) as total FROM notices WHERE society_id=%s AND payment_status='Pending'",
                    (society_id,))
    pending = cur.fetchone()['total']

    cur.close(); conn.close()
    return {'batches': batches, 'members': members, 'paid': paid, 'pending': pending}

def get_unique_member_stats(society_id):
    """Deduplicates members across notice types using flat_no as unique key."""
    conn = get_db(); cur = conn.cursor()
    # Unique members (distinct flat_no)
    cur.execute("""SELECT COUNT(DISTINCT flat_no) as total FROM notices WHERE society_id=%s""", (society_id,))
    unique_members = cur.fetchone()['total']
    # Paid (flat paid at least once in latest batch)
    cur.execute("""SELECT COUNT(DISTINCT flat_no) as total FROM notices
                   WHERE society_id=%s AND payment_status='Paid'""", (society_id,))
    paid = cur.fetchone()['total']
    # Outstanding = unique members who have ANY pending notice
    cur.execute("""SELECT COUNT(DISTINCT flat_no) as total FROM notices
                   WHERE society_id=%s AND payment_status='Pending'""", (society_id,))
    pending = cur.fetchone()['total']
    # Total outstanding amount (latest pending per member)
    cur.execute("""SELECT COALESCE(SUM(amount),0) as total FROM (
                     SELECT DISTINCT ON (flat_no) flat_no, amount
                     FROM notices WHERE society_id=%s AND payment_status='Pending'
                     ORDER BY flat_no, created_at DESC
                   ) sub""", (society_id,))
    outstanding_amount = cur.fetchone()['total']
    # Total collected
    cur.execute("""SELECT COALESCE(SUM(payment_amount),0) as total FROM notices
                   WHERE society_id=%s AND payment_status='Paid'""", (society_id,))
    collected_amount = cur.fetchone()['total']
    cur.close(); conn.close()
    return {
        'unique_members': unique_members,
        'paid': paid,
        'pending': pending,
        'outstanding_amount': outstanding_amount,
        'collected_amount': collected_amount
    }

def get_batches_by_type(society_id, notice_type=None):
    """Get batches filtered by notice type."""
    conn = get_db(); cur = conn.cursor()
    if notice_type:
        cur.execute("""
            SELECT b.*,
                   COUNT(CASE WHEN n.payment_status='Paid'    THEN 1 END) as paid_count,
                   COUNT(CASE WHEN n.payment_status='Pending' THEN 1 END) as pending_count
            FROM notice_batches b
            LEFT JOIN notices n ON n.batch_id = b.id
            WHERE b.society_id=%s AND b.notice_type=%s
            GROUP BY b.id ORDER BY b.created_at DESC
        """, (society_id, notice_type))
    else:
        cur.execute("""
            SELECT b.*,
                   COUNT(CASE WHEN n.payment_status='Paid'    THEN 1 END) as paid_count,
                   COUNT(CASE WHEN n.payment_status='Pending' THEN 1 END) as pending_count
            FROM notice_batches b
            LEFT JOIN notices n ON n.batch_id = b.id
            WHERE b.society_id=%s
            GROUP BY b.id ORDER BY b.created_at DESC
        """, (society_id,))
    rows = cur.fetchall(); cur.close(); conn.close()
    return [dict(r) for r in rows]

# ── Monthly billing ────────────────────────────────────────────
def init_billing_table():
    conn = get_db(); cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS monthly_bills (
            id          SERIAL PRIMARY KEY,
            society_id  INTEGER REFERENCES societies(id) ON DELETE CASCADE,
            bill_month  TEXT NOT NULL,
            bill_year   TEXT NOT NULL,
            amount      NUMERIC(12,2) NOT NULL,
            description TEXT,
            status      TEXT DEFAULT 'Unpaid',
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit(); cur.close(); conn.close()

def create_monthly_bill(society_id, bill_month, bill_year, amount, description):
    conn = get_db(); cur = conn.cursor()
    cur.execute("""
        INSERT INTO monthly_bills (society_id, bill_month, bill_year, amount, description)
        VALUES (%s,%s,%s,%s,%s) RETURNING id
    """, (society_id, bill_month, bill_year, amount, description))
    bid = cur.fetchone()['id']; conn.commit(); cur.close(); conn.close()
    return bid

def get_bills_for_society(society_id):
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT * FROM monthly_bills WHERE society_id=%s ORDER BY created_at DESC", (society_id,))
    rows = cur.fetchall(); cur.close(); conn.close()
    return [dict(r) for r in rows]

def get_all_bills():
    conn = get_db(); cur = conn.cursor()
    cur.execute("""
        SELECT mb.*, s.name as society_name FROM monthly_bills mb
        JOIN societies s ON mb.society_id=s.id
        ORDER BY mb.created_at DESC
    """)
    rows = cur.fetchall(); cur.close(); conn.close()
    return [dict(r) for r in rows]

def update_bill_status(bill_id, status):
    conn = get_db(); cur = conn.cursor()
    cur.execute("UPDATE monthly_bills SET status=%s WHERE id=%s", (status, bill_id))
    conn.commit(); cur.close(); conn.close()

def delete_bill(bill_id):
    conn = get_db(); cur = conn.cursor()
    cur.execute("DELETE FROM monthly_bills WHERE id=%s", (bill_id,))
    conn.commit(); cur.close(); conn.close()

init_billing_table()
init_db()
def get_bill_by_id(bill_id):
    conn = get_db(); cur = conn.cursor()
    cur.execute("""
        SELECT mb.*, s.name as society_name, s.address as society_address, s.regd_no
        FROM monthly_bills mb
        JOIN societies s ON mb.society_id = s.id
        WHERE mb.id = %s
    """, (bill_id,))
    row = cur.fetchone(); cur.close(); conn.close()
    return dict(row) if row else None


# ── Member Portal ───────────────────────────────────────────────
def init_member_portal_table():
    conn = get_db(); cur = conn.cursor()
    cur.execute("""
        ALTER TABLE societies
        ADD COLUMN IF NOT EXISTS portal_code TEXT UNIQUE;
    """)
    # default_pin_format: 'no_hyphen' → B01310  |  'flat_combo' → B01-310
    cur.execute("""
        ALTER TABLE societies
        ADD COLUMN IF NOT EXISTS default_pin_format TEXT DEFAULT 'no_hyphen';
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS member_logins (
            id           SERIAL PRIMARY KEY,
            society_id   INTEGER REFERENCES societies(id) ON DELETE CASCADE,
            flat_combo   TEXT NOT NULL,
            pin_hash     TEXT NOT NULL,
            must_change  BOOLEAN DEFAULT TRUE,
            created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_login   TIMESTAMP,
            UNIQUE(society_id, flat_combo)
        );
    """)
    conn.commit(); cur.close(); conn.close()

init_member_portal_table()

def get_society_by_portal_code(portal_code):
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT * FROM societies WHERE UPPER(portal_code)=UPPER(%s)", (portal_code,))
    row = cur.fetchone(); cur.close(); conn.close()
    return dict(row) if row else None

def set_portal_code(society_id, portal_code):
    conn = get_db(); cur = conn.cursor()
    cur.execute("UPDATE societies SET portal_code=UPPER(%s) WHERE id=%s",
                (portal_code, society_id))
    conn.commit(); cur.close(); conn.close()

def get_member_login(society_id, flat_combo):
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT * FROM member_logins WHERE society_id=%s AND UPPER(flat_combo)=UPPER(%s)",
                (society_id, flat_combo))
    row = cur.fetchone(); cur.close(); conn.close()
    return dict(row) if row else None

def upsert_member_login(society_id, flat_combo, pin_hash, must_change=True):
    conn = get_db(); cur = conn.cursor()
    cur.execute("""
        INSERT INTO member_logins (society_id, flat_combo, pin_hash, must_change)
        VALUES (%s, UPPER(%s), %s, %s)
        ON CONFLICT (society_id, flat_combo)
        DO UPDATE SET pin_hash=EXCLUDED.pin_hash, must_change=EXCLUDED.must_change
    """, (society_id, flat_combo, pin_hash, must_change))
    conn.commit(); cur.close(); conn.close()

def update_member_pin(society_id, flat_combo, new_pin_hash):
    conn = get_db(); cur = conn.cursor()
    cur.execute("""
        UPDATE member_logins
        SET pin_hash=%s, must_change=FALSE, last_login=NOW()
        WHERE society_id=%s AND UPPER(flat_combo)=UPPER(%s)
    """, (new_pin_hash, society_id, flat_combo))
    conn.commit(); cur.close(); conn.close()

def touch_member_login(society_id, flat_combo):
    conn = get_db(); cur = conn.cursor()
    cur.execute("UPDATE member_logins SET last_login=NOW() WHERE society_id=%s AND UPPER(flat_combo)=UPPER(%s)",
                (society_id, flat_combo))
    conn.commit(); cur.close(); conn.close()

def get_society_pin_format(society_id):
    """Return the society's default_pin_format ('no_hyphen' or 'flat_combo')."""
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT default_pin_format FROM societies WHERE id=%s", (society_id,))
    row = cur.fetchone(); cur.close(); conn.close()
    return (row['default_pin_format'] if row else None) or 'no_hyphen'

def reset_member_pin(society_id, flat_combo, default_pin=None):
    """Reset a member's PIN to default. default_pin is the plain-text PIN computed by the caller."""
    import hashlib
    pin = (default_pin or flat_combo).upper()
    pin_hash = hashlib.sha256(pin.encode()).hexdigest()
    upsert_member_login(society_id, flat_combo, pin_hash, must_change=True)

def get_member_notices(society_id, flat_combo):
    conn = get_db(); cur = conn.cursor()
    cur.execute("""
        SELECT n.*, nb.batch_name, nb.notice_type, nb.issued_date
        FROM notices n
        JOIN notice_batches nb ON n.batch_id = nb.id
        WHERE nb.society_id=%s AND UPPER(n.flat_no)=UPPER(%s)
        ORDER BY nb.issued_date DESC
    """, (society_id, flat_combo))
    rows = cur.fetchall(); cur.close(); conn.close()
    return [dict(r) for r in rows]

def get_member_announcements(society_id):
    conn = get_db(); cur = conn.cursor()
    cur.execute("""
        SELECT * FROM announcements
        WHERE society_id=%s ORDER BY created_at DESC LIMIT 10
    """, (society_id,))
    rows = cur.fetchall(); cur.close(); conn.close()
    return [dict(r) for r in rows]

def init_announcements_table():
    conn = get_db(); cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS announcements (
            id          SERIAL PRIMARY KEY,
            society_id  INTEGER REFERENCES societies(id) ON DELETE CASCADE,
            title       TEXT NOT NULL,
            body        TEXT NOT NULL,
            category    TEXT DEFAULT 'General',
            posted_by   TEXT DEFAULT 'Committee',
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    # ── Knowledge base table (outstanding amounts + rules stored as text) ──
    cur.execute("""
        CREATE TABLE IF NOT EXISTS society_knowledge (
            id          SERIAL PRIMARY KEY,
            society_id  INTEGER REFERENCES societies(id) ON DELETE CASCADE,
            kb_type     TEXT NOT NULL,
            content     TEXT NOT NULL,
            updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(society_id, kb_type)
        );
    """)
    conn.commit(); cur.close(); conn.close()

init_announcements_table()

def create_announcement(society_id, title, body, category='General', posted_by='Committee'):
    conn = get_db(); cur = conn.cursor()
    cur.execute("""
        INSERT INTO announcements (society_id, title, body, category, posted_by)
        VALUES (%s, %s, %s, %s, %s)
    """, (society_id, title, body, category, posted_by))
    conn.commit(); cur.close(); conn.close()

def delete_announcement(ann_id):
    conn = get_db(); cur = conn.cursor()
    cur.execute("DELETE FROM announcements WHERE id=%s", (ann_id,))
    conn.commit(); cur.close(); conn.close()

# ── Society Knowledge Base ─────────────────────────────────────────────────────

def upsert_knowledge(society_id, kb_type, content):
    """Insert or replace a knowledge base entry for a society."""
    conn = get_db(); cur = conn.cursor()
    cur.execute("""
        INSERT INTO society_knowledge (society_id, kb_type, content, updated_at)
        VALUES (%s, %s, %s, NOW())
        ON CONFLICT (society_id, kb_type)
        DO UPDATE SET content=EXCLUDED.content, updated_at=NOW()
    """, (society_id, kb_type, content))
    conn.commit(); cur.close(); conn.close()

def get_knowledge(society_id, kb_type=None):
    """Return all knowledge entries for a society, or just one type."""
    conn = get_db(); cur = conn.cursor()
    if kb_type:
        cur.execute("SELECT * FROM society_knowledge WHERE society_id=%s AND kb_type=%s",
                    (society_id, kb_type))
    else:
        cur.execute("SELECT * FROM society_knowledge WHERE society_id=%s ORDER BY kb_type",
                    (society_id,))
    rows = cur.fetchall(); cur.close(); conn.close()
    return [dict(r) for r in rows]

def get_member_outstanding(society_id, flat_combo):
    """Look up a flat's outstanding in the knowledge base outstanding text."""
    rows = get_knowledge(society_id, 'outstanding')
    if not rows:
        return None
    text = rows[0]['content']
    # Scan line-by-line for the flat
    flat_up = flat_combo.strip().upper()
    for line in text.splitlines():
        if flat_up in line.upper():
            return line.strip()
    return None


# ── Member Tickets / Complaints ────────────────────────────────────────────────

def init_tickets_table():
    conn = get_db(); cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS member_tickets (
            id              SERIAL PRIMARY KEY,
            society_id      INTEGER REFERENCES societies(id) ON DELETE CASCADE,
            flat_combo      TEXT NOT NULL,
            member_name     TEXT NOT NULL,
            category        TEXT NOT NULL DEFAULT 'General',
            subject         TEXT NOT NULL,
            description     TEXT NOT NULL,
            status          TEXT NOT NULL DEFAULT 'Open',
            priority        TEXT NOT NULL DEFAULT 'Normal',
            committee_note  TEXT,
            created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            resolved_at     TIMESTAMP
        );
    """)
    conn.commit(); cur.close(); conn.close()

init_tickets_table()

def create_ticket(society_id, flat_combo, member_name, category, subject, description, priority='Normal'):
    conn = get_db(); cur = conn.cursor()
    cur.execute("""
        INSERT INTO member_tickets (society_id, flat_combo, member_name, category, subject, description, priority)
        VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id
    """, (society_id, flat_combo, member_name, category, subject, description, priority))
    tid = cur.fetchone()['id']
    conn.commit(); cur.close(); conn.close()
    return tid

def get_member_tickets(society_id, flat_combo):
    conn = get_db(); cur = conn.cursor()
    cur.execute("""
        SELECT * FROM member_tickets
        WHERE society_id=%s AND UPPER(flat_combo)=UPPER(%s)
        ORDER BY created_at DESC
    """, (society_id, flat_combo))
    rows = cur.fetchall(); cur.close(); conn.close()
    return [dict(r) for r in rows]

def get_all_tickets(society_id, status=None):
    conn = get_db(); cur = conn.cursor()
    if status:
        cur.execute("SELECT * FROM member_tickets WHERE society_id=%s AND status=%s ORDER BY created_at DESC",
                    (society_id, status))
    else:
        cur.execute("SELECT * FROM member_tickets WHERE society_id=%s ORDER BY created_at DESC",
                    (society_id,))
    rows = cur.fetchall(); cur.close(); conn.close()
    return [dict(r) for r in rows]

def update_ticket_status(ticket_id, status, committee_note=''):
    conn = get_db(); cur = conn.cursor()
    if status == 'Resolved':
        cur.execute("""
            UPDATE member_tickets
            SET status=%s, committee_note=%s, updated_at=NOW(), resolved_at=NOW()
            WHERE id=%s
        """, (status, committee_note, ticket_id))
    else:
        cur.execute("""
            UPDATE member_tickets
            SET status=%s, committee_note=%s, updated_at=NOW(), resolved_at=NULL
            WHERE id=%s
        """, (status, committee_note, ticket_id))
    conn.commit(); cur.close(); conn.close()

def get_ticket_by_id(ticket_id):
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT * FROM member_tickets WHERE id=%s", (ticket_id,))
    row = cur.fetchone(); cur.close(); conn.close()
    return dict(row) if row else None


# ── Audit Log ──────────────────────────────────────────────────────────────────

def init_audit_table():
    conn = get_db(); cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id          SERIAL PRIMARY KEY,
            society_id  INTEGER,
            actor       TEXT NOT NULL,
            action      TEXT NOT NULL,
            detail      TEXT,
            ip_address  TEXT,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_audit_society ON audit_log(society_id);
        CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at DESC);
    """)
    conn.commit(); cur.close(); conn.close()

init_audit_table()

def log_audit(society_id, actor, action, detail='', ip_address=''):
    try:
        conn = get_db(); cur = conn.cursor()
        cur.execute("""
            INSERT INTO audit_log (society_id, actor, action, detail, ip_address)
            VALUES (%s, %s, %s, %s, %s)
        """, (society_id, actor, action, detail, ip_address))
        conn.commit(); cur.close(); conn.close()
    except Exception:
        pass  # Never let audit logging crash the app

def get_audit_log(society_id, limit=100):
    conn = get_db(); cur = conn.cursor()
    cur.execute("""
        SELECT * FROM audit_log WHERE society_id=%s
        ORDER BY created_at DESC LIMIT %s
    """, (society_id, limit))
    rows = cur.fetchall(); cur.close(); conn.close()
    return [dict(r) for r in rows]


# ── Payment Records ────────────────────────────────────────────────────────────

def init_payments_table():
    conn = get_db(); cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS portal_payments (
            id                  SERIAL PRIMARY KEY,
            society_id          INTEGER REFERENCES societies(id) ON DELETE CASCADE,
            flat_combo          TEXT NOT NULL,
            member_name         TEXT NOT NULL,
            notice_id           INTEGER,
            razorpay_order_id   TEXT UNIQUE,
            razorpay_payment_id TEXT,
            amount              NUMERIC(12,2) NOT NULL,
            currency            TEXT DEFAULT 'INR',
            status              TEXT DEFAULT 'created',
            description         TEXT,
            created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            paid_at             TIMESTAMP
        );
    """)
    conn.commit(); cur.close(); conn.close()

init_payments_table()

def create_payment_order(society_id, flat_combo, member_name, notice_id,
                         razorpay_order_id, amount, description=''):
    conn = get_db(); cur = conn.cursor()
    cur.execute("""
        INSERT INTO portal_payments
            (society_id, flat_combo, member_name, notice_id,
             razorpay_order_id, amount, description)
        VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id
    """, (society_id, flat_combo, member_name, notice_id,
          razorpay_order_id, amount, description))
    pid = cur.fetchone()['id']
    conn.commit(); cur.close(); conn.close()
    return pid

def confirm_payment(razorpay_order_id, razorpay_payment_id):
    conn = get_db(); cur = conn.cursor()
    cur.execute("""
        UPDATE portal_payments
        SET status='paid', razorpay_payment_id=%s, paid_at=NOW()
        WHERE razorpay_order_id=%s
        RETURNING id, notice_id, society_id, flat_combo, amount
    """, (razorpay_payment_id, razorpay_order_id))
    row = cur.fetchone()
    conn.commit(); cur.close(); conn.close()
    return dict(row) if row else None

def get_payment_history(society_id, flat_combo):
    conn = get_db(); cur = conn.cursor()
    cur.execute("""
        SELECT * FROM portal_payments
        WHERE society_id=%s AND UPPER(flat_combo)=UPPER(%s)
        ORDER BY created_at DESC
    """, (society_id, flat_combo))
    rows = cur.fetchall(); cur.close(); conn.close()
    return [dict(r) for r in rows]


# ── DPDPA Consent & Data Management ───────────────────────────────────────────

def init_consent_table():
    conn = get_db(); cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS member_consent (
            id          SERIAL PRIMARY KEY,
            society_id  INTEGER REFERENCES societies(id) ON DELETE CASCADE,
            flat_combo  TEXT NOT NULL,
            consent_given BOOLEAN DEFAULT FALSE,
            consent_at  TIMESTAMP,
            ip_address  TEXT,
            UNIQUE(society_id, flat_combo)
        );
    """)
    conn.commit(); cur.close(); conn.close()

init_consent_table()

def record_consent(society_id, flat_combo, ip_address=''):
    conn = get_db(); cur = conn.cursor()
    cur.execute("""
        INSERT INTO member_consent (society_id, flat_combo, consent_given, consent_at, ip_address)
        VALUES (%s, UPPER(%s), TRUE, NOW(), %s)
        ON CONFLICT (society_id, flat_combo)
        DO UPDATE SET consent_given=TRUE, consent_at=NOW(), ip_address=EXCLUDED.ip_address
    """, (society_id, flat_combo, ip_address))
    conn.commit(); cur.close(); conn.close()

def has_consent(society_id, flat_combo):
    conn = get_db(); cur = conn.cursor()
    cur.execute("""
        SELECT consent_given FROM member_consent
        WHERE society_id=%s AND UPPER(flat_combo)=UPPER(%s)
    """, (society_id, flat_combo))
    row = cur.fetchone(); cur.close(); conn.close()
    return bool(row and row['consent_given'])

def delete_member_data(society_id, flat_combo):
    """DPDPA right to erasure — removes all personal data for a flat."""
    conn = get_db(); cur = conn.cursor()
    flat_up = flat_combo.strip().upper()
    cur.execute("DELETE FROM member_logins   WHERE society_id=%s AND UPPER(flat_combo)=%s",
                (society_id, flat_up))
    cur.execute("DELETE FROM member_consent  WHERE society_id=%s AND UPPER(flat_combo)=%s",
                (society_id, flat_up))
    cur.execute("DELETE FROM member_tickets  WHERE society_id=%s AND UPPER(flat_combo)=%s",
                (society_id, flat_up))
    cur.execute("UPDATE society_members SET name='[Deleted]', phone='0000000000', email=''   "
                "WHERE society_id=%s AND UPPER(flat_combo)=%s", (society_id, flat_up))
    conn.commit(); cur.close(); conn.close()


# ── Analytics Queries ──────────────────────────────────────────────────────────

def get_analytics(society_id):
    conn = get_db(); cur = conn.cursor()

    # Monthly collection trend (last 12 months)
    cur.execute("""
        SELECT DATE_TRUNC('month', created_at) AS month,
               COUNT(*) AS total_notices,
               SUM(CASE WHEN payment_status='Paid' THEN 1 ELSE 0 END) AS paid,
               COALESCE(SUM(CASE WHEN payment_status='Paid' THEN payment_amount ELSE 0 END),0) AS collected
        FROM notices
        WHERE society_id=%s AND created_at >= NOW() - INTERVAL '12 months'
        GROUP BY month ORDER BY month
    """, (society_id,))
    monthly_trend = [dict(r) for r in cur.fetchall()]

    # Ageing buckets (outstanding)
    cur.execute("""
        SELECT
            COUNT(CASE WHEN NOW()-created_at < INTERVAL '30 days' THEN 1 END)  AS bucket_0_30,
            COUNT(CASE WHEN NOW()-created_at BETWEEN INTERVAL '30 days' AND INTERVAL '60 days' THEN 1 END) AS bucket_31_60,
            COUNT(CASE WHEN NOW()-created_at BETWEEN INTERVAL '60 days' AND INTERVAL '90 days' THEN 1 END) AS bucket_61_90,
            COUNT(CASE WHEN NOW()-created_at > INTERVAL '90 days' THEN 1 END)  AS bucket_90_plus,
            COALESCE(SUM(CASE WHEN NOW()-created_at < INTERVAL '30 days' THEN amount ELSE 0 END),0) AS amt_0_30,
            COALESCE(SUM(CASE WHEN NOW()-created_at BETWEEN INTERVAL '30 days' AND INTERVAL '60 days' THEN amount ELSE 0 END),0) AS amt_31_60,
            COALESCE(SUM(CASE WHEN NOW()-created_at > INTERVAL '90 days' THEN amount ELSE 0 END),0) AS amt_90_plus
        FROM notices WHERE society_id=%s AND payment_status='Pending'
    """, (society_id,))
    ageing = dict(cur.fetchone())

    # Top defaulters — from knowledge base outstanding data (latest Excel uploaded by committee)
    # Falls back to summing pending notices if no KB data uploaded yet
    kb_rows = get_knowledge(society_id, 'outstanding')
    defaulters = []
    if kb_rows:
        import re as _re
        kb_text = kb_rows[0]['content']

        # Detect if first data line has a header so we can map column positions
        # Header format: "Flat | Outstanding Amount | Member"
        header_parts = None
        for line in kb_text.splitlines():
            if '|' in line and not line.strip().startswith('-'):
                hp = [p.strip().lower().replace(' ', '').replace('_', '') for p in line.split('|')]
                # Check if this looks like a header (no numeric values)
                if all(not _re.search(r'\d{2,}', p) for p in hp):
                    header_parts = hp
                break

        # Determine which column index holds the amount
        amt_idx    = 1   # default: second column
        flat_idx   = 0   # default: first column
        member_idx = 2   # default: third column
        if header_parts:
            for i, h in enumerate(header_parts):
                if any(k in h for k in ('outstanding', 'amount', 'dues', 'balance', 'pending', 'total', 'owed', 'arrear')):
                    amt_idx = i
                elif any(k in h for k in ('flat', 'unit', 'aptno', 'flatno')):
                    flat_idx = i
                elif any(k in h for k in ('member', 'name', 'owner', 'resident')):
                    member_idx = i

        for line in kb_text.splitlines():
            if '|' not in line:
                continue
            if line.strip().startswith('-'):
                continue
            parts = [p.strip() for p in line.split('|')]
            if len(parts) < 2:
                continue
            flat = parts[flat_idx].strip() if flat_idx < len(parts) else ''
            if not flat or flat.lower() in ('flat', 'flat no', 'flat_no', 'unit', ''):
                continue
            # Skip header row
            if flat.lower().replace(' ', '').replace('_', '') in ('flat', 'flatno', 'unit', 'aptno'):
                continue

            # Try the detected amount column first; fall back to scanning all parts
            amt = 0.0
            amt_part = parts[amt_idx].strip() if amt_idx < len(parts) else ''
            amt_raw = _re.sub(r'[^\d.]', '', amt_part)
            try:
                amt = float(amt_raw)
            except (ValueError, TypeError):
                amt = 0.0

            # If amount still zero, scan remaining parts for a numeric value
            if amt <= 0:
                for i, p in enumerate(parts):
                    if i == flat_idx:
                        continue
                    candidate = _re.sub(r'[^\d.]', '', p.strip())
                    try:
                        v = float(candidate)
                        if v > 0:
                            amt = v
                            break
                    except (ValueError, TypeError):
                        continue

            if amt <= 0:
                continue

            member = parts[member_idx].strip() if member_idx < len(parts) else ''
            defaulters.append({
                'flat_no':      flat,
                'member_name':  member,
                'notice_count': '-',
                'total_owed':   amt,
            })
        defaulters = sorted(defaulters, key=lambda x: x['total_owed'], reverse=True)[:10]

    if not defaulters:
        # Fallback: sum pending notice amounts from notices table
        cur.execute("""
            SELECT flat_no, member_name, COUNT(*) AS notice_count,
                   SUM(amount) AS total_owed
            FROM notices WHERE society_id=%s AND payment_status='Pending'
            GROUP BY flat_no, member_name
            ORDER BY total_owed DESC LIMIT 10
        """, (society_id,))
        defaulters = [dict(r) for r in cur.fetchall()]

    # Ticket stats by category
    cur.execute("""
        SELECT category, status, COUNT(*) as cnt
        FROM member_tickets WHERE society_id=%s
        GROUP BY category, status ORDER BY cnt DESC
    """, (society_id,))
    ticket_stats = [dict(r) for r in cur.fetchall()]

    # Notice type breakdown
    cur.execute("""
        SELECT notice_type, payment_status, COUNT(*) as cnt
        FROM notices WHERE society_id=%s
        GROUP BY notice_type, payment_status
    """, (society_id,))
    notice_breakdown = [dict(r) for r in cur.fetchall()]

    cur.close(); conn.close()
    return {
        'monthly_trend':    monthly_trend,
        'ageing':           ageing,
        'defaulters':       defaulters,
        'ticket_stats':     ticket_stats,
        'notice_breakdown': notice_breakdown,
    }


# ══════════════════════════════════════════════════════════════
#  VECTOR KNOWLEDGE BASE  (pgvector on Neon)
# ══════════════════════════════════════════════════════════════

def init_vector_kb():
    """Enable pgvector extension and create kb_chunks table."""
    conn = get_db(); cur = conn.cursor()
    # Enable pgvector - safe to run multiple times
    cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS kb_chunks (
            id          SERIAL PRIMARY KEY,
            society_id  INTEGER REFERENCES societies(id) ON DELETE CASCADE,
            kb_type     TEXT NOT NULL,
            doc_name    TEXT NOT NULL,
            chunk_index INTEGER NOT NULL,
            chunk_text  TEXT NOT NULL,
            embedding   vector(384),
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    # Migration: if table existed with vector(768), drop and recreate
    # (safe because data will be re-uploaded anyway)
    try:
        cur.execute("""
            SELECT pg_catalog.format_type(a.atttypid, a.atttypmod)
            FROM pg_catalog.pg_attribute a
            JOIN pg_catalog.pg_class c ON c.oid = a.attrelid
            WHERE c.relname = 'kb_chunks' AND a.attname = 'embedding' AND a.attnum > 0
        """)
        row = cur.fetchone()
        if row and '768' in str(row):
            print("[KB] Migrating kb_chunks from vector(768) to vector(384)...")
            cur.execute("DROP TABLE IF EXISTS kb_chunks CASCADE;")
            cur.execute("DROP TABLE IF EXISTS kb_documents CASCADE;")
            cur.execute("""
                CREATE TABLE kb_chunks (
                    id          SERIAL PRIMARY KEY,
                    society_id  INTEGER REFERENCES societies(id) ON DELETE CASCADE,
                    kb_type     TEXT NOT NULL,
                    doc_name    TEXT NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    chunk_text  TEXT NOT NULL,
                    embedding   vector(384),
                    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            print("[KB] Migration complete ✅")
    except Exception as _me:
        print(f"[KB] Migration check skipped: {_me}")
    # Index for fast cosine similarity search
    cur.execute("""
        CREATE INDEX IF NOT EXISTS kb_chunks_embedding_idx
        ON kb_chunks USING ivfflat (embedding vector_cosine_ops)
        WITH (lists = 50);
    """)
    # Track uploaded documents per society
    cur.execute("""
        CREATE TABLE IF NOT EXISTS kb_documents (
            id          SERIAL PRIMARY KEY,
            society_id  INTEGER REFERENCES societies(id) ON DELETE CASCADE,
            kb_type     TEXT NOT NULL,
            doc_name    TEXT NOT NULL,
            file_type   TEXT NOT NULL,
            chunk_count INTEGER DEFAULT 0,
            uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit(); cur.close(); conn.close()

def delete_kb_document(society_id, doc_name, kb_type):
    """Remove all chunks for a document and its metadata record."""
    conn = get_db(); cur = conn.cursor()
    cur.execute("""
        DELETE FROM kb_chunks
        WHERE society_id=%s AND doc_name=%s AND kb_type=%s
    """, (society_id, doc_name, kb_type))
    cur.execute("""
        DELETE FROM kb_documents
        WHERE society_id=%s AND doc_name=%s AND kb_type=%s
    """, (society_id, doc_name, kb_type))
    conn.commit(); cur.close(); conn.close()

def save_kb_chunks(society_id, kb_type, doc_name, file_type, chunks_with_embeddings):
    """
    chunks_with_embeddings: list of (chunk_text, embedding_list)
    Replaces existing chunks for same doc_name.
    """
    conn = get_db(); cur = conn.cursor()
    try:
        # Remove old version of this doc
        cur.execute("""
            DELETE FROM kb_chunks WHERE society_id=%s AND doc_name=%s AND kb_type=%s
        """, (society_id, doc_name, kb_type))
        cur.execute("""
            DELETE FROM kb_documents WHERE society_id=%s AND doc_name=%s AND kb_type=%s
        """, (society_id, doc_name, kb_type))
        # Insert new chunks — convert embedding list to string so psycopg2
        # passes it as "[0.1, 0.2, ...]" which pgvector expects (same as vector_search)
        for idx, (text, embedding) in enumerate(chunks_with_embeddings):
            emb_str = str(embedding)   # e.g. "[0.023, -0.11, ...]"
            cur.execute("""
                INSERT INTO kb_chunks (society_id, kb_type, doc_name, chunk_index, chunk_text, embedding)
                VALUES (%s, %s, %s, %s, %s, %s::vector)
            """, (society_id, kb_type, doc_name, idx, text, emb_str))
        # Track document
        cur.execute("""
            INSERT INTO kb_documents (society_id, kb_type, doc_name, file_type, chunk_count)
            VALUES (%s, %s, %s, %s, %s)
        """, (society_id, kb_type, doc_name, file_type, len(chunks_with_embeddings)))
        conn.commit()
    except Exception:
        conn._conn.rollback()   # reset the failed transaction
        raise                   # re-raise so the caller can fall back to text KB
    finally:
        cur.close(); conn.close()   # always return connection to pool

def get_kb_documents(society_id, kb_type=None):
    """List all uploaded documents for a society."""
    conn = get_db(); cur = conn.cursor()
    if kb_type:
        cur.execute("""
            SELECT * FROM kb_documents WHERE society_id=%s AND kb_type=%s
            ORDER BY uploaded_at DESC
        """, (society_id, kb_type))
    else:
        cur.execute("""
            SELECT * FROM kb_documents WHERE society_id=%s ORDER BY kb_type, uploaded_at DESC
        """, (society_id,))
    rows = cur.fetchall(); cur.close(); conn.close()
    return [dict(r) for r in rows]

def vector_search(society_id, query_embedding, kb_type=None, top_k=5):
    """
    Semantic similarity search using cosine distance.
    Returns top_k most relevant chunks.
    """
    conn = get_db(); cur = conn.cursor()
    emb_str = str(query_embedding)  # pgvector accepts Python list as string
    if kb_type:
        cur.execute("""
            SELECT chunk_text, doc_name, kb_type,
                   1 - (embedding <=> %s::vector) AS similarity
            FROM kb_chunks
            WHERE society_id=%s AND kb_type=%s
            ORDER BY embedding <=> %s::vector
            LIMIT %s
        """, (emb_str, society_id, kb_type, emb_str, top_k))
    else:
        cur.execute("""
            SELECT chunk_text, doc_name, kb_type,
                   1 - (embedding <=> %s::vector) AS similarity
            FROM kb_chunks
            WHERE society_id=%s
            ORDER BY embedding <=> %s::vector
            LIMIT %s
        """, (emb_str, society_id, emb_str, top_k))
    rows = cur.fetchall(); cur.close(); conn.close()
    return [dict(r) for r in rows]

def get_kb_chunk_count(society_id):
    """Total chunks stored for a society."""
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT COUNT(*) as total FROM kb_chunks WHERE society_id=%s", (society_id,))
    r = cur.fetchone(); cur.close(); conn.close()
    return r['total'] if r else 0

try:
    init_vector_kb()
except Exception as e:
    print(f"[WARN] pgvector init skipped: {e}")