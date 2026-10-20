"""Where a project's OneCrew state lives, for the commands that run without --project / --state-root (the installed hooks and `onecrew init`).

* The project: `--project`, else CLAUDE_PROJECT_DIR (set by Claude Code for every hook), else the hook event's cwd, else the process cwd.
* The state root: `--state-root`, else `<project>/.onecrew/config.json` {"state_root": ...} (written by `onecrew init`), else the system default
  (the same default the Ledger uses). Stdlib only: `hook check` imports this before every tool call.
"""
import json
import os
from pathlib import Path

CONFIG = 'config.json'


def default_state_root():
    """The state root of a Ledger given none: %LOCALAPPDATA%\\OneCrew on Windows, ~/.onecrew elsewhere."""
    local = os.environ.get('LOCALAPPDATA')
    return (Path(local) / 'OneCrew' if local else Path.home() / '.onecrew').resolve()


def config_file(project):
    return Path(project) / '.onecrew' / CONFIG


def read_config(project):
    """The parsed config.json of a project, or {} when it is missing or unreadable."""
    try:
        value = json.loads(config_file(project).read_text(encoding='utf-8-sig'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def configured_state_root(project):
    """The state root named by <project>/.onecrew/config.json, or None."""
    value = read_config(project).get('state_root')
    return Path(value) if isinstance(value, str) and value.strip() else None


def state_root_for(project, explicit=None):
    """Explicit value first, then config.json; None leaves the choice to the Ledger default."""
    return Path(explicit) if explicit else configured_state_root(project)


def project_from_environment(event_cwd=None):
    for start in (os.environ.get('CLAUDE_PROJECT_DIR'), event_cwd, os.getcwd()):
        if start: return Path(start)
    return Path.cwd()


def git_root(start):
    """The directory at or above `start` that holds a .git (directory or file, as in a worktree); None when there is none."""
    here = Path(start).resolve()
    for directory in (here, *here.parents):
        if (directory / '.git').exists(): return directory
    return None
