"""Job intake. The shared part (the task row and its events) is task_intake.submit (core, also used by v2); what is below is the v1-only
part: work contracts, native-change / QC / Android recipes, delivery children and solution binding."""
import re

from .ledger import LedgerError
from .task_intake import Audit, submit as core_submit


class V1(Audit):
    """The v1 steps of intake, called by task_intake.submit at the points the former single function ran them."""

    @staticmethod
    def work_contract(ledger, goal, contract, branch, remote, image, android_build, native_change):
        from .work_contract import validate as validate_contract
        if contract is None: raise LedgerError('Work mode needs a work contract (--contract).')
        if branch or remote or image or android_build or native_change:
            raise LedgerError('Work mode takes its authority from the contract only.')
        contract = validate_contract(contract, ledger.project)
        if goal not in (None, '', contract['goal']): raise LedgerError('--goal differs from the contract goal; give one goal.')
        return contract['goal'], contract

    @staticmethod
    def admit(mode, provider, model, image, branch, remote, android_build, native_change, qc, contract):
        if image is not None and not re.fullmatch(r'sha256:[a-f0-9]{64}',image):
            raise LedgerError('Image must be a locally installed immutable sha256 image ID.')
        if native_change is not None:
            from .native_change import validate
            native_change=validate(native_change)
            if mode!='change' or provider!='claude' or branch or remote or image:
                raise LedgerError('Native change requires Claude change mode without publication/container options.')
        if qc is not None:
            if not native_change: raise LedgerError('QC judges a candidate through a native change recipe.')
            from .qc_gate import validate as validate_qc
            qc=validate_qc(qc,provider,model)
        if mode == 'change' and not image and not native_change:
            raise LedgerError('Change jobs require an authorized sandbox image.')
        if mode in ('delivery','branch') or branch or remote:
            if mode=='audit': raise LedgerError('Audit jobs cannot publish Git changes.')
            if not branch or not re.fullmatch(r'onecrew/[A-Za-z0-9][A-Za-z0-9._/-]{0,100}', branch) or '..' in branch:
                raise LedgerError('Delivery needs an explicit new onecrew/... branch.')
            if mode=='branch' and remote: raise LedgerError('Historical branch mode is local only.')
            if mode!='branch' and (not remote or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,60}',remote)):
                raise LedgerError('Delivery needs an explicit existing Git remote name.')
        from .owned_recipes import validate
        android_build = validate(android_build)
        if android_build and mode != 'branch': raise LedgerError('Historical Android recipe requires branch mode.')
        permissions = ['discover','report'] + (['candidate.write','sandbox.test'] if mode == 'change' else [])
        if android_build: permissions += ['android.build']
        if native_change: permissions += ['native.test','workspace.apply']
        if native_change and native_change.get('apk_build'): permissions += ['android.build']
        if branch and remote:
            permissions += ['git.branch','git.commit','git.push']
        elif mode=='branch': permissions += ['git.branch']
        if mode=='work':
            from .work_contract import permissions as contract_permissions
            permissions = contract_permissions(contract)
        return native_change, qc, android_build, permissions

    @staticmethod
    def recommend(ledger, goal, mode, provider, model):
        from .budget_policy import recommend
        return recommend(ledger, goal, mode, provider, model)

    @staticmethod
    def child_budget(ledger, conn, parent, node, generation, goal, native_change, solution_id, solution_revision):
        from .delivery_store import child_authority
        return child_authority(ledger,conn,parent,node,generation,goal,native_change,solution_id,solution_revision)

    @staticmethod
    def solution_binding(ledger, conn, mode, solution_id, solution_revision, delivery_parent):
        if mode in ('audit','work') and not solution_id: return None
        from .conversations import ensure, approved
        ensure(conn)
        if not solution_id or not solution_revision:raise LedgerError('Review/approve a solution first; pass solution_id and solution_revision for implementation.')
        from .v2 import solution_link
        linked = solution_link.intake_binding(ledger, conn, solution_id, solution_revision)
        if linked is not None:
            root, sol = linked
            return sol, {'id': 'root:' + root['root_task_id'] + ':' + root['sha']}
        sol,decision=approved(ledger,conn,solution_id,solution_revision)
        # One feature contract has one live writer. Parallel implementation uses
        # the existing sealed DAG with explicit ownership/integration checks.
        if mode!='audit':
            peers=conn.execute('SELECT b.task_id FROM solution_bindings b JOIN tasks t ON t.id=b.task_id WHERE b.solution=? AND json_extract(t.payload,\'$.owned_execution.mode\')!=\'audit\'',(solution_id,)).fetchall()
            for peer in peers:
                if peer['task_id']==delivery_parent: continue
                if conn.execute("SELECT 1 FROM events WHERE task_id=? AND kind='solution.stopped'",(peer['task_id'],)).fetchone():continue
                checkpoint=conn.execute("SELECT json_extract(payload,'$.phase') FROM events WHERE task_id=? AND kind='workflow.checkpoint' ORDER BY seq DESC LIMIT 1",(peer['task_id'],)).fetchone()
                if not checkpoint or checkpoint[0] not in ('completed','failed','cancelled'):
                    raise LedgerError('This solution already has a live task; continue it instead of creating parallel writers.')
        return sol,decision

    @staticmethod
    def bind(conn, task_id, binding, solution_id, solution_revision):
        sol,decision=binding
        conn.execute('INSERT INTO solution_bindings VALUES(?,?,?,?,?)',(task_id,sol['conversation'],solution_id,solution_revision,decision['id']))

    @staticmethod
    def link_child(conn, task_id, parent, node, generation):
        conn.execute('INSERT INTO delivery_children VALUES(?,?,?,?)',(task_id,parent,node,generation))


def submit(ledger, goal, request_key, **options):
    return core_submit(ledger, goal, request_key, extension=V1, **options)
