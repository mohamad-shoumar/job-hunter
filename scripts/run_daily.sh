#!/bin/sh
# Entry point for cron/launchd: runs the pipeline from the project folder
# with the project's virtualenv, appending output to data/run.log.
# Arguments go to `jobhunter run` (the evening run passes --skip serpapi).
set -eu
cd "$(dirname "$0")/.."
mkdir -p data
exec ./.venv/bin/jobhunter run "$@" >> data/run.log 2>&1
