"""Validate the packaged UI in a real browser outside the checkout.

python -I <package>/verify/obs2_artifact_browser.py <package> <verified trial>
Imports only packaged harnesses and the installed wheel in a child interpreter.
"""
import importlib.util
import json
import os
from pathlib import Path
import sys

sys.dont_write_bytecode = True


def main(package, work):
    package, work = Path(package).resolve(), Path(work).resolve()
    spec = importlib.util.spec_from_file_location('obs2_verify', package / 'verify/verify_obs2.py')
    verify = importlib.util.module_from_spec(spec); spec.loader.exec_module(verify)
    manifest, _ = verify.package_identity(package)
    report = json.loads((work / 'verify-report.json').read_text(encoding='utf-8'))
    if report.get('result') != 'pass' or report.get('manifest') != manifest:
        raise ValueError('Trial verifier has not passed for this exact package.')
    if not (work / 'venv/Scripts/python.exe').is_file(): raise ValueError('Run package verifier first.')
    out = work / 'browser'; out.mkdir(exist_ok=True)
    sys.path.insert(0, str(package / 'verify'))
    from tests import obs1_ux_harness as ux
    from tests.obs2_ux_harness import HARNESS
    ux.HARNESS = HARNESS
    choices = [Path(os.environ.get('PROGRAMFILES', 'C:/Program Files')) / 'Google/Chrome/Application/chrome.exe',
               Path(os.environ.get('PROGRAMFILES(X86)', 'C:/Program Files (x86)')) / 'Microsoft/Edge/Application/msedge.exe']
    browser = next((str(p) for p in choices if p.is_file()), None)
    if not browser: raise ValueError('Browser missing; artifact browser verification is NOT passed.')
    state = work / 'state'
    if not state.is_dir(): raise ValueError('Expected synthetic fixture state from package verifier.')
    env = verify.isolated_env(work)
    before = verify.digest_tree(state)
    def cli(*args):
        return json.loads(verify.run([work / 'venv/Scripts/python.exe', '-I', '-X', 'utf8', '-m', 'onecrew.v2.tracking_cli',
            '--project', work / 'project', '--state-root', state, 'track', *args], env=env, cwd=out))
    proxy, identity = None, None
    result = {'commit': manifest['code_commit'], 'wheel': manifest['wheel'], 'results': {}, 'ok': False}
    try:
        identity = cli('open', '--no-browser', '--project-only')
        if identity.get('reused'): raise ValueError('Another trial viewer is already running; stop it before browser verification.')
        if identity['version'] != manifest['version']: raise ValueError('Unexpected installed version.')
        proxy = ux.Proxy(identity['url'])
        profile = out / 'profile'
        for size in ('desktop', 'mobile'):
            width, height = ux.SIZES[size]
            value = ux.run(browser, proxy.url, 'work', width, height, profile, budget=45000)
            result['results'][size] = value
            if not value.get('ok'): raise ValueError('Browser assertions failed: '+json.dumps(value, ensure_ascii=False))
        for view in ('board', 'overview', 'solution', 'results', 'decision'):
            if not ux.screenshot(browser, proxy.url, 'work', 1280, 900, profile, out / (view+'.png'), budget=45000, extra='&view='+view):
                raise ValueError('Screenshot missing: '+view)
        if verify.digest_tree(state) != before: raise ValueError('Browser changed trial state.')
        result['ok'] = True
    finally:
        if proxy: proxy.stop()
        if identity and not identity.get('reused'):
            try:
                stopped = cli('stop', '--url', identity['url'], '--instance', identity['instance'], '--pid', str(identity['pid']), '--started-at', identity['started_at'])
                if not stopped.get('stopped'): raise ValueError('Trial viewer did not stop.')
                result['stop'] = stopped
            except Exception as error:
                result['ok'], result['stop_error'] = False, str(error)
        (out / 'browser-report.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))
    if not result['ok']: raise SystemExit(1)


if __name__ == '__main__':
    main(*sys.argv[1:])
