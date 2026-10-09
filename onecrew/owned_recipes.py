"""Grant-bound fixed recipes for owned jobs. No worker-defined command or SDK path."""
from pathlib import Path
from .ledger import LedgerError, exact_fields


def validate(config):
    if config is None: return None
    exact_fields(config, ('flutter_root', 'android_sdk', 'dependency_root', 'dependency_policy',
                          'max_seconds', 'queue_seconds', 'native_authorized'), 'Android recipe grant')
    if config['native_authorized'] is not True: raise LedgerError('Native build requires explicit operator authorization.')
    if config['dependency_policy'] not in ('as-of', 'head'): raise LedgerError('Invalid dependency policy.')
    for key, low, high in (('max_seconds',10,1800),('queue_seconds',1,28800)):
        if type(config[key]) is not int or not low <= config[key] <= high: raise LedgerError('Invalid '+key)
    config = dict(config)
    for key in ('flutter_root','android_sdk','dependency_root'):
        if key == 'dependency_root' and config[key] is None: continue
        if not isinstance(config[key], str) or not Path(config[key]).is_absolute():
            raise LedgerError('Recipe '+key+' requires an absolute path.')
        config[key] = str(Path(config[key]).resolve())
    return config


def dispatch(runtime, task, state, args, profile):
    exact_fields(args, (), 'android_build arguments')
    config = validate(profile.get('android_build'))
    if not config: raise LedgerError('Android build recipe is not authorized for this job.')
    if len(state.get('branches', [])) != 1: raise LedgerError('Create one verified historical branch before building.')
    from .android_jobs import dispatch as launch
    # One immutable operation per job. A lost acknowledgement resumes this same key.
    key = 'owned-android-v1'
    result = launch(runtime.ledger, task, key, **config)
    state['operation'] = {'kind':'android_build','key':key}
    state.update(phase='waiting_operation', waiting_reason='operation')
    return {'operation_id':key,'status':result['status'],'waiting_uses_model':False}


def advance(runtime, task, state):
    from .android_jobs import reconcile, status
    from .android_build import verify_apk
    operation = state['operation']
    reconcile(runtime.ledger, task, operation['key'])
    result = status(runtime.ledger, task, operation['key'])
    if result['status'] == 'succeeded':
        artifact = result.get('apk') or result.get('build', {}).get('apk')
        if not artifact or verify_apk(Path(artifact['path'])) != artifact:
            raise LedgerError('Build artifact no longer matches verified receipt.')
        state['build_evidence'] = {'key':operation['key'],'apk':artifact,'device_tested':False}
        state.update(phase='running', message='APK verified; prepare evidence-based delivery.')
        state.pop('waiting_reason', None)
        return True
    if result['status'] in ('blocked','cancelled','interrupted'):
        state.update(phase='blocked', message=result.get('error') or 'Build '+result['status'],
                     recovery={'kind':'build','automatic_retry':False,'key':operation['key']})
        return True
    return False


def verify_completion(runtime, task, state, profile):
    if not profile.get('android_build'): return
    from .android_build import verify_apk
    evidence = state.get('build_evidence')
    if not evidence: raise LedgerError('Required Android build has no verified APK evidence.')
    artifact = evidence['apk']
    if verify_apk(Path(artifact['path'])) != artifact:
        raise LedgerError('APK changed after verification; cannot complete.')
