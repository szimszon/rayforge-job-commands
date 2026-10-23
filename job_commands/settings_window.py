import logging
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gtk, Gio # noqa: E402

from .runner import EVENTS  # noqa: E402

from pathlib import Path

_ICON_DIR = Path(__file__).parent / "icons"

_ICON_CANDIDATES = {
    "add": ["list-add-symbolic", "add-symbolic", "jc-add-symbolic"],
    "remove": ["user-trash-symbolic", "delete-symbolic",
               "list-remove-symbolic", "jc-remove-symbolic"],
    "run": ["media-playback-start-symbolic", "play-symbolic"],
}

_BUNDLED = {
    "add": "jc-add-symbolic.svg",
    "remove": "jc-remove-symbolic.svg",
}

_FALLBACK_TEXT = {"add": "+", "remove": "✕", "run": "▶"}

def _resolve_icon(kind: str) -> str | None:
    display = Gdk.Display.get_default()
    theme = Gtk.IconTheme.get_for_display(display)
    if _ICON_DIR.is_dir() and str(_ICON_DIR) not in theme.get_search_path():
        theme.add_search_path(str(_ICON_DIR))
    for name in _ICON_CANDIDATES[kind]:
        if theme.has_icon(name):
            logging.getLogger(__name__).info("icon %s -> %s", kind, name)
            p = theme.lookup_icon(name, None, 16, 1, Gtk.TextDirection.NONE, 0)
            f = p.get_file()
            logging.getLogger(__name__).info(
                "icon %s -> %s (%s)", kind, name, f.get_path() if f else "no file")
            return name
    return None


def _flat_icon_button(kind: str, tooltip: str) -> Gtk.Button:
    btn = Gtk.Button(tooltip_text=tooltip, valign=Gtk.Align.CENTER)
    bundled = _ICON_DIR / _BUNDLED.get(kind, "")
    if kind in _BUNDLED and bundled.is_file():
        image = Gtk.Image.new_from_gicon(
            Gio.FileIcon.new(Gio.File.new_for_path(str(bundled))))
        btn.set_child(image)
    else:
        icon = _resolve_icon(kind)
        if icon:
            btn.set_icon_name(icon)
        else:
            btn.set_label(_FALLBACK_TEXT[kind])
    btn.add_css_class("flat")
    return btn


class JobCommandsWindow(Adw.Window):
    def __init__(self, runner, parent=None):
        super().__init__(title="Job Event Commands",
                         default_width=680, default_height=760)
        if parent is not None:
            self.set_transient_for(parent)

        self.runner = runner
        self._cfg = runner.load()
        saved = self._cfg.get("events") or {}
        self._events: dict[str, list[dict]] = {
            ev: [self._normalize(e) for e in (saved.get(ev) or [])]
            for ev, _label in EVENTS
        }

        # --- layout -----------------------------------------------------
        header = Adw.HeaderBar()
        save_btn = Gtk.Button(label="Save")
        save_btn.add_css_class("suggested-action")
        save_btn.connect("clicked", self._on_save)
        header.pack_end(save_btn)

        page = Adw.PreferencesPage()

        general = Adw.PreferencesGroup(title="General")
        self._timeout = Adw.SpinRow.new_with_range(1, 3600, 1)
        self._timeout.set_title("Default timeout (seconds)")
        self._timeout.set_subtitle("Commands running longer than this are killed")
        self._timeout.set_value(float(self._cfg.get("default_timeout", 30)))
        general.add(self._timeout)
        self._interval = Adw.SpinRow.new_with_range(0, 86400, 1)
        self._interval.set_title("Progress command interval (seconds)")
        self._interval.set_subtitle(
            "How often the 'Job progress' commands run while a job is "
            "running. 0 disables them. Rayforge reports at most once per second.")
        self._interval.set_value(float(self._cfg.get("progress_interval", 30)))
        general.add(self._interval)
        page.add(general)

        events = Adw.PreferencesGroup(
            title="Events",
            description=("Commands run in a shell. Event details are available "
                         "as $RAYFORGE_EVENT, $RAYFORGE_MACHINE, "
                         "$RAYFORGE_STATUS, $RAYFORGE_PREV_STATUS "
                         "$RAYFORGE_MESSAGE, $RAYFORGE_TIMESTAMP and, for job events, "
                         "$RAYFORGE_JOB_KIND, $RAYFORGE_PROGRESS (percent), "
                         "$RAYFORGE_ELAPSED_SECONDS, $RAYFORGE_ETA_SECONDS, "
                         "$RAYFORGE_ESTIMATED_SECONDS, $RAYFORGE_TRAVELED_DISTANCE and "
                         "$RAYFORGE_TOTAL_DISTANCE."),
        )
        for ev, label in EVENTS:
            events.add(self._build_event_row(ev, label))
        page.add(events)

        self._toasts = Adw.ToastOverlay()
        self._toasts.set_child(page)

        view = Adw.ToolbarView()
        view.add_top_bar(header)
        view.set_content(self._toasts)
        self.set_content(view)

    # --- helpers ---------------------------------------------------------
    @staticmethod
    def _normalize(entry) -> dict:
        return {"command": entry} if isinstance(entry, str) else dict(entry)

    def _build_event_row(self, ev: str, label: str) -> Adw.ExpanderRow:
        expander = Adw.ExpanderRow(title=label, subtitle=ev)

        test_btn = _flat_icon_button("run",
                                     "Save and run this event's commands now")
        test_btn.connect("clicked", lambda _b, e=ev: self._on_test(e))
        expander.add_suffix(test_btn)

        add_row = Adw.ActionRow(title="Add command")
        add_btn = _flat_icon_button("add", "Add command")
        add_row.add_suffix(add_btn)
        add_row.set_activatable_widget(add_btn)
        expander.add_row(add_row)

        add_btn.connect("clicked",
                        lambda _b: self._add_new_command(expander, ev))

        for entry in self._events[ev]:
            self._add_command_row(expander, ev, entry)
        return expander

    def _add_new_command(self, expander, ev: str) -> None:
        entry = {"command": ""}
        self._events[ev].append(entry)
        self._add_command_row(expander, ev, entry)
        expander.set_expanded(True)

    def _add_command_row(self, expander, ev: str, entry: dict) -> None:
        row = Adw.EntryRow(title="Command")
        row.set_text(entry.get("command", ""))
        row.connect("changed",
                    lambda r: entry.__setitem__("command", r.get_text()))

        switch = Gtk.Switch(active=entry.get("enabled", True) is not False,
                            valign=Gtk.Align.CENTER, tooltip_text="Enabled")
        switch.connect("notify::active",
                       lambda s, _p: entry.__setitem__("enabled", s.get_active()))
        row.add_prefix(switch)

        remove = _flat_icon_button("remove", "Remove command")

        def on_remove(_b):
            self._events[ev][:] = [e for e in self._events[ev] if e is not entry]
            expander.remove(row)

        remove.connect("clicked", on_remove)
        row.add_suffix(remove)
        expander.add_row(row)

    # --- saving / testing -------------------------------------------------
    def _collect(self) -> dict:
        cfg = dict(self._cfg)                       # keep unknown keys
        cfg["default_timeout"] = self._timeout.get_value()
        cfg["progress_interval"] = self._interval.get_value()
        events = dict(cfg.get("events") or {})      # keep unknown events
        for ev, _label in EVENTS:
            cleaned = []
            for entry in self._events[ev]:
                if not entry.get("command", "").strip():
                    continue
                entry = dict(entry)
                if entry.get("enabled", True) is True:
                    entry.pop("enabled", None)
                cleaned.append(entry["command"] if list(entry) == ["command"]
                               else entry)
            events[ev] = cleaned
        cfg["events"] = events
        return cfg

    def _save(self) -> bool:
        cfg = self._collect()
        if self.runner.save(cfg):
            self._cfg = cfg
            return True
        return False

    def _on_save(self, _btn) -> None:
        msg = "Saved" if self._save() else "Could not save, see the log"
        self._toasts.add_toast(Adw.Toast(title=msg))

    def _on_test(self, ev: str) -> None:
        if not self._save():
            self._toasts.add_toast(Adw.Toast(title="Could not save, see the log"))
            return
        self.runner.fire(ev, machine_name="settings-test", status="TEST",
                         message="Test run from settings", force=True)
        self._toasts.add_toast(Adw.Toast(title=f"Ran '{ev}' commands"))