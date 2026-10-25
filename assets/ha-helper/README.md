## Setup notes

- **`{uuid}`:** Replace it with your webhook ID, the same one at the end of the URL you give `ha_notify.sh`.
- **Where it goes:** Put the block in `configuration.yaml` under `template:`, or in a file included with `template: !include templates.yaml`. In that case, drop the top-level `template:` line and keep the list. Reload with **Developer Tools → YAML → Template entities**.
- **Connection events:** `ha_notify.sh` sends the connection state you pass as its first argument. Call it with `true` for "Machine connected" and `false` for "Machine disconnected". For `connection_error` and `alarm` you can pass either, since the template derives the state from the event name when it can't use the boolean.
- **Single webhook:** Because the whole payload arrives in one POST, all entities update together on every event. That is the reason for the "keep previous value" branches above.
- **Syntax versions:** The `triggers:` / `trigger:` form needs Home Assistant 2024.10 or newer. On older versions, use `trigger:` / `platform: webhook` instead.
- **Timestamp sensor:** If it shows `unknown`, the payload's `timestamp` wasn't a valid Unix time. With `ha_notify.sh` it falls back to the current time, so this shouldn't happen.
