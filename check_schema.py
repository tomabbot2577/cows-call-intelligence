#!/usr/bin/env python3

import psycopg2
import os
from urllib.parse import urlparse

# Connect to database
url = urlparse(os.getenv('DATABASE_URL'))
conn = psycopg2.connect(
    database=url.path[1:],
    user=url.username,
    password=url.password,
    host=url.hostname,
    port=url.port
)

cur = conn.cursor()

print("Columns in call_recordings table:")
cur.execute("""
    SELECT column_name, data_type
    FROM information_schema.columns
    WHERE table_name = 'call_recordings'
    ORDER BY ordinal_position
""")

for row in cur.fetchall():
    print(f"  {row[0]}: {row[1]}")

conn.close()