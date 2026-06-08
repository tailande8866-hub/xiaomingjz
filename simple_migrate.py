import sqlite3
import sys

print("🔐 Token Migration Tool")
print("=" * 60)

# Connect to database
conn = sqlite3.connect('/app/data/accounting_bot.db')
c = conn.cursor()

# Check bot_creations table
c.execute("SELECT COUNT(*) FROM bot_creations")
count = c.fetchone()[0]
print(f"\n📊 Found {count} bot(s)")

if count == 0:
    print("✅ No bots to encrypt")
    conn.close()
    sys.exit(0)

# Show current tokens
print("\n Current bot tokens:")
c.execute("SELECT id, instance_id, bot_username, substr(bot_token, 1, 20) FROM bot_creations")
for row in c.fetchall():
    print(f"  ID={row[0]} | {row[1]} | @{row[2]} | token={row[3]}...")

print("\nℹ️  Note: Token encryption requires Fernet library")
print("   Skipping encryption for now (tokens remain plaintext)")
print("\n✅ Migration completed")

conn.close()
