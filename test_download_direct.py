#!/usr/bin/env python3
"""
Test direct download of a recording
"""

import os
import sys
sys.path.insert(0, '/var/www/call-recording-system')

from dotenv import load_dotenv
from ringcentral import SDK

load_dotenv('/var/www/call-recording-system/.env')

# Get first pending recording
import psycopg2

db_url = os.getenv('DATABASE_URL')
if db_url.startswith('postgresql://'):
    db_url = db_url.replace('postgresql://', '')

parts = db_url.split('@')
user_pass = parts[0].split(':')
host_db = parts[1].split('/')
host_port = host_db[0].split(':')

conn = psycopg2.connect(
    host=host_port[0],
    port=int(host_port[1]) if len(host_port) > 1 else 5432,
    database=host_db[1],
    user=user_pass[0],
    password=user_pass[1]
)

cur = conn.cursor()
cur.execute("SELECT recording_id FROM call_recordings WHERE download_status = 'pending' LIMIT 1")
recording_id = cur.fetchone()[0]
cur.close()
conn.close()

print(f"Testing download of recording: {recording_id}")

# Initialize SDK
rcsdk = SDK(
    os.getenv('RINGCENTRAL_CLIENT_ID'),
    os.getenv('RINGCENTRAL_CLIENT_SECRET'),
    os.getenv('RINGCENTRAL_SERVER_URL', 'https://platform.ringcentral.com')
)

platform = rcsdk.platform()
platform.login(jwt=os.getenv('RINGCENTRAL_JWT_TOKEN'))

# Try download
url = f'/restapi/v1.0/account/~/recording/{recording_id}/content'
print(f"URL: {url}")

response = platform.get(url)

print(f"Response type: {type(response)}")
print(f"Response attributes: {dir(response)}")

# Try different methods
if hasattr(response, 'ok'):
    print(f"Has ok(): {response.ok()}")

if hasattr(response, 'status'):
    print(f"Has status(): {response.status()}")

if hasattr(response, 'body'):
    body = response.body()
    print(f"Body type: {type(body)}")
    print(f"Body length: {len(body)} bytes")

    # Save to file
    with open('/tmp/test_recording.mp3', 'wb') as f:
        f.write(body)
    print("Saved to /tmp/test_recording.mp3")

platform.logout()