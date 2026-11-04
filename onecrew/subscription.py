"""Child-only subscription environment; never edit the user's credentials/settings."""
import os

UTF8_ENV = {'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8'}

CODEX_AUTH_ARGS = ['-c', 'forced_login_method="chatgpt"', '-c', 'model_provider="openai"']
CLAUDE_AUTH_ARGS = ['--restricted', '--safe-mode', '--settings',
                    '{"disableAllHooks":true,"forceLoginMethod":"claudeai"}']


def environment(source=None):
    source = os.environ if source is None else source
    # Case insensitive on Windows. Keep the subscription OAuth token, if supplied,
    # but not API keys, alternate endpoints or third-party provider selectors.
    def allowed(key):
        key = key.upper()
        if key == 'CLAUDE_CODE_OAUTH_TOKEN':
            return True
        return not (key.startswith(('OPENAI_', 'ANTHROPIC_', 'CLAUDE_CODE_USE_',
                                    'CLAUDE_CODE_API_KEY_HELPER'))
                    or key in {'CODEX_API_KEY', 'CHATGPT_BASE_URL', 'CLAUDE_CODE_SIMPLE'})
    env = {key: value for key, value in source.items() if allowed(key)}
    env.update(UTF8_ENV)  # the CLI's Bash/Python children must not fall back to a legacy console codepage
    return env
