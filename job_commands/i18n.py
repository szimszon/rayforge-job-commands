import gettext
from pathlib import Path

DOMAIN = "job_commands"


def _find_localedir() -> Path:
    here = Path(__file__).resolve().parent
    for base in (here, here.parent):          # package dir, then repo root
        candidate = base / "locales"
        if candidate.is_dir():
            return candidate
    return here / "locales"


_t = gettext.translation(DOMAIN, localedir=_find_localedir(), fallback=True)
_ = _t.gettext


def N_(message: str) -> str:
    """Marks a string for extraction without translating it yet
    (for module-level constants such as the event labels)."""
    return message