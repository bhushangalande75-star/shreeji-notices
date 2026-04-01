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
        CREATE TABLE IF NOT EXISTS notice_batches (
            id          SERIAL PRIMARY KEY,
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
    conn.commit()
    cur.close()
    conn.close()

def save_batch(batch_name, notice_type, issued_date, members):
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("""
        INSERT INTO notice_batches (batch_name, notice_type, issued_date, total)
        VALUES (%s, %s, %s, %s) RETURNING id
    """, (batch_name, notice_type, issued_date, len(members)))
    batch_id = cur.fetchone()['id']
    for m in members:
        cur.execute("""
            INSERT INTO notices (batch_id, flat_no, ref_no, member_name, amount, notice_type, issued_date, prev_ref_no)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (batch_id, m['flat_no'], m['ref_no'], m['name'], m['amount'],
              notice_type, issued_date, m.get('prev_ref_no', '')))
    conn.commit()
    cur.close()
    conn.close()
    return batch_id

def get_batches():
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("""
        SELECT b.*,
               COUNT(CASE WHEN n.payment_status='Paid'    THEN 1 END) as paid_count,
               COUNT(CASE WHEN n.payment_status='Pending' THEN 1 END) as pending_count
        FROM notice_batches b
        LEFT JOIN notices n ON n.batch_id = b.id
        GROUP BY b.id
        ORDER BY b.created_at DESC
    """)
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [dict(r) for r in rows]

def get_batch_notices(batch_id):
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("SELECT * FROM notices WHERE batch_id = %s ORDER BY flat_no", (batch_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [dict(r) for r in rows]

def update_payment(notice_id, status, payment_date, payment_amount, remark):
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("""
        UPDATE notices SET payment_status=%s, payment_date=%s, payment_amount=%s, payment_remark=%s
        WHERE id=%s
    """, (status, payment_date, payment_amount, remark, notice_id))
    conn.commit()
    cur.close()
    conn.close()

def get_eligible_for_2nd(batch_id):
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("""
        SELECT * FROM notices WHERE batch_id=%s AND payment_status='Pending' ORDER BY flat_no
    """, (batch_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [dict(r) for r in rows]

def get_paid_members(batch_id):
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("""
        SELECT * FROM notices WHERE batch_id=%s AND payment_status='Paid' ORDER BY payment_date DESC
    """, (batch_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [dict(r) for r in rows]

def delete_batch(batch_id):
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("DELETE FROM notices       WHERE batch_id=%s", (batch_id,))
    cur.execute("DELETE FROM notice_batches WHERE id=%s",      (batch_id,))
    conn.commit()
    cur.close()
    conn.close()

# Initialise tables on startup
init_db()
