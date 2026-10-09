"""Discussion-only routing. No execution preference, inference or approval by default."""
from .ledger import LedgerError
from .conversations import clean

DEFAULTS={'claude':'sonnet','codex':'gpt-6-luna'}


def route(entry, intent='local', provider=None, model=None, reference=None, policy=None, brief=None, jev=False):
    clean(entry,'entry',100)
    if type(jev) is not bool:raise LedgerError('jev must be a boolean opt-in.')
    if intent not in ('local','consult','auto'):raise LedgerError('Unknown discussion intent.')
    if intent=='local':
        if provider or model or jev:raise LedgerError('A mention is not consultation authority; supply explicit consult intent.')
        return dict(status='local',entry=entry,selection_source='current-entry',dispatch=False,actual_model=None)
    clean(reference,'actual user request reference',1000)
    if provider:
        if provider not in ('claude','codex','kiro'):raise LedgerError('Unsupported consultation provider.')
        requested=model
        model=model or DEFAULTS.get(provider)
        if not model:raise LedgerError('Configure an explicit consultation model for this provider.')
        clean(model,'model',100)
        return dict(status='selected',entry=entry,selection_source='explicit',provider=provider,model=model,
                    provider_requested=provider,model_requested=requested,dispatch=True,jev={'status':'skipped','calls':0})
    if intent!='auto' or not policy:raise LedgerError('Consultation requires an explicit provider or auto policy.')
    from .routing import choose
    result=choose(policy['workload'],policy['candidates'])
    evaluator={'status':'disabled','calls':0}
    if jev:
        from .model_advisor import advise
        from .jev import JevError
        try:evaluator=advise(brief,policy['workload'],policy['candidates'],result)
        except JevError:evaluator={'status':'unavailable','calls':1,'automatic_application':False,'cost':None}
    return dict(status='selected' if result['status']=='recommended' else 'needs_decision',entry=entry,
        selection_source='rule',dispatch=result['status']=='recommended',provider_requested=None,model_requested=None,
        **({k:result['selected'][k] for k in ('provider','model')} if result.get('selected') else {}),
        rule=result,jev=evaluator,policy=policy)
