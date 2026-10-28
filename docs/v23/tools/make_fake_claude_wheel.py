"""make_fake_claude_wheel.py <out dir> - build the wheel of the FAKE `claude` command (the test double: no model, no network, no login).

Stdlib only. In a package this file sits in verify/ next to onecrew_fake_claude.py, which is what the wheel carries (as the console script
`claude`). It is the same wheel that verify_milestone.py builds for itself (V2). Installing it into a venv puts `claude.exe` in that venv's
Scripts folder; put that folder first on PATH in ONE PowerShell window and `onecrew engine step` runs the fake instead of a real model.
Only the drill (examples/first-task/README.vi.md, part A) uses it. Never install it where the real work runs.
Prints the path of the wheel it wrote."""
import base64
import hashlib
import sys
import zipfile
from pathlib import Path


def build(source, into):
    info = 'onecrew_fake_claude-0.1.dist-info'
    files = {'onecrew_fake_claude.py': Path(source).read_bytes(),
             f'{info}/METADATA': b'Metadata-Version: 2.1\nName: onecrew-fake-claude\nVersion: 0.1\n',
             f'{info}/WHEEL': b'Wheel-Version: 1.0\nGenerator: make_fake_claude_wheel\nRoot-Is-Purelib: true\nTag: py3-none-any\n',
             f'{info}/entry_points.txt': b'[console_scripts]\nclaude = onecrew_fake_claude:main\n'}
    lines = [f'{n},sha256={base64.urlsafe_b64encode(hashlib.sha256(d).digest()).decode().rstrip("=")},{len(d)}' for n, d in files.items()]
    files[f'{info}/RECORD'] = ('\n'.join(lines + [f'{info}/RECORD,,']) + '\n').encode()
    Path(into).mkdir(parents=True, exist_ok=True)
    path = Path(into) / 'onecrew_fake_claude-0.1-py3-none-any.whl'
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items(): archive.writestr(name, data)
    return path


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit(__doc__.split('\n', 1)[0])
    print(build(Path(__file__).resolve().with_name('onecrew_fake_claude.py'), sys.argv[1]))
