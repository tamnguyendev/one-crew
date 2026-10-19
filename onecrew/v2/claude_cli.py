"""Where the Claude CLI is and which model v2 asks by default: the one module both the reviewer verifier and the advisor (plan advise) use.

* `cli_argv(env)`: `claude` on the PATH of the (filtered) environment first, then the places a per-user install or an npm global install puts it
  on this operating system. The error names every place that was searched.
* `DEFAULT_MODEL` / `default_model()`: the model an advisor call uses when none is given; the environment variable ONECREW_DEFAULT_MODEL
  overrides it. A milestone's reviewer model is never defaulted: the contract names it.
"""
import ntpath
import os
import posixpath
import shutil

from ..ledger import LedgerError

DEFAULT_MODEL = 'claude-opus-5-5'
MODEL_ENV = 'ONECREW_DEFAULT_MODEL'


def default_model(env=None):
    """The default model id: ONECREW_DEFAULT_MODEL when set and not blank, else DEFAULT_MODEL."""
    value = (os.environ if env is None else env).get(MODEL_ENV, '').strip()
    return value or DEFAULT_MODEL


def search_places(env=None, osname=None, home=None):
    """The fallback locations for the Claude CLI, best first, written for `osname` ('nt' or 'posix'; default: this system). Pure: touches no file."""
    env = os.environ if env is None else env
    osname = osname or os.name
    home = home or os.path.expanduser('~')
    if osname == 'nt':
        join = ntpath.join
        places = [join(home, '.local', 'bin', 'claude.exe'), join(home, '.claude', 'local', 'claude.exe')]
        appdata = env.get('APPDATA') or join(home, 'AppData', 'Roaming')
        prefix = env.get('NPM_CONFIG_PREFIX')
        for base in ([prefix] if prefix else []) + [join(appdata, 'npm')]:
            places += [join(base, 'claude.cmd'), join(base, 'claude.exe')]
        return places
    join = posixpath.join
    places = [join(home, '.local', 'bin', 'claude'), join(home, '.claude', 'local', 'claude')]
    prefix = env.get('NPM_CONFIG_PREFIX')
    places += [join(prefix, 'bin', 'claude')] if prefix else []
    places += [join(home, '.npm-global', 'bin', 'claude'), '/usr/local/bin/claude', '/opt/homebrew/bin/claude', '/usr/bin/claude']
    return places


def cli_argv(env, osname=None, home=None, which=shutil.which, exists=os.path.isfile):
    """The Claude CLI as an argv prefix. (Tests replace this, or pass `osname`, `home`, `which` and `exists` to simulate a system.)"""
    path = env.get('PATH', '')
    found = which('claude', path=path)
    if found: return [found]
    places = search_places(env, osname, home)
    for place in places:
        if exists(place): return [place]
    raise LedgerError('The Claude CLI was not found. Searched: `claude` on PATH (' + (path if len(path) < 300 else path[:300] + '...')
                      + '), then ' + ', '.join(places) + '. Install it or put it on PATH.')
