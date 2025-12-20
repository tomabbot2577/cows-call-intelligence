#!/usr/bin/env python3
"""
Check and enhance search capabilities for the web analyzer
"""

import sqlite3
import sys
sys.path.insert(0, '/var/www/call-recording-system')

# Check current database schema
conn = sqlite3.connect('/var/www/call-recording-system/data/insights/insights.db')
cursor = conn.cursor()

# Get table info
cursor.execute("PRAGMA table_info(insights)")
columns = cursor.fetchall()

print("Current insights table columns:")
print("-" * 60)
for col in columns:
    print(f"  {col[1]:30} {col[2]:15}")

# Check for indexes
cursor.execute("SELECT name, sql FROM sqlite_master WHERE type='index' AND tbl_name='insights'")
indexes = cursor.fetchall()

print("\nCurrent indexes:")
print("-" * 60)
for idx in indexes:
    print(f"  {idx[0]}")

# Check some sample data
cursor.execute("SELECT COUNT(*) FROM insights")
count = cursor.fetchone()[0]
print(f"\nTotal records in insights table: {count}")

if count > 0:
    # Get sample records to understand data
    cursor.execute("""
        SELECT recording_id, agent_name, customer_name, customer_phone, call_date
        FROM insights
        LIMIT 5
    """)
    samples = cursor.fetchall()

    print("\nSample data:")
    print("-" * 60)
    for sample in samples:
        print(f"  ID: {sample[0]}")
        print(f"  Agent: {sample[1]}")
        print(f"  Customer: {sample[2]}")
        print(f"  Phone: {sample[3]}")
        print(f"  Date: {sample[4]}")
        print("-" * 30)

conn.close()

print("\n" + "="*60)
print("ANALYSIS COMPLETE")
print("="*60)
print("""
Current search capabilities (from code review):
- ✅ Date range filtering (start_date, end_date)
- ✅ Agent ID filtering
- ✅ Customer ID filtering
- ✅ Sentiment filtering
- ✅ Category filtering
- ✅ Quality score filtering

Missing/Enhanced features needed:
- ❌ Employee NAME search (currently only agent_id)
- ❌ Customer NAME search (currently only customer_id)
- ❌ Open text search (transcript content, summary)
- ❌ Phone number search
- ❌ Sorting options (by date, quality, sentiment)
- ❌ Multi-select filters for categories
""")