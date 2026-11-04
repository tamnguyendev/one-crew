"""Installed plan window: same mapped/close receipt logic as v1."""
from pathlib import Path
import sys
from ..desktop_window_core import show as show_core
from .exceptions import desktop_snapshots
from .notification_cli import text_report


def show(root, key):
    return show_core(root, key, snapshots=desktop_snapshots, text_report=text_report)


if __name__ == '__main__':
    show(Path(sys.argv[1]).resolve(), sys.argv[2])
