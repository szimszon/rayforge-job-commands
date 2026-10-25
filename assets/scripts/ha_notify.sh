#!/bin/bash
#
# Posts Rayforge job/machine events to a Home Assistant webhook.
# Meant to be called from the job_commands add-on, which provides the
# event details as RAYFORGE_* environment variables. Every variable is
# optional: missing ones are sent as empty strings or null.
#
# Requires: curl, jq
#
# Usage:
#   ha_notify.sh <connected> <webhook-url>
#
#   <connected>    "true" or "false"; the connection state to report.
#                  Sent as a JSON boolean (any other value becomes null).
#                  Pass it from the command, e.g. "ha_notify.sh true URL"
#                  under "Machine connected" and "... false URL" under
#                  "Machine disconnected".
#   <webhook-url>  Home Assistant webhook URL, e.g.
#                  https://ha.example.com/api/webhook/<webhook-id>
#
# Environment variables set by the add-on (all optional):
#   RAYFORGE_EVENT              event name (job_started, job_progress, ...)
#   RAYFORGE_TIMESTAMP          Unix timestamp (default: current time)
#   RAYFORGE_STATUS             machine state / job phase
#   RAYFORGE_MESSAGE            message text (alarm or error details)
#   RAYFORGE_JOB_KIND           job type (SEND or FRAME)
#   RAYFORGE_PROGRESS           job progress in percent (0-100)
#   RAYFORGE_TRAVELED_DISTANCE  distance covered so far
#   RAYFORGE_TOTAL_DISTANCE     total distance of the job
#   RAYFORGE_ELAPSED_SECONDS    time since the job started
#   RAYFORGE_ETA_SECONDS        estimated time remaining

TAG="$(basename "$0")"
CONNECTION="${1:-}"
URL="${2:-}"

# Log to the system log if logger exists; never fail because of logging.
log() {
    if command -v logger > /dev/null; then
        logger -t "$TAG" "$*"
    fi
}

if [ -z "$URL" ]; then
    log "no webhook URL given, nothing to send"
    exit 1
fi

if ! command -v jq > /dev/null; then
    log "jq is not installed, cannot build the payload"
    exit 1
fi

# Build the payload. All values are passed with --arg (always plain
# strings), so jq takes care of escaping quotes, backslashes, newlines, etc.
# Numeric fields are converted to JSON numbers; an empty or non-numeric
# value (e.g. progress on a "connected" event) becomes null.
DATA=$(jq -n -c \
    --arg event "${RAYFORGE_EVENT:-}" \
    --arg timestamp "${RAYFORGE_TIMESTAMP:-$(date +%s)}" \
    --arg connected "$CONNECTION" \
    --arg machine_state "${RAYFORGE_STATUS:-}" \
    --arg alarm_code "${RAYFORGE_MESSAGE:-}" \
    --arg job_state "${RAYFORGE_JOB_KIND:-}" \
    --arg progress "${RAYFORGE_PROGRESS:-}" \
    --arg travelled "${RAYFORGE_TRAVELED_DISTANCE:-}" \
    --arg total "${RAYFORGE_TOTAL_DISTANCE:-}" \
    --arg elapsed "${RAYFORGE_ELAPSED_SECONDS:-}" \
    --arg remaining "${RAYFORGE_ETA_SECONDS:-}" \
    '
    def num: try tonumber catch null;
    {
        event: $event,
        timestamp: ($timestamp | num),
        connected: ($connected | if . == "true" then true
                                 elif . == "false" then false
                                 else null end),
        machine_state: $machine_state,
        alarm_code: $alarm_code,
        job_state: $job_state,
        file: "",                     # not provided by Rayforge yet
        progress: ($progress | num),
        travelled_distance: ($travelled | num),
        total_distance: ($total | num),
        elapsed_s: ($elapsed | num),
        remaining_s: ($remaining | num)
    }
    ' 2> /dev/null)

# If jq failed for any reason, fall back to a minimal payload so that
# Home Assistant still learns that something happened.
if [ -z "$DATA" ]; then
    log "could not build the full payload, sending a minimal one"
    DATA="{\"event\": \"unknown\", \"timestamp\": $(date +%s)}"
fi

# Send the payload to Home Assistant (give up after 10 seconds).
if ! curl --silent --show-error --max-time 10 \
          --header "Content-Type: application/json" \
          --request POST \
          --data "$DATA" \
          "$URL"; then
    log "failed to post to the webhook"
fi

# Also write the payload to the system log (view with: journalctl -t ha_notify.sh)
log "$DATA"