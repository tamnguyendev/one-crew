"""Shared v1 bounded recovery decisions; no delivery-specific executor imported."""
from .ledger import content_hash, utcnow

POLICY_VERSION = 1
# class -> (automatic action, automatic attempts per failure signature before asking the user)
POLICY = {
    'transient': ('retry', 3),
    'interrupted': ('replay', 1),
    'environment': ('retry', 2),
    'product': ('repair', 2),
    'review': ('repair', 2),
    # A selector of a OneCrew-planned scenario that did not resolve on the live UI: recalibrate from its snapshot.
    'scenario_selector': ('calibrate', 2),
    # A pinned exact selector that does not match on a real device: stop at once with masked evidence.
    'selector_mismatch': ('ask', 0),
    'side_effect_unknown': ('reconcile', 1),
    'decision_pending': ('wait', 0),
    'permission': ('ask', 0),
    'budget': ('ask', 0),
    'drift': ('ask', 0),
    'artifact': ('ask', 0),
    'runtime_bug': ('ask', 0),
    'unknown': ('ask', 0),
}

def signature(node_id, cls, key):
    return content_hash({'node':node_id,'class':cls,'key':key})[:24]


def progress(d, runtime_tree=None):
    passed=sorted(n for n,r in (d.get('nodes') or {}).items() if r.get('phase')=='passed')
    tools=(d.get('preflight') or {}).get('tools')
    return content_hash({'source':(d.get('source') or {}).get('hash'),'env':content_hash(tools) if tools else None,
                         'runtime':runtime_tree,'passed':passed,'generation':d.get('generation')})[:24]


def runtime_tree():
    try:
        from .interventions import runtime_revision
        return runtime_revision().get('tree')
    except (ImportError,ValueError,OSError,AttributeError):
        return None


def migrate(d):
    for key,value in (('failures',{}),('recoveries',[]),('escalations',[])):d.setdefault(key,value)
    return d


def decide(d, node_id, cls, key, detail, now=None, policy=None):
    """Record the failure and return (action, record). Never resets counters."""
    migrate(d);now=now or utcnow()
    sig=signature(node_id,cls,key);fp=progress(d,runtime_tree())
    rec=d['failures'].setdefault(sig,{'class':cls,'node':node_id,'detail':str(detail)[:500],'count':0,
        'attempts':[],'allowance':0,'first_at':now,'last_at':now,'status':'open'})
    action,limit=POLICY.get(policy or cls,('ask',0))
    if action=='wait' and rec['attempts'] and rec['attempts'][-1]['action']=='wait':
        return action,dict(rec,signature=sig,progress=fp)  # Still waiting on the same answer: no new history.
    rec['count']+=1;rec['last_at']=now;rec['detail']=str(detail)[:500]
    # Waiting for a live attempt to settle is not a recovery attempt; it never spends the allowance.
    automatic=[a for a in rec['attempts'] if a['action'] not in ('ask','wait','wait_settle')]
    if action=='wait':pass
    elif action!='ask' and len(automatic)>=limit+rec['allowance']:action='ask'
    # Same failure on the same material state means the last recovery made no progress.
    elif action in ('repair','replay','reconcile') and any(a['progress']==fp for a in automatic):action='ask'
    rec['attempts'].append({'at':now,'action':action,'progress':fp})
    rec['status']='escalated' if action=='ask' else 'waiting' if action=='wait' else 'recovering'
    return action,dict(rec,signature=sig,progress=fp)
