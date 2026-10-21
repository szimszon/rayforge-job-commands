"""Loads the user's command config and runs commands off the UI thread."""
import json
import logging
import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

logger = logging.getLogger(__name__)

# (event key, label shown in the settings window)
EVENTS = [
    ("job_started", "Job started"),
    ("job_paused", "Job paused"),
    ("job_resumed", "Job resumed"),
    ("job_finished", "Job finished"),
    ("job_stopped", "Job stopped (cancelled while paused)"),
    ("job_error", "Job error"),
    ("alarm", "Machine alarm"),
    ("connected", "Machine connected"),
    ("disconnected", "Machine disconnected"),
    ("connection_error", "Connection error"),
]

EXAMPLE_CONFIG = """\
# Rayforge job event commands. Edited changes apply immediately, no restart.
#
# Events: job_started, job_paused, job_resumed, job_finished, job_stopped,
#         job_error, alarm, connected, disconnected, connection_error
#
# Each entry is either a string or a mapping with command/timeout/enabled.
# Event details are passed as environment variables (RAYFORGE_EVENT,
# RAYFORGE_MACHINE, RAYFORGE_STATUS, RAYFORGE_PREV_STATUS, RAYFORGE_MESSAGE,
# RAYFORGE_TIMESTAMP). Use these instead of string interpolation.

default_timeout: 30
events:
  job_started: []
  job_finished: []
  job_error: []
  # Examples:
  # job_started:
  #   - 'notify-send "Rayforge" "Job started on $RAYFORGE_MACHINE"'
  #   - command: "curl -s -X POST https://example.com/hook -d event=$RAYFORGE_EVENT"
  #     timeout: 10
  # job_error:
  #   - 'notify-send -u critical "Rayforge ERROR" "$RAYFORGE_MESSAGE"'
"""


def config_path() -> Path:
    override = os.environ.get("RAYFORGE_JOB_COMMANDS_CONFIG")
    if override:
        return Path(override)
    try:
        from platformdirs import user_config_dir
        base = Path(user_config_dir("rayforge", appauthor=False))
    except ImportError:
        base = Path.home() / ".config" / "rayforge"
    return base / "job_commands.yaml"


def _parse(text: str, path: Path) -> dict:
    if path.suffix == ".json":
        return json.loads(text)
    import yaml  # Rayforge already depends on PyYAML for manifests
    return yaml.safe_load(text) or {}


class CommandRunner:
    DEDUPE_SECONDS = 1.0

    def __init__(self):
        self.path = config_path()
        self._pool = ThreadPoolExecutor(max_workers=4,
                                        thread_name_prefix="job-cmd")
        self._last_fired: dict[tuple, float] = {}

    # ---- config ----------------------------------------------------------
    def ensure_config(self) -> None:
        if self.path.exists():
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(EXAMPLE_CONFIG, encoding="utf-8")
            logger.info("job_commands: wrote example config to %s", self.path)
        except OSError:
            logger.exception("job_commands: could not create %s", self.path)

    def load(self) -> dict:
        try:
            return _parse(self.path.read_text(encoding="utf-8"), self.path)
        except FileNotFoundError:
            return {}
        except Exception:
            logger.exception("job_commands: invalid config %s", self.path)
            return {}

    def save(self, cfg: dict) -> bool:
        """Writes the config as YAML (comments in an existing file are lost)."""
        try:
            import yaml
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True),
                encoding="utf-8")
            return True
        except Exception:
            logger.exception("job_commands: could not save %s", self.path)
            return False

    # ---- firing events ---------------------------------------------------
    def fire(self, event: str, machine_name: str = "", status: str = "",
             prev_status: str = "", message: str = "",
             force: bool = False) -> None:
        # Drop duplicate events (a state change and a signal may both report
        # the same thing). `force` bypasses this, e.g. for the Test button.
        now = time.monotonic()
        key = (event, machine_name)
        if not force and now - self._last_fired.get(key, 0.0) < self.DEDUPE_SECONDS:
            return
        self._last_fired[key] = now

        cfg = self.load()  # re-read each time so edits apply immediately
        entries = (cfg.get("events") or {}).get(event) or []
        if not entries:
            return
        default_timeout = float(cfg.get("default_timeout", 30))

        env = os.environ.copy()
        env.update({
            "RAYFORGE_EVENT": event,
            "RAYFORGE_MACHINE": machine_name or "",
            "RAYFORGE_STATUS": status or "",
            "RAYFORGE_PREV_STATUS": prev_status or "",
            "RAYFORGE_MESSAGE": message or "",
            "RAYFORGE_TIMESTAMP": str(int(time.time())),
        })

        for entry in entries:
            if isinstance(entry, str):
                entry = {"command": entry}
            if not entry.get("command") or entry.get("enabled", True) is False:
                continue
            timeout = float(entry.get("timeout", default_timeout))
            self._pool.submit(self._run, event, entry["command"], env, timeout)

    @staticmethod
    def _run(event: str, command: str, env: dict, timeout: float) -> None:
        logger.info("job_commands[%s]: running %r", event, command)
        try:
            proc = subprocess.run(command, shell=True, env=env, timeout=timeout,
                                  capture_output=True, text=True)
            if proc.returncode != 0:
                logger.warning("job_commands[%s]: exit %s: %s", event,
                               proc.returncode, proc.stderr.strip()[:500])
        except subprocess.TimeoutExpired:
            logger.warning("job_commands[%s]: timed out after %ss: %r",
                           event, timeout, command)
        except Exception:
            logger.exception("job_commands[%s]: failed to run %r", event, command)

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)