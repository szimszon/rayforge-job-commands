import logging
import pluggy

from .runner import CommandRunner
from .watcher import ConnectionWatcher

hookimpl = pluggy.HookimplMarker("rayforge")
logger = logging.getLogger(__name__)

_runner: CommandRunner | None = None
_watcher: ConnectionWatcher | None = None
_main_window = None
_window = None


@hookimpl
def rayforge_init(context):
    global _runner, _watcher
    _runner = CommandRunner()
    _runner.ensure_config()
    _watcher = ConnectionWatcher(_runner)

    machines = getattr(context.machine_mgr, "machines", None)
    if isinstance(machines, dict):
        machines = machines.values()
    for machine in list(machines or []):
        _watcher.attach(machine)
    _watcher.attach(context.machine)
    logger.info("job_commands: ready, config at %s", _runner.path)


@hookimpl
def main_window_ready(main_window):
    global _main_window
    _main_window = main_window


@hookimpl
def register_actions(action_registry):
    from gi.repository import Gio
    from rayforge.ui_gtk.action_registry import MenuPlacement

    action = Gio.SimpleAction.new("job-commands-settings", None)
    action.connect("activate", _open_settings)
    action_registry.register(
        action_name="job-commands-settings",
        action=action,
        addon_name="job_commands",
        label="Job Event Commands…",
        icon_name="preferences-system-symbolic",
        menu=MenuPlacement(menu_id="tools", priority=60),
    )

### Where the menu entry is placed. Settings is reached via Edit -> Settings,
### so the Edit menu is the closest documented-by-behaviour match. The id
### "edit" is a guess: change it if your Rayforge build uses another one.
##MENU_ID = "edit"
##MENU_PRIORITY = 900   # lower numbers appear first, so this lands near the bottom
##
##@hookimpl
##def register_actions(action_registry):
##    from gi.repository import Gio
##    from rayforge.ui_gtk.action_registry import MenuPlacement
##
##    action = Gio.SimpleAction.new("job-commands-settings", None)
##    action.connect("activate", _open_settings)
##    action_registry.register(
##        action_name="job-commands-settings",
##        action=action,
##        addon_name="job_commands",
##        label="Job Event Commands…",
##        icon_name="preferences-system-symbolic",
##        menu=MenuPlacement(menu_id=MENU_ID, priority=MENU_PRIORITY),
##    )
##
##    # Diagnostic: get_menu_items() is a documented lookup method.
##    try:
##        items = list(action_registry.get_menu_items(MENU_ID))
##        logger.info("job_commands: %d item(s) registered under menu %r",
##                    len(items), MENU_ID)
##    except Exception:
##        logger.debug("job_commands: could not query menu %r", MENU_ID,
##                     exc_info=True)

def _open_settings(_action, _param):
    global _window
    if _runner is None:
        return
    if _window is not None:
        _window.present()
        return
    from .settings_window import JobCommandsWindow
    _window = JobCommandsWindow(_runner, _main_window)
    _window.connect("close-request", _on_closed)
    _window.present()


def _on_closed(_win):
    global _window
    _window = None
    return False


@hookimpl
def on_unload():
    global _runner, _watcher, _window
    if _window is not None:
        _window.destroy()
        _window = None
    if _watcher:
        _watcher.detach_all()
    if _runner:
        _runner.shutdown()
    _runner = _watcher = None

def _fmt(value, digits=1):
    if value is None:
        return ""
    return f"{value:.{digits}f}" if isinstance(value, float) else str(value)


def _job_env(status) -> dict:
    frac = getattr(status, "progress_fraction", None)
    kind = getattr(status, "kind", None)
    return {
        "RAYFORGE_JOB_KIND": getattr(kind, "name", kind),
        "RAYFORGE_PROGRESS": None if frac is None else f"{frac * 100:.1f}",
        "RAYFORGE_ELAPSED_SECONDS": _fmt(getattr(status, "elapsed_seconds", None)),
        "RAYFORGE_ETA_SECONDS": _fmt(getattr(status, "eta_seconds", None)),
        "RAYFORGE_ESTIMATED_SECONDS": _fmt(getattr(status, "estimated_seconds", None)),
        "RAYFORGE_TRAVELED_DISTANCE": _fmt(getattr(status, "traveled_distance", None)),
        "RAYFORGE_TOTAL_DISTANCE": _fmt(getattr(status, "total_distance", None)),
    }


def _fire_job(event: str, status, message: str = "") -> None:
    if _runner is None:
        return
    phase = getattr(status, "phase", None)
    _runner.fire(event, status.machine_name,
                 status=str(getattr(phase, "name", phase or "")),
                 message=message, extra_env=_job_env(status))


@hookimpl
def on_job_started(status):
    if _runner is None:
        return
    _runner.start_progress_clock(status.machine_id)
    _fire_job("job_started", status)


@hookimpl
def on_job_updated(status):
    if _runner is not None and _runner.progress_due(status.machine_id):
        _fire_job("job_progress", status)


@hookimpl
def on_job_paused(status):
    _fire_job("job_paused", status)


@hookimpl
def on_job_resumed(status):
    if _runner is not None:
        _runner.start_progress_clock(status.machine_id)
    _fire_job("job_resumed", status)


@hookimpl
def on_job_finished(status, outcome, message=""):
    if _runner is None:
        return
    _runner.stop_progress_clock(status.machine_id)
    name = str(getattr(outcome, "name", outcome)).upper()
    if name == "COMPLETED":
        _fire_job("job_finished", status)
    elif name == "CANCELLED":
        _fire_job("job_stopped", status)
    else:
        _fire_job("job_error", status, message=message)