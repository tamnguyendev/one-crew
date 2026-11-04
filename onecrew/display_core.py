"""Existing v1 log redaction; delivery never interprets content as commands."""
import re

SECRET = re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY|'
                    r'\b(?:ghp_|github_pat_|sk-proj-|sk-ant-|apikey_)[A-Za-z0-9_-]{15,}|'
                    r'(?im:^\s*(?:[A-Z_]*(?:PASSWORD|SECRET|API_KEY|ACCESS_TOKEN))\s*[=:]\s*["\x27]?[^\s"\x27]{8,})|'
                    r'(?i:["\x27](?:[a-z_]*(?:password|secret|api_key|access_token|refresh_token|auth_token))["\x27]\s*:\s*["\x27][^"\x27]{8,})')

def safe(value, limit=180):
    text=str(value or '')
    if SECRET.search(text) or re.search(r'(?i)(password|secret|token|api.?key)\s*[=:]',text):
        return '[sensitive content withheld]'
    text=re.sub(r'https?://[^\s/@]+:[^\s/@]+@[^\s]+','[credential URL withheld]',text)
    # Never allow logs/model output to inject terminal control sequences.
    text=re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07]*(?:\x07|\x1b\\)', '', text)
    text=''.join(c if c.isprintable() else ' ' for c in text)
    return text[:limit]+('…' if len(text)>limit else '')
