import logging
import pluggy

from .runner import CommandRunner
from .watcher import JobEventWatcher

hookimpl = pluggy.HookimplMarker("rayforge")
logger = logging.getLogger(__name__)

_runner: CommandRunner | None = None
_watcher: JobEventWatcher | None = None
_main_window = None
_window = None


@hookimpl
def rayforge_init(context):
    global _runner, _watcher
    _runner = CommandRunner()
    _runner.ensure_config()
    _watcher = JobEventWatcher(_runner)

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