"""
Run this script from inside your society_app folder:
    python update_refs.py
"""
import pandas as pd
import sqlite3
import os

# ── Paths ─────────────────────────────────────────────────────
EXCEL_PATH = "Defaulter_List_Mar_2026.xlsx"   # Put the Excel file in society_app folder
DB_PATH    = "notices.db"

# ── Check files exist ─────────────────────────────────────────
if not os.path.exists(EXCEL_PATH):
    print(f"❌ Excel file not found: {EXCEL_PATH}")
    print("   Please copy the Excel file into the society_app folder and try again.")
    exit()

if not os.path.exists(DB_PATH):
    print(f"❌ Database not found: {DB_PATH}")
    print("   Make sure you run this from inside the society_app folder.")
    exit()

# ── Read Excel ────────────────────────────────────────────────
df   = pd.read_excel(EXCEL_PATH, header=None)
data = df.iloc[1:].reset_index(drop=True)

# Build a mapping: flat_no → new ref_no
updates = {}
for _, row in data.iterrows():
    flat_no = str(row[2]).strip()
    ref_no  = str(row[4]).strip()
    updates[flat_no] = ref_no

print(f"📋 Found {len(updates)} members in Excel\n")

# ── Update Database ───────────────────────────────────────────
conn  = sqlite3.connect(DB_PATH)
cur   = conn.cursor()

success = 0
not_found = []

for flat_no, new_ref in updates.items():
    result = cur.execute(
        "UPDATE notices SET ref_no = ? WHERE flat_no = ?",
        (new_ref, flat_no)
    )
    if result.rowcount > 0:
        success += result.rowcount
        print(f"  ✅ {flat_no} → {new_ref}")
    else:
        not_found.append(flat_no)

conn.commit()
conn.close()

# ── Summary ───────────────────────────────────────────────────
print(f"\n{'='*50}")
print(f"✅ Successfully updated : {success} records")
if not_found:
    print(f"⚠️  Not found in DB     : {len(not_found)} members")
    for f in not_found:
        print(f"   - {f}")
print(f"{'='*50}")
print("\nDone! Open the Tracker to verify the updated ref numbers.")
