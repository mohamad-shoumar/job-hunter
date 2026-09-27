#!/bin/sh
# Daily entry point for cron/launchd: runs the pipeline from the project folder
# with the project's virtualenv, appending output to data/run.log.
set -eu
cd "$(dirname "$0")/.."
mkdir -p data
exec ./.venv/bin/jobhunter run >> data/run.log 2>&1
