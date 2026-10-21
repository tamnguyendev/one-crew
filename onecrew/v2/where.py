"""Where a project's OneCrew state lives, for the commands that run without --project / --state-root (the installed hooks and `onecrew init`).

* The project: `--project`, else CLAUDE_PROJECT_DIR (set by Claude Code for every hook), else the hook event's cwd, else the process cwd.
* The state root: `--state-root`, else `<project>/.onecrew/config.json` {"state_root": ...} (written by `onecrew init`), else (hooks only) the registry
  `onecrew init` also wrote outside the project, else the system default (the same default the Ledger uses). Stdlib only: `hook check` imports this
  before every tool call.
"""
import json
import os
import uuid
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


def configured_state_root(project=None):
    """The state root named by config.json: of the git root at or above `project` (the cwd when None) first, then of `project` itself. None when neither has one."""
    try:
        start = Path(project) if project else Path.cwd()
        top = git_root(start)
        for directory in ([top] if top else []) + [start]:
            value = read_config(directory).get('state_root')
            if isinstance(value, str) and value.strip(): return Path(value)
    except (OSError, TypeError, ValueError):
        pass
    return None


def state_root_for(project, explicit=None):
    """Explicit value first, then config.json; None leaves the choice to the Ledger default."""
    return Path(explicit) if explicit else configured_state_root(project)


# ---- the registry: where `onecrew init` recorded a project's state root, outside the project --------------------------------------------

REGISTRY = 'hook-projects.json'


def registry_file():
    return default_state_root() / REGISTRY


def _key(project):
    return os.path.normcase(str(Path(project).resolve()))


def registered_state_root(project):
    """The state root that `onecrew init` recorded for this very project in the registry (<default state root>/hook-projects.json, a place outside the
    project), or None. The hook falls back to it when `.onecrew/config.json` is gone, so deleting `.onecrew/` does not hide a custom state root."""
    try:
        value = json.loads(registry_file().read_text(encoding='utf-8-sig'))
        found = (value.get('projects') or {}).get(_key(project)) if isinstance(value, dict) else None
        return Path(found) if isinstance(found, str) and found.strip() else None
    except (OSError, ValueError, TypeError, AttributeError):
        return None


def register_project(project, state_root):
    """Record `project` -> `state_root` in the registry (entries of projects that no longer exist are dropped). Never raises: a registry that cannot be
    written leaves `.onecrew/config.json` as the only pointer, as before."""
    try:
        path = registry_file()
        try:
            value = json.loads(path.read_text(encoding='utf-8-sig'))
        except (OSError, ValueError):
            value = {}
        old = value.get('projects') if isinstance(value, dict) and isinstance(value.get('projects'), dict) else {}
        projects = {k: v for k, v in old.items() if isinstance(v, str) and Path(k).is_dir()}
        projects[_key(project)] = str(state_root)
        if projects == old: return
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
        temporary.write_text(json.dumps({'projects': projects}, indent=2, ensure_ascii=False), encoding='utf-8')
        os.replace(temporary, path)
    except (OSError, ValueError, TypeError):
        pass


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


def repository_dirs(start):
    """`start` and its parents up to and including the repository root (the first one holding a .git), nearest first; no directory above the
    repository is ever in the list. Outside any repository only `start` itself: there is no boundary to search up to."""
    here = Path(start).resolve()
    top = git_root(here)
    if top is None: return [here]
    return [directory for directory in (here, *here.parents) if directory == top or top in directory.parents]
