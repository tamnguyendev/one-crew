"""Where a project's OneCrew state lives, for the commands that run without --project / --state-root (the installed hooks and `onecrew init`).

* The project: `--project`, else CLAUDE_PROJECT_DIR (set by Claude Code for every hook), else the hook event's cwd, else the process cwd.
* The state root: `--state-root`, else `<project>/.onecrew/config.json` {"state_root": ...} (written by `onecrew init`), else (hooks only) the registry
  `onecrew init` also wrote outside the project, else the system default (the same default the Ledger uses). Stdlib only: `hook check` imports this
  before every tool call.
"""
import json
import os
import time
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


def configured(project=None):
    """(directory, state root) of the config.json that names a state root: of the git root at or above `project` (the cwd when None) first, then of `project`
    itself. (None, None) when neither has one."""
    try:
        start = Path(project) if project else Path.cwd()
        top = git_root(start)
        for directory in ([top] if top else []) + [start]:
            value = read_config(directory).get('state_root')
            if isinstance(value, str) and value.strip(): return directory, Path(value)
    except (OSError, TypeError, ValueError):
        pass
    return None, None


def configured_state_root(project=None):
    """The state root named by config.json (see `configured`). None when there is none."""
    return configured(project)[1]


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
        found = _read_registry(registry_file()).get(_key(project))
        return Path(found) if found and found.strip() else None
    except (OSError, ValueError, TypeError):
        return None


def _read_registry(path):
    try:
        value = json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return {}
    projects = value.get('projects') if isinstance(value, dict) else None
    return {k: v for k, v in projects.items() if isinstance(k, str) and isinstance(v, str)} if isinstance(projects, dict) else {}


def _gone(key):
    """A project directory that is missing while its drive (or filesystem root) is there. A missing directory on a drive that is not mounted right now is
    not gone: it may be back tomorrow, and its entry stays."""
    here = Path(key)
    return not here.exists() and bool(here.anchor) and Path(here.anchor).exists()


def register_project(project, state_root):
    """Record `project` -> `state_root` in the registry. The hook calls this every time it reads a project's config.json (and `onecrew init` does), so the
    entry exists for every project the hook has seen. Nothing is written when the entry is already there. A write takes a short lock file and goes through a
    temporary file renamed over the registry, so two writers cannot tear it or drop each other's entry; when it does write, entries of directories that are gone
    from a mounted drive are dropped. Never raises: a registry that cannot be written leaves `.onecrew/config.json` as the only pointer, as before."""
    try:
        path = registry_file()
        old = _read_registry(path)
        if old.get(_key(project)) == str(state_root): return
        path.parent.mkdir(parents=True, exist_ok=True)
        lock = path.with_name(path.name + '.lock')
        deadline = time.monotonic() + 3
        while True:
            try:
                os.close(os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY))
                break
            except FileExistsError:
                try:
                    if time.time() - lock.stat().st_mtime > 10: lock.unlink()          # a writer that died holding it
                except OSError:
                    pass
                if time.monotonic() > deadline: return
                time.sleep(0.02)
        try:
            projects = {k: v for k, v in _read_registry(path).items() if not _gone(k)}          # read again under the lock: another writer may have added an entry
            projects[_key(project)] = str(state_root)
            temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
            temporary.write_text(json.dumps({'projects': projects}, indent=2, ensure_ascii=False), encoding='utf-8')
            os.replace(temporary, path)
        finally:
            try:
                lock.unlink()
            except OSError:
                pass
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
