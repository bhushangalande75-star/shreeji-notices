#!/usr/bin/env python3
"""
One-time migration script: hash all plaintext society passwords in the database.
Run ONCE on Render Shell or locally:
    python migrate_passwords.py

Safe to run multiple times — bcrypt hashes are detected and skipped.
"""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))

from database import get_db, hash_password

def migrate():
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("SELECT id, name, password FROM societies")
    rows = cur.fetchall()

    upgraded = 0
    skipped  = 0
    for row in rows:
        pwd = row["password"] or ""
        if pwd.startswith("$2b$") or pwd.startswith("$2a$"):
            skipped += 1
            print(f"  [SKIP] {row['name']} — already bcrypt")
        else:
            new_hash = hash_password(pwd)
            cur.execute("UPDATE societies SET password=%s WHERE id=%s",
                        (new_hash, row["id"]))
            upgraded += 1
            print(f"  [HASH] {row['name']} — password migrated")

    conn.commit()
    cur.close()
    conn.close()
    print(f"\n✅ Done. Upgraded: {upgraded}  |  Already hashed: {skipped}")

if __name__ == "__main__":
    migrate()
