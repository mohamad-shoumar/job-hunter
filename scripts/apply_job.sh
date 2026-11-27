#!/bin/sh
# The apply-job skill with nobody at the keyboard (the user's ask, 2026-11-27): run_daily.sh
# calls this after a successful pipeline run when launchd passes --apply-job. Claude Code
# (`claude -p`) drives the user's real Chrome through Claude in Chrome, fills each To apply
# job's form and stops before the final Submit, as the skill says; the tabs stay open for
# the user. Needs the Mac awake and Chrome with the Claude extension connected.
# Permissions: `auto` mode (a classifier approves each action, nothing is bypassed), with
# the Chrome tools allowed up front; anything that would still ask is denied, never waited on.
# Report: reports/apply_<date>.md (the session keeps it up to date). Log: data/apply_job.log.
set -u
cd "$(dirname "$0")/.."
mkdir -p data reports
day=$(date +%F)
log=data/apply_job.log
report="reports/apply_$day.md"
cap=${APPLY_JOB_MAX_SECONDS:-18000}   # 5 hours; the 2026-11-24 run took about 3 minutes a ready job
say() { echo "$(date '+%F %T') $*" >> "$log"; }

claude=${CLAUDE_CODE_BIN:-}
for c in "$claude" "$HOME/.local/bin/claude" "$HOME/.claude/local/claude" "$(command -v claude || true)"; do
    if [ -n "$c" ] && [ -x "$c" ]; then claude=$c; break; fi
done
if [ -z "$claude" ] || [ ! -x "$claude" ]; then say "apply-job: no claude program found, skipped"; exit 1; fi

# The app: the skill works from its To apply column. Started here (not by the session) so it
# outlives the run; the plist's AbandonProcessGroup keeps launchd from stopping it after.
if ! curl -sf -o /dev/null http://127.0.0.1:8765/api/status; then
    nohup ./.venv/bin/jobhunter serve --no-open >> data/serve.log 2>&1 &
    n=0; until curl -sf -o /dev/null http://127.0.0.1:8765/api/status || [ $n -ge 30 ]; do sleep 1; n=$((n+1)); done
    curl -sf -o /dev/null http://127.0.0.1:8765/api/status || { say "apply-job: the app did not start (data/serve.log), skipped"; exit 1; }
fi
open -ga "Google Chrome" 2>/dev/null && sleep 5
# Keep the Mac and its screen awake while this script runs (hours, nobody touching it).
caffeinate -di -w $$ &

# Jobs an earlier run already prepared stay in To apply until the user presses Submit:
# code lists them (a LinkedIn note or a Tracking note on a card in the column), so they are
# not filled twice, with a second Easy Apply draft and contact search every night. The
# column's jobs come from the app's own lists, the same calls the board makes.
done_jobs=$(./.venv/bin/python - 2>> "$log" <<'PY'
import json, sqlite3, urllib.request
base = "http://127.0.0.1:8765/api/jobs?view="
ids = set()
for view, stages in (("shortlisted", None), ("visa_list&days=2", None), ("tracked", {"saved"})):
    for job in json.load(urllib.request.urlopen(base + view, timeout=30))["jobs"]:
        if stages is None or job.get("stage") in stages:
            ids.add(int(job["id"]))
if ids:
    marks = ", ".join("?" * len(ids))
    rows = sqlite3.connect("data/jobs.sqlite").execute(
        f"SELECT a.job_id, j.company, j.title FROM applications a JOIN jobs j ON j.id = a.job_id "
        f"WHERE a.job_id IN ({marks}) AND (COALESCE(a.linkedin_note, '') != '' OR COALESCE(a.notes, '') != '') "
        f"ORDER BY a.job_id", sorted(ids))
    for row in rows:
        print(" | ".join(str(v) for v in row))
PY
)
if [ -n "$done_jobs" ]; then
    already="These To apply jobs were prepared by an earlier run and are waiting for the user to submit them. Leave them as they are (no CV, form, contact or note work, no Skip) and list them in the report under \"Already prepared, waiting for you\":
$done_jobs"
else
    already="No job in To apply was prepared by an earlier run."
fi

prompt="Use the apply-job skill (Skill tool) to work through the To apply column at http://127.0.0.1:8765/#pipeline, top to bottom.

This run was started by the evening schedule, right after the job fetch. Nobody is at the computer: never ask a question or wait for an answer; make the sensible choice, note it and keep going, as the skill says. Everything in the skill still holds, the hard stops above all: never press the final Apply/Submit, never press Connect, Message or Follow, never create an account or type a password.

$already

The final report has no chat to land in, so keep it in the file $report: create it when you start, and add each job to it as soon as that job is done (filled, skipped or waiting for a sign-in), in the skill's report format, so the file is useful even if the run stops early. End the file with the skill's full final report. If Chrome or the Claude extension cannot be reached, write that one line to the file and stop."

say "apply-job: started ($claude, report $report)"
# The prompt goes in on stdin: --allowedTools takes several values and would swallow it.
printf '%s\n' "$prompt" | perl -e 'alarm shift; exec @ARGV' "$cap" "$claude" -p --chrome --model opus \
    --permission-mode auto --permission-prompts none --allowedTools "mcp__claude-in-chrome__*" \
    >> "$log" 2>&1
status=$?
case $status in
    0) say "apply-job: finished, report $report" ;;
    142) say "apply-job: stopped after $cap seconds (APPLY_JOB_MAX_SECONDS), report so far in $report" ;;
    *) say "apply-job: claude exited with $status" ;;
esac
osascript -e "display notification \"See $report\" with title \"apply-job finished ($status)\"" 2>/dev/null || true
exit $status
