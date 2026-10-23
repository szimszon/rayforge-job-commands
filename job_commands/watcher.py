"""Listens to machine signals that the Rayforge job hooks don't cover:
connection changes and alarms outside of a job."""
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


class ConnectionWatcher:
    def __init__(self, runner):
        self.runner = runner
        self._attached: list[tuple[Signal, object]] = []
        self._machine_ids: set[int] = set()
        self._prev: dict[int, str | None] = {}

    def attach(self, machine) -> None:
        if machine is None or id(machine) in self._machine_ids:
            return
        self._machine_ids.add(id(machine))
        self._prev[id(machine)] = _status_name(getattr(machine, "state", None))
        self._connect(machine, "connection_status_changed", self._on_connection)
        self._connect(machine, "state_changed", self._on_state)

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

    def detach_all(self) -> None:
        for sig, handler in self._attached:
            try:
                sig.disconnect(handler)
            except Exception:
                pass
        self._attached.clear()
        self._machine_ids.clear()
        self._prev.clear()

    def _on_connection(self, machine, **kw) -> None:
        status = str(getattr(kw.get("status"), "name", kw.get("status"))).upper()
        message = str(kw.get("message") or "")
        event = {"CONNECTED": "connected",
                 "DISCONNECTED": "disconnected",
                 "ERROR": "connection_error"}.get(status)
        if event:
            self.runner.fire(event, _name_of(machine), status, message=message)

    def _on_state(self, machine, **kw) -> None:
        # Only alarms *outside* a job; a job aborted by an alarm is reported
        # by the on_job_finished(FAILED) hook.
        cur = _status_name(kw.get("state") or getattr(machine, "state", None))
        key = id(machine)
        prev = self._prev.get(key)
        self._prev[key] = cur
        if cur == "ALARM" and prev not in (None, "ALARM", "RUN", "HOLD"):
            self.runner.fire("alarm", _name_of(machine), cur, prev or "")