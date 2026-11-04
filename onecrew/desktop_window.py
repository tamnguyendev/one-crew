"""v1 desktop window entry point, using the shared outbox implementation."""
from pathlib import Path
import sys
from .desktop_notifications import snapshots, text_report
from .desktop_window_core import show as show_core


def show(root, key):
    return show_core(root, key, snapshots=snapshots, text_report=text_report)


if __name__ == '__main__':
    show(Path(sys.argv[1]).resolve(), sys.argv[2])
