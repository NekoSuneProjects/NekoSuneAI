"""Process entry point.

Runs the three things that must happen before any interface starts - finish
first-time setup, apply a pending update, then hand off - and selects the
front end from the command line: the native desktop GUI, the browser
dashboard, or the terminal REPL.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys

from dotenv import load_dotenv

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

from .cli import main as cli_main  # noqa: E402
from .paths import ROOT_DIR  # noqa: E402
from .updater import (  # noqa: E402
    apply_update,
    check_for_updates,
    get_auto_update_check_enabled,
    get_auto_update_install_enabled,
)

SETUP_MARKER = ROOT_DIR / ".setup-complete"
SETUP_PY = ROOT_DIR / "setup.py"

_SKIP_UPDATE_ENV = "NEKOSUNEAI_SKIP_AUTO_UPDATE"
_DEFAULT_WEB_HOST = "0.0.0.0"
_DEFAULT_WEB_PORT = "8788"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run NekoSuneAI.")
    parser.add_argument(
        "--gui",
        action="store_true",
        help="Launch the native desktop GUI (needs a display + pywebview).",
    )
    parser.add_argument(
        "--web", action="store_true", help="Serve the browser dashboard."
    )
    parser.add_argument(
        "--web-host", default=os.getenv("WEB_DASHBOARD_HOST", _DEFAULT_WEB_HOST)
    )
    parser.add_argument(
        "--web-port",
        type=int,
        default=int(os.getenv("WEB_DASHBOARD_PORT", _DEFAULT_WEB_PORT)),
    )
    return parser


def ensure_setup() -> None:
    """Run first-time setup unless it has already completed."""
    if SETUP_MARKER.exists() or not SETUP_PY.exists():
        return

    print("First-time NekoSuneAI setup is incomplete. Running setup...")
    result = subprocess.run(
        [sys.executable, str(SETUP_PY), "--setup"],
        cwd=str(ROOT_DIR),
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def _relaunch_command() -> list[str]:
    """The argv that re-runs this application as it was originally started."""
    if getattr(sys, "frozen", False):
        # In a frozen build sys.executable is the application itself, and no
        # separate app.py ships beside it, so re-exec the executable directly.
        return [sys.executable, *sys.argv[1:]]
    return [sys.executable, str(ROOT_DIR / "app.py"), *sys.argv[1:]]


def restart_current_process() -> None:
    environment = os.environ.copy()
    environment[_SKIP_UPDATE_ENV] = "1"  # the child must not update again
    subprocess.Popen(_relaunch_command(), cwd=str(ROOT_DIR), env=environment)
    raise SystemExit(0)


def maybe_apply_startup_update() -> None:
    """Check GitHub for a newer release and, if configured to, install it."""
    if os.getenv(_SKIP_UPDATE_ENV) == "1":
        return

    load_dotenv()
    if not get_auto_update_check_enabled():
        return

    status = check_for_updates()
    if status.error:
        print(f"GitHub update check skipped: {status.error}")
        return
    if not status.update_available:
        return

    if not get_auto_update_install_enabled():
        print(
            f"NekoSuneAI {status.remote_version} is available on GitHub. "
            "Run `python setup.py --update` when you want to install it."
        )
        return

    print(
        f"NekoSuneAI {status.remote_version} is available on GitHub. "
        f"Updating from {status.local_version} now..."
    )
    try:
        apply_update()
    except Exception as exc:
        print(f"Auto-update skipped: {exc}")
        return

    print("NekoSuneAI finished updating. Restarting with the latest files...")
    restart_current_process()


def _run_gui() -> None:
    from .webgui import main as gui_main

    gui_main()


def _run_web(host: str, port: int) -> None:
    from .webserver import serve

    serve(host, port, os.getenv("WEB_DASHBOARD_TOKEN") or None)


def main() -> None:
    args = build_parser().parse_args()

    ensure_setup()
    maybe_apply_startup_update()

    # Front ends are imported lazily so a CLI run never pays for GUI or web deps.
    if args.gui:
        _run_gui()
    elif args.web:
        _run_web(args.web_host, args.web_port)
    else:
        cli_main()
