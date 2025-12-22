#!/bin/bash
# Video Meeting AI Layer Processing - Cron Wrapper
# Processes video meetings through the 6-layer AI pipeline
#
# Cron schedule (every 2 hours):
#   0 */2 * * * /var/www/call-recording-system/scripts/run_video_ai_layers.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT"

# Activate virtual environment
source venv/bin/activate

# Run AI layer processing
python scripts/video_processing/process_all_layers.py --limit 20

echo "Video AI layer processing completed at $(date)"
