"""W09: local Git roots for evidence; only an explicit owner cleanup removes them.

Tree refs keep their descendant trees/blobs reachable through ordinary Git GC. They
are scoped to a project, state root and plan, including when worktrees share refs.
This module never pushes, runs GC, expires refs or removes snapshot-store blobs.
"""
import os
from pathlib import Path

from ..ledger import LedgerError, content_hash
from .verifiers import command

PREFIX = 'refs/onecrew/evidence/'


def _prefix(ledger, name):
    from . import namespaces
    bare, explicit = namespaces.parse(name)
    chosen = explicit
    if chosen is None and hasattr(ledger, 'transaction'):
        with ledger.transaction() as conn:
            row = namespaces.resolve(ledger, conn, bare)
        chosen = row['request_key'] if row else None
    # Keep historical legacy pins addressable; new roots with the same bare name
    # receive a distinct scope. Unit adapters without a ledger keep their scope.
    identity = chosen if chosen and chosen.startswith(namespaces.NAMESPACED) else bare
    scope = {'project': os.path.normcase(str(Path(ledger.project).resolve())),
             'state_root': os.path.normcase(str(Path(ledger.state_root).resolve())), 'plan': identity}
    return PREFIX + content_hash(scope) + '/'


def list_refs(ledger, name):
    """Return only this plan's durable refs as {ref: tree}; does not create any."""
    prefix = _prefix(ledger, name)
    output = command._git(ledger.project, 'for-each-ref', '--format=%(refname) %(objectname) %(symref)', prefix)
    result = {}
    for line in output.splitlines():
        fields = line.split()
        if len(fields) != 2:
            raise LedgerError('Symbolic evidence retention ref; owner inspection required.')
        ref, oid = fields
        if (not ref.startswith(prefix) or not command.TREE_ID.fullmatch(oid)
                or ref != prefix + oid):
            raise LedgerError('Unexpected evidence retention ref; owner inspection required.')
        result[ref] = oid
    return result


def pin_trees(ledger, name, *trees):
    """Validate then idempotently root every supplied tree, before publishing evidence.

    Failure may conservatively leave extra pins. It never removes an existing pin,
    including after a later failed ledger transaction or a verifier failure.
    """
    prefix = _prefix(ledger, name)
    if any(not isinstance(tree, str) or not command.TREE_ID.fullmatch(tree) for tree in trees):
        raise LedgerError('Evidence tree id must be 40 or 64 lowercase hex characters.')
    unique = sorted(set(trees))
    # Check the type, not just existence: commit ids would retain unrelated history.
    for tree in unique:
        if command._git(ledger.project, 'cat-file', '-t', tree) != 'tree':
            raise LedgerError('Evidence retention requires a Git tree object.')
    present = list_refs(ledger, name)
    for tree in unique:
        ref = prefix + tree
        if ref in present:
            continue
        try:
            command._git(ledger.project, 'update-ref', '--no-deref', ref, tree, '0' * len(tree))
        except LedgerError:
            # A concurrent publisher may have created precisely this immutable pin.
            if list_refs(ledger, name).get(ref) != tree:
                raise
    return [prefix + tree for tree in unique]


def cleanup(ledger, name, by):
    """Explicit owner-only removal, restricted to this project/state-root/plan.

    The expected old values fence concurrent changes. No other cleanup path calls
    this function, and it neither deletes objects nor invokes pruning.
    """
    from .plan import require_owner
    require_owner(by, 'Evidence retention cleanup')
    retained = list_refs(ledger, name)
    if retained:
        commands = ''.join(f'delete {ref} {tree}\n' for ref, tree in sorted(retained.items()))
        command._git(ledger.project, 'update-ref', '--no-deref', '--stdin', input=commands.encode('ascii'))
    return {'plan': name, 'removed': sorted(retained)}


def pin_evidence(ledger, name, artifact, body=None, strict=False):
    """Pin Git evidence before publishing it; preserve opaque manual artifacts.

    Command/reviewer receipts must name real trees. Their null sentinel means no
    artifact was produced and is handled by the verdict result validation. Manual
    evidence can also name an external document hash, which is not a Git tree.
    """
    body = body or {}
    from .verifiers import artifact as identities
    if not strict and not body and not identities.is_git(ledger.project):
        return []  # legacy owner-manual opaque evidence remains a blob, not a snapshot claim
    if identities.validate_evidence(ledger, artifact, body):
        return []  # v1 snapshot manifest and blobs already reside in durable storage
    trees = [artifact] + [body.get(key) for key in
                         ('artifact_sha_after', 'tracked_tree', 'base_artifact', 'base_tracked')]
    trees = [tree for tree in trees if tree is not None and tree not in ('0' * 40, '0' * 64)]
    if not strict:
        actual = []
        for tree in trees:
            if not isinstance(tree, str) or not command.TREE_ID.fullmatch(tree):
                continue
            try:
                kind = command._git(ledger.project, 'cat-file', '-t', tree)
            except LedgerError:
                continue
            if kind == 'tree':
                actual.append(tree)
        trees = actual
    return pin_trees(ledger, name, *trees) if trees else []
