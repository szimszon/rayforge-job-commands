"""Translates Rayforge machine signals into job events."""
import logging
from blinker import Signal

logger = logging.getLogger(__name__)


def _status_name(state) -> str | None:
    status = getattr(state, "status", None)
    if status is None:
        return None
    return str(getattr(status, "name", status)).upper()


def _name_of(obj) -> str:
    return str(getattr(obj, "name", None) or getattr(obj, "id", None) or id(obj))


class JobEventWatcher:
    def __init__(self, runner):
        self.runner = runner
        self._attached: list[tuple[Signal, object]] = []
        self._prev: dict[int, str | None] = {}

    # ---- attaching -------------------------------------------------------
    def attach(self, machine) -> None:
        if machine is None or any(m is machine for m in self._machines()):
            return
        self._prev[id(machine)] = _status_name(getattr(machine, "state", None))
        self._connect(machine, "state_changed", self._on_state)
        self._connect(machine, "connection_status_changed", self._on_connection)
        self._connect(machine, "command_status_changed", self._on_command)
        self._log_discovered_signals(machine)

    def _machines(self):
        return [s.__dict__.get("_rf_machine") for s, _ in self._attached]

    def _connect(self, machine, attr: str, handler) -> None:
        sig = getattr(machine, attr, None)
        if not isinstance(sig, Signal):
            logger.info("job_commands: machine has no signal %r (skipped)", attr)
            return
        # weak=False: blinker would otherwise garbage-collect our closure.
        def bound(sender, **kw):
            handler(machine, **kw)
        sig.connect(bound, weak=False)
        self._attached.append((sig, bound))
        logger.info("job_commands: listening to %s.%s", _name_of(machine), attr)

    @staticmethod
    def _log_discovered_signals(machine) -> None:
        found = sorted(n for n in dir(machine)
                       if not n.startswith("_")
                       and isinstance(getattr(type(machine), n, None) or
                                      getattr(machine, n, None), Signal))
        logger.info("job_commands: signals on %s: %s",
                    _name_of(machine), ", ".join(found) or "(none)")

    def detach_all(self) -> None:
        for sig, handler in self._attached:
            try:
                sig.disconnect(handler)
            except Exception:
                pass
        self._attached.clear()
        self._prev.clear()

    # ---- handlers ----------------------------------------------------------
    def _on_state(self, machine, **kw) -> None:
        cur = _status_name(kw.get("state") or getattr(machine, "state", None))
        key = id(machine)
        prev = self._prev.get(key)
        self._prev[key] = cur
        if cur is None or cur == prev:
            return

        event = None
        if cur == "RUN":
            event = "job_resumed" if prev == "HOLD" else "job_started"
        elif cur == "HOLD" and prev == "RUN":
            event = "job_paused"
        elif cur == "IDLE" and prev == "RUN":
            event = "job_finished"
        elif cur == "IDLE" and prev == "HOLD":
            event = "job_stopped"      # left a pause straight to idle: cancelled
        elif cur == "ALARM":
            event = "job_error" if prev in ("RUN", "HOLD") else "alarm"

        if event:
            self.runner.fire(event, _name_of(machine), cur, prev or "")

    def _on_connection(self, machine, **kw) -> None:
        status = str(getattr(kw.get("status"), "name", kw.get("status"))).upper()
        message = str(kw.get("message") or "")
        event = {"CONNECTED": "connected",
                 "DISCONNECTED": "disconnected",
                 "ERROR": "connection_error"}.get(status)
        if event:
            self.runner.fire(event, _name_of(machine), status, message=message)

    def _on_command(self, machine, **kw) -> None:
        status = str(getattr(kw.get("status"), "name", kw.get("status"))).upper()
        if "ERROR" in status:
            self.runner.fire("job_error", _name_of(machine), status,
                             message=str(kw.get("message") or ""))