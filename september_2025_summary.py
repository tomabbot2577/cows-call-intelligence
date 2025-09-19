#!/usr/bin/env python3
"""
Analyze and summarize September 2025 recordings
"""

import json
from datetime import datetime
from collections import defaultdict, Counter

# Load the recordings
with open('september_2025_recordings.json', 'r') as f:
    recordings = json.load(f)

print("\n" + "="*100)
print("📊 SEPTEMBER 2025 CALL RECORDINGS ANALYSIS")
print("="*100)

# Basic Statistics
print(f"\n📈 BASIC STATISTICS:")
print(f"  Total Call Recordings: {len(recordings)}")

# Date range analysis
dates = []
for rec in recordings:
    if rec['start_time']:
        dates.append(datetime.fromisoformat(rec['start_time'].replace('Z', '+00:00')))

if dates:
    earliest = min(dates)
    latest = max(dates)
    print(f"  Date Range: {earliest.strftime('%Y-%m-%d %H:%M')} to {latest.strftime('%Y-%m-%d %H:%M')} UTC")

# Call direction breakdown
directions = Counter(rec['direction'] for rec in recordings)
print(f"\n📞 CALL DIRECTION:")
for direction, count in directions.most_common():
    percentage = (count / len(recordings)) * 100
    print(f"  {direction}: {count} ({percentage:.1f}%)")

# Recording types
recording_types = Counter(rec['recording_type'] for rec in recordings)
print(f"\n🎙️ RECORDING TYPES:")
for rec_type, count in recording_types.most_common():
    percentage = (count / len(recordings)) * 100
    print(f"  {rec_type}: {count} ({percentage:.1f}%)")

# Duration analysis
durations = [rec['duration'] for rec in recordings if rec['duration']]
if durations:
    total_duration = sum(durations)
    avg_duration = total_duration / len(durations)
    max_duration = max(durations)
    min_duration = min(durations)

    print(f"\n⏱️ CALL DURATION ANALYSIS:")
    print(f"  Total Duration: {total_duration} seconds ({total_duration/3600:.2f} hours)")
    print(f"  Average Duration: {avg_duration:.1f} seconds ({avg_duration/60:.1f} minutes)")
    print(f"  Longest Call: {max_duration} seconds ({max_duration/60:.1f} minutes)")
    print(f"  Shortest Call: {min_duration} seconds")

# Top callers (from)
from_names = defaultdict(int)
for rec in recordings:
    if rec['from_name']:
        from_names[rec['from_name']] += 1

print(f"\n👤 TOP 10 CALLERS (FROM):")
for name, count in sorted(from_names.items(), key=lambda x: x[1], reverse=True)[:10]:
    print(f"  {name}: {count} calls")

# Top recipients (to)
to_names = defaultdict(int)
to_numbers = defaultdict(int)
for rec in recordings:
    if rec['to_name']:
        to_names[rec['to_name']] += 1
    elif rec['to_number']:
        to_numbers[rec['to_number']] += 1

print(f"\n📱 TOP 10 RECIPIENTS (TO):")
combined_recipients = {**to_names, **to_numbers}
for recipient, count in sorted(combined_recipients.items(), key=lambda x: x[1], reverse=True)[:10]:
    print(f"  {recipient}: {count} calls")

# Daily distribution
daily_counts = defaultdict(int)
for rec in recordings:
    if rec['start_time']:
        date = datetime.fromisoformat(rec['start_time'].replace('Z', '+00:00')).date()
        daily_counts[date] += 1

print(f"\n📅 DAILY CALL DISTRIBUTION (TOP 10 BUSIEST DAYS):")
for date, count in sorted(daily_counts.items(), key=lambda x: x[1], reverse=True)[:10]:
    print(f"  {date}: {count} calls")

# Recording IDs for reference
print(f"\n🔗 SAMPLE RECORDING IDs (First 10):")
for i, rec in enumerate(recordings[:10], 1):
    print(f"  {i}. Recording ID: {rec['recording_id']}")
    print(f"     Call ID: {rec['call_id']}")
    print(f"     URI: {rec['recording_uri']}")
    print()

print("="*100)
print(f"✅ Analysis complete. Full data saved in: september_2025_recordings.json")
print("="*100)