import sqlite3

conn = sqlite3.connect('notices.db')

# Show all batches
print("Current batches in database:")
print("-" * 60)
batches = conn.execute("SELECT id, batch_name, notice_type, issued_date, total FROM notice_batches ORDER BY id").fetchall()
for b in batches:
    print(f"  ID: {b[0]} | {b[1]} | {b[2]} Notice | Date: {b[3]} | Members: {b[4]}")

print("\n" + "-" * 60)

# Ask which to delete
if batches:
    ids = input("\nEnter batch ID(s) to DELETE (comma separated, e.g. 1,2): ").strip()
    if ids:
        id_list = [int(i.strip()) for i in ids.split(',')]
        for bid in id_list:
            conn.execute("DELETE FROM notices WHERE batch_id = ?", (bid,))
            conn.execute("DELETE FROM notice_batches WHERE id = ?", (bid,))
            print(f"  🗑️  Deleted batch ID {bid}")
        conn.commit()
        print("\n✅ Done! Old batches removed.")
    else:
        print("No batches deleted.")
else:
    print("No batches found in database.")

conn.close()
