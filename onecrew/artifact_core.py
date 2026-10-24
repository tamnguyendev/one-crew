"""Shared v1 typed artifact validation; tool-free workers return owned bytes."""
from copy import deepcopy

from .ledger import LedgerError, exact_fields, text_field


ARTIFACT_SCHEMA = {'type': 'object', 'additionalProperties': False,
                  'required': ['summary', 'files', 'backlog'], 'properties': {
                      'summary': {'type': 'string'}, 'backlog': {'type': 'array', 'items': {'type': 'string'}},
                      'files': {'type': 'array', 'items': {'type': 'object', 'additionalProperties': False,
                                  'required': ['path', 'content'], 'properties': {
                                      'path': {'type': 'string'}, 'content': {'type': ['string', 'null']}}}}}}


CONTINUATION_SCHEMA = {'type': 'object', 'additionalProperties': False, 'required': ['remaining'],
                       'properties': {'remaining': {'type': 'string', 'minLength': 1}}}


def artifact_schema(owned):
    schema = deepcopy(ARTIFACT_SCHEMA)
    files = schema['properties']['files']
    files['items']['properties']['path']['enum'] = list(owned)
    # W36 (T07b E16): a worker that stops at a safe point with work left says so; the files are a PARTIAL candidate then
    schema['properties']['continuation'] = deepcopy(CONTINUATION_SCHEMA)
    return schema


def continuation_of(value):
    """The worker's declared remaining work (None when the result is complete) and the value without it, for `artifacts`."""
    if not isinstance(value, dict) or 'continuation' not in value:
        return None, value
    continuation = value['continuation']
    if (not isinstance(continuation, dict) or set(continuation) != {'remaining'} or not isinstance(continuation['remaining'], str)
            or not continuation['remaining'].strip()):
        raise LedgerError('continuation.remaining: what is left to do, as non-empty text; omit continuation when the work is complete.')
    return {'remaining': text_field(continuation['remaining'], 'continuation.remaining', 2000)}, {k: v for k, v in value.items() if k != 'continuation'}


def artifacts(value, owned):
    exact_fields(value, ('summary', 'files', 'backlog'), 'Artifacts')
    text_field(value['summary'], 'output summary')
    if not isinstance(value['backlog'], list) or len(value['backlog']) > 10:
        raise LedgerError('Invalid backlog.')
    for item in value['backlog']:
        text_field(item, 'backlog item')
    if not isinstance(value['files'], list) or not 1 <= len(value['files']) <= len(owned):
        raise LedgerError('Invalid artifact file list.')
    result = {}
    for item in value['files']:
        exact_fields(item, ('path', 'content'), 'Artifact file')
        name, content = item['path'], item['content']
        if name not in owned or name in result or (content is not None and not isinstance(content, str)):
            raise LedgerError('Artifact scope, type or duplicate path violation.')
        result[name] = content.encode('utf-8') if content is not None else None
    return result
