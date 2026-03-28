import sqlite3

conn = sqlite3.connect('notices.db')
rows = conn.execute("SELECT flat_no, ref_no, payment_status FROM notices WHERE payment_status='Pending' LIMIT 5").fetchall()
for r in rows:
    print(r)
conn.close()
