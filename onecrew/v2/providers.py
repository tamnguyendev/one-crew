"""Reviewer and advisor providers (W43, P1.0): `claude`, `codex` and `kiro` as read-only command-line calls with one shared shape.

A contract names the provider and the model of its reviewer (milestone.verifier.config) and of its advisor (the optional top-level `advisor`);
changing the provider is a change of those two fields, never of code. Every provider is one headless CLI call: the prompt in, the answer out,
no session file, an EMPTY working directory, and no permission to write:

  claude   claude -p --output-format json --model M --tools '' ...        (reviewer.call builds it; unchanged since v2.1)
  codex    codex exec -s read-only --ephemeral --skip-git-repo-check -m M --json --color never -     (prompt on stdin)
  kiro     kiro-cli chat --no-interactive --trust-tools=fs_read --model M --output-format stream-json [prompt]

Nothing here chooses a provider: when one is out of quota the call ends `quota_exhausted` and the verdict is `inconclusive` with the reason; the
next provider is never tried. A provider answers pass / fail / inconclusive (reviewer) or ok / objection (advisor), never a decision.

Not verified against a real CLI (W45 / T40b does that): the live behaviour of the `codex exec` and `kiro-cli chat` argv above and of the shapes of
their output events. The argv is taken from the v1 adapters that were verified (onecrew/workflow.py CodexArtifact, onecrew/providers.py kiro_argv, with
docs/kiro-cli-2.29.0-evidence.json) and from the shape T40a asks for. Where a CLI sends something else, the answer is `inconclusive`, never a pass.

The command of a provider can be configured: the environment variable ONECREW_<PROVIDER>_CLI (CLAUDE, CODEX, KIRO) holds a path, or a JSON list that is the
argv prefix (tests use it to put a fake in place of the CLI). It is read from the process environment, not from the filtered one the CLI sees.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess

from ..independence import author_vendor
from ..ledger import LedgerError

PROVIDERS = ('claude', 'codex', 'kiro')
CLI_ENV = {'claude': 'ONECREW_CLAUDE_CLI', 'codex': 'ONECREW_CODEX_CLI', 'kiro': 'ONECREW_KIRO_CLI'}
PROGRAM = {'claude': 'claude', 'codex': 'codex', 'kiro': 'kiro-cli'}
QUOTA = 'quota_exhausted'                 # the provider_error kind, and the prefix of the error text, of a call that ended on a usage limit
MAX_ANSWER = 200_000
KIRO_ARG_CAP = 16_000                     # characters the v1 adapter verified on a Windows command line; a longer prompt goes on stdin (NOT verified)
VERSION_SECONDS = 15
QUOTA_CODES = ('usage_limit_exceeded', 'quota_exhausted', 'insufficient_quota')
QUOTA_TEXT = ("hit your usage limit", "hit your limit", "usage limit has been reached", 'usage limit', 'quota exceeded', 'quota exhausted',
              'out of credits', 'no credits', 'credit limit', 'insufficient_quota')
ANSI = re.compile(r'\x1b\[[0-9;?]*[ -/]*[@-~]')


# ---- who is the vendor, and may this reviewer review that author ------------------------------------------------------------

def model_vendor(model):
    """The vendor a model id belongs to, or None when the id says nothing (claude-* -> claude, gpt-*/o3/codex -> codex, gemini-* -> google)."""
    name = str(model).lower()
    if name.startswith(('claude', 'anthropic')): return 'claude'
    if name.startswith(('gpt', 'codex', 'chatgpt', 'openai')) or re.match(r'o[1-9]([-.]|$)', name): return 'codex'
    if name.startswith('gemini'): return 'google'
    return None


def reviewer_vendor(provider, model):
    """Whose model reviews: the provider's own for claude and codex; for kiro (a gateway to several vendors) the vendor of the model chosen."""
    if provider == 'kiro': return model_vendor(model) or 'kiro'
    return provider


def _same_model(a, b):
    norm = lambda m: re.sub(r'[.\-_]+', '-', str(m).lower())
    return norm(a) == norm(b)


def independence(author, author_model, provider, model):
    """How independent a codex/kiro reviewer is from one author (the claude path is onecrew.independence, unchanged). Judged by vendor: another vendor
    is independent; the same vendor needs a known author model that differs from the reviewer's, and the same vendor with the same model is refused.
    Raises LedgerError, so a refusal costs no call."""
    if provider not in PROVIDERS: raise LedgerError('Reviewer provider ' + str(provider) + ' is not one of ' + ', '.join(PROVIDERS) + '.')
    vendor, theirs = reviewer_vendor(provider, model), author_vendor(author, None) or model_vendor(author_model or '')
    base = {'author_vendor': theirs, 'author_model': author_model, 'reviewer_provider': provider, 'reviewer_model': model, 'reviewer_vendor': vendor}
    if theirs is None:
        return dict(base, level='unknown_author_vendor', note='The author vendor is unknown, so independence cannot be shown.')
    if theirs != vendor:
        return dict(base, level='cross_vendor', note='The reviewer is another vendor than the author.')
    if author_model and _same_model(author_model, model):
        raise LedgerError('The reviewer would be the author (same vendor and model); choose another reviewer model.')
    if not author_model:
        raise LedgerError(f'The author is {theirs} and the reviewer model {model} ({provider}) is {vendor} too: record the author model so a reviewer '
                          'model that differs from the author\'s can be shown. An unknown author model is not accepted as independent.')
    return dict(base, level='same_vendor_other_model', note='A different model of the same vendor reviews.')


# ---- finding and building the command ---------------------------------------------------------------------------------------

def places(provider, home=None):
    """Where a CLI is looked for after PATH (codex/kiro; claude has its own finder in claude_cli)."""
    home = home or os.path.expanduser('~')
    if provider == 'kiro':
        local = os.environ.get('LOCALAPPDATA') or os.path.join(home, 'AppData', 'Local')
        return [os.path.join(local, 'Kiro-Cli', 'kiro-cli.exe'), os.path.join(home, '.local', 'bin', 'kiro-cli')]
    if provider == 'codex':
        return [os.path.join(os.environ.get('APPDATA') or os.path.join(home, 'AppData', 'Roaming'), 'npm', 'codex.cmd'), os.path.join(home, '.local', 'bin', 'codex')]
    return []


def cli_prefix(provider, env, config_env=None, which=shutil.which, exists=os.path.isfile):
    """The CLI of `provider` as an argv prefix: the configured one (ONECREW_<P>_CLI), else the program on the PATH of `env`, else the usual places.
    The error names everything searched. Never falls back to another provider."""
    if provider not in PROVIDERS: raise LedgerError('Unknown provider ' + str(provider) + '.')
    configured = (os.environ if config_env is None else config_env).get(CLI_ENV[provider], '').strip()
    if configured:
        if configured.startswith('['):
            try:
                parsed = json.loads(configured)
            except ValueError:
                parsed = None
            if not (isinstance(parsed, list) and parsed and all(isinstance(p, str) and p for p in parsed)):
                raise LedgerError(CLI_ENV[provider] + ' is not a JSON list of strings.')
            return parsed
        return [configured]
    path = env.get('PATH', '')
    found = which(PROGRAM[provider], path=path)
    if found: return [found]
    spots = places(provider)
    for spot in spots:
        if exists(spot): return [spot]
    raise LedgerError(f'The {provider} CLI ({PROGRAM[provider]}) was not found. Searched: PATH ({path[:200]}), ' + (', '.join(spots) + ', ' if spots else '')
                      + CLI_ENV[provider] + '. Install it or set ' + CLI_ENV[provider] + '.')


def build_argv(provider, prefix, model, prompt=None):
    """(argv, stdin_text) of a read-only call. `prompt` is needed only for kiro, which takes a short prompt as an argument. No write permission is
    granted by any argument: codex runs in the read-only sandbox; kiro trusts only fs_read."""
    if provider == 'codex':
        return [*prefix, 'exec', '-s', 'read-only', '--ephemeral', '--skip-git-repo-check', '-m', model, '--json', '--color', 'never', '-'], prompt
    if provider == 'kiro':
        argv = [*prefix, 'chat', '--no-interactive', '--trust-tools=fs_read', '--model', model, '--output-format', 'stream-json']
        if prompt is not None and len(prompt) <= KIRO_ARG_CAP: return argv + [prompt], None
        return argv, prompt
    raise LedgerError('The claude call is built by reviewer.call.')


# ---- the process, and what came back ------------------------------------------------------------------------------------------

def run_process(argv, stdin_text, scratch, env, limit):
    """(stdout, stderr, returncode, timed_out, os_error). stdin_text None: nothing is sent. `limit` is in minutes."""
    from .verifiers import command
    out, err, timed_out = b'', b'', False
    try:
        process = subprocess.Popen(argv, cwd=scratch, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   creationflags=0x08000000 if os.name == 'nt' else 0)
        try:
            out, err = process.communicate((stdin_text or '').encode('utf-8'), timeout=limit * 60)
        except subprocess.TimeoutExpired:
            timed_out = True
            command._kill_tree(process)
            out, err = process.communicate()
    except OSError as problem:
        return b'', b'', None, False, f'{type(problem).__name__}: {problem}'[:300]
    return out, err, process.returncode, timed_out, None


def is_quota(value):
    """Is this error envelope (a code, or the CLI's own message) a usage limit? Only the CLI's error text is judged, never the model's answer."""
    if isinstance(value, dict):
        if value.get('code') in QUOTA_CODES: return True
        value = value.get('message') or value.get('error')
        if isinstance(value, dict): return is_quota(value)
    return isinstance(value, str) and any(marker in value.lower() for marker in QUOTA_TEXT)


def quota_error(provider, text):
    return f'{QUOTA}: {provider} reported a usage limit: {str(text)[:200]}'


CREDENTIAL_MISSING = 'credential_missing'    # the provider_error kind, and the prefix of the error text, of an api call refused before any process: no key


def error_kind(error):
    """The provider_error kind of an error text: quota_exhausted, credential_missing (2.3 hotfix: api chosen, no key, nothing run), or
    provider_unavailable for any other error; None when there is none."""
    if not error: return None
    for kind in (QUOTA, CREDENTIAL_MISSING):
        if str(error).startswith(kind + ':'): return kind
    return 'provider_unavailable'


def _events(text):
    for line in text.splitlines():
        line = line.strip()
        if line.startswith('{'):
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict): yield event


def _message(value):
    if isinstance(value, dict): return value.get('message') or value.get('error') or json.dumps(value)[:200]
    return value


def parse_codex(text):
    """(answer, usage, error) from `codex exec --json` (JSON lines): the last agent_message is the answer; a turn.failed or error event is the error;
    an item that is a file change or a tool call outside the read-only sandbox is an error, not an answer."""
    answer, usage, errors, forbidden = None, {}, [], None
    for event in _events(text):
        kind = event.get('type')
        item = event.get('item') if isinstance(event.get('item'), dict) else {}
        if kind == 'item.completed':
            if item.get('type') == 'agent_message' and isinstance(item.get('text'), str): answer = item['text']
            elif item.get('type') not in (None, 'reasoning', 'agent_message', 'command_execution'): forbidden = forbidden or item.get('type')
        elif kind == 'turn.completed':
            usage = {'usage': event.get('usage')}
        elif kind in ('turn.failed', 'error'):
            errors.append(_message(event.get('error') if event.get('error') is not None else event.get('message')))
    if forbidden: return '', usage, f'codex attempted {forbidden}, outside a read-only review'
    if errors:
        why = ' / '.join(str(e) for e in errors if e)[:300] or 'codex reported an error'
        return '', usage, quota_error('codex', why) if any(is_quota(e) for e in errors) else why
    if answer is None: return '', usage, 'codex sent no final message'
    return answer, usage, None


def parse_kiro(text):
    """(answer, usage, error) from `kiro-cli chat --output-format stream-json`: the agent_message_chunk texts, ended by a successful runFinished.
    Output with no JSON events at all is taken as plain text (still parsed strictly by the caller)."""
    chunks, usage, finished, seen = [], {}, None, False
    for event in _events(text):
        seen = True
        data = event.get('data') if isinstance(event.get('data'), dict) else {}
        update = data.get('update') or (event.get('params') or {}).get('update') or event.get('update') or {}
        if update.get('sessionUpdate') == 'agent_message_chunk' and (update.get('content') or {}).get('type') == 'text':
            chunks.append(update['content'].get('text') or '')
        if event.get('type') == 'metadata' and 'meteringUsage' in data: usage = {'metering': data['meteringUsage']}
        if event.get('type') == 'runFinished': finished = data
    if not seen:
        plain = ANSI.sub('', text).strip()
        return (plain, usage, None) if plain else ('', usage, 'kiro sent no output')
    if finished is None: return '', usage, 'kiro stream has no runFinished event'
    if finished.get('status') != 'success':
        why = str(_message(finished.get('error')) or finished.get('status'))[:300]
        return '', usage, quota_error('kiro', why) if is_quota(finished.get('error')) else 'kiro run did not succeed: ' + why
    if finished.get('finalTextTruncated') is True: return '', usage, 'kiro answer was truncated'
    return ''.join(chunks).strip(), usage, None


def call(provider, prompt, model, env, scratch, limit):
    """One read-only call of a codex or kiro CLI: (answer, usage, error, timed_out, raw_stdout), the shape reviewer.call returns."""
    try:
        prefix = cli_prefix(provider, env)
    except LedgerError as problem:
        return '', {}, str(problem)[:300], False, b''
    argv, stdin_text = build_argv(provider, prefix, model, prompt)
    out, err, code, timed_out, os_error = run_process(argv, stdin_text, scratch, env, limit)
    if os_error: return '', {}, os_error, False, b''
    if timed_out: return '', {}, None, True, out
    text, stderr = out.decode('utf-8', 'replace'), err.decode('utf-8', 'replace')
    answer, usage, error = (parse_codex if provider == 'codex' else parse_kiro)(text)
    if error is None and code: error = f'{provider} CLI exited with {code}: {(stderr or text)[:200]}'     # it said it failed although it sent an answer: not trusted
    if error is None and not answer: error = f'{provider} sent an empty answer'
    if error and not error.startswith(QUOTA + ':'):
        if is_quota(stderr): error = quota_error(provider, stderr)
        elif stderr.strip() and not text.strip(): error = (error + ' | stderr: ' + stderr.strip())[:300]
    return ('' if error else answer[:MAX_ANSWER]), usage, error, False, out


# ---- what W45 records about a real CLI -------------------------------------------------------------------------------------------

def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''): digest.update(block)
    return digest.hexdigest()


def cli_identity(provider, env=None, prefix=None, timeout=VERSION_SECONDS):
    """Which CLI this is: the argv prefix, the path and sha256 of the executable (and of every other file in the prefix, such as a script), and the
    output of `--version`. Nothing is written. For the matrix of T40b: a receipt of a fake can be told from a real one by this sha256."""
    env = os.environ if env is None else env
    prefix = prefix or cli_prefix(provider, dict(env))
    files, identity_errors = {}, {}
    for path in prefix:
        if os.path.isfile(path):
            try:
                files[path] = sha256_file(path)
            except OSError as problem:
                # Windows execution aliases can launch but cannot be read as files.
                # Keep identity explicitly incomplete, never invent a binary hash.
                identity_errors[path] = type(problem).__name__
    try:
        done = subprocess.run([*prefix, '--version'], capture_output=True, timeout=timeout, env=dict(env), stdin=subprocess.DEVNULL,
                              creationflags=0x08000000 if os.name == 'nt' else 0)
        version = (done.stdout or done.stderr).decode('utf-8', 'replace').strip()[:200]
    except (OSError, subprocess.SubprocessError) as problem:
        version = f'unavailable: {type(problem).__name__}'
    return {'provider': provider, 'argv': list(prefix), 'path': prefix[0], 'sha256': files.get(prefix[0]), 'files': files, 'version': version,
            **({'identity_errors': identity_errors} if identity_errors else {})}


# ---- capabilities (W50b / TD19) -------------------------------------------------------------------------------------------

# Declared image observers, by provider. Empty in the product: the three read-only CLI calls above are text-only and no vision path has been
# verified against a real CLI, so `vision()` says so instead of claiming to read the image. An adapter is injected here (tests, or a later verified
# adapter) — never inferred from the model name.
VISION_ADAPTERS = {}


def vision(provider):
    """The capability declaration `localization.localize` consumes for `--provider`: name, capabilities, observe_image.

    Without a declared adapter the capabilities are empty, so the image is never opened and the result says "không đọc ảnh"; the declaration
    also carries the reason, for the report."""
    if provider not in PROVIDERS:
        raise LedgerError(f'provider {provider!r}: expected one of {", ".join(PROVIDERS)}.')
    adapter = VISION_ADAPTERS.get(provider)
    return {'name': provider, 'capabilities': ['vision'] if callable(adapter) else [], 'observe_image': adapter,
            'reason': None if callable(adapter) else f'provider {provider} declares no vision adapter (text-only CLI call; not verified on a real CLI)'}
