import sqlite3, os

DB_PATH = os.path.join(os.path.dirname(__file__), "notices.db")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS notice_batches (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_name  TEXT NOT NULL,
            notice_type TEXT DEFAULT '1st',
            issued_date TEXT NOT NULL,
            total       INTEGER DEFAULT 0,
            created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS notices (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id        INTEGER,
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
            created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (batch_id) REFERENCES notice_batches(id)
        );
    """)
    conn.commit()
    conn.close()

def save_batch(batch_name, notice_type, issued_date, members):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO notice_batches (batch_name, notice_type, issued_date, total)
        VALUES (?, ?, ?, ?)
    """, (batch_name, notice_type, issued_date, len(members)))
    batch_id = cur.lastrowid
    for m in members:
        cur.execute("""
            INSERT INTO notices (batch_id, flat_no, ref_no, member_name, amount, notice_type, issued_date, prev_ref_no)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (batch_id, m['flat_no'], m['ref_no'], m['name'], m['amount'], notice_type, issued_date, m.get('prev_ref_no', '')))
    conn.commit()
    conn.close()
    return batch_id

def get_batches():
    conn = get_db()
    rows = conn.execute("""
        SELECT b.*, 
               COUNT(CASE WHEN n.payment_status='Paid' THEN 1 END) as paid_count,
               COUNT(CASE WHEN n.payment_status='Pending' THEN 1 END) as pending_count
        FROM notice_batches b
        LEFT JOIN notices n ON n.batch_id = b.id
        GROUP BY b.id
        ORDER BY b.created_at DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_batch_notices(batch_id):
    conn = get_db()
    rows = conn.execute("""
        SELECT * FROM notices WHERE batch_id = ? ORDER BY flat_no
    """, (batch_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def update_payment(notice_id, status, payment_date, payment_amount, remark):
    conn = get_db()
    conn.execute("""
        UPDATE notices SET payment_status=?, payment_date=?, payment_amount=?, payment_remark=?
        WHERE id=?
    """, (status, payment_date, payment_amount, remark, notice_id))
    conn.commit()
    conn.close()

def get_eligible_for_2nd(batch_id):
    conn = get_db()
    rows = conn.execute("""
        SELECT * FROM notices 
        WHERE batch_id=? AND payment_status='Pending'
        ORDER BY flat_no
    """, (batch_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_paid_members(batch_id):
    conn = get_db()
    rows = conn.execute("""
        SELECT * FROM notices 
        WHERE batch_id=? AND payment_status='Paid'
        ORDER BY payment_date DESC
    """, (batch_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

init_db()
