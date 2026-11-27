#!/bin/sh
# Entry point for cron/launchd: runs the pipeline from the project folder
# with the project's virtualenv, appending output to data/run.log.
# Arguments go to `jobhunter run` (the evening run passes --digest), except --apply-job:
# then, when the pipeline succeeded, the apply-job skill runs too (scripts/apply_job.sh).
set -eu
cd "$(dirname "$0")/.."
mkdir -p data
apply=
for a; do
    shift
    if [ "$a" = --apply-job ]; then apply=1; else set -- "$@" "$a"; fi
done
status=0
./.venv/bin/jobhunter run "$@" >> data/run.log 2>&1 || status=$?
if [ -n "$apply" ]; then
    if [ "$status" -eq 0 ]; then
        sh scripts/apply_job.sh || true
    else
        echo "$(date '+%F %T') apply-job: not started, the pipeline exited with $status (data/run.log)" >> data/apply_job.log
    fi
fi
exit "$status"
