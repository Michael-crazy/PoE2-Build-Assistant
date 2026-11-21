#!/usr/bin/env python3
"""Validate explicit candidate choices against a freshly rebuilt offline snapshot."""
from copy import deepcopy

from guide_contract import keys, snapshot_sha256, text, validate_guide


def _integer(value, path):
    if type(value) is not int or value < 0:
        raise ValueError(f'{path}: expected non-negative integer ID')


def validate_confirmation(guide, confirmation, **lookups):
    """Rebuild candidates locally; never trust caller-supplied candidate records.

    A selection can be partial. Null means unselected, while [] explicitly
    selects no nodes. This records choices only, without rewriting guide facts.
    """
    keys(confirmation, ('schema_version', 'context', 'selection'), 'confirmation')
    if type(confirmation['schema_version']) is not int or confirmation['schema_version'] != 1:
        raise ValueError('confirmation.schema_version: expected 1')
    result = validate_guide(guide, **lookups)
    context = result['confirmation_context']
    if snapshot_sha256(confirmation['context']) != snapshot_sha256(context):
        raise ValueError('confirmation.context: stale or mismatched candidate snapshot; query again')
    if (result['class_ascendancy_candidates']['status'] != 'ready'
            or result['passive_node_candidates']['status'] in
            ('missing_tree_version', 'unknown_tree_version')):
        raise ValueError('confirmation: an explicit indexed tree_version is required')
    sources = context['sources'].values()
    if len({(s['repository'], s['branch'], s['commit']) for s in sources}) != 1:
        raise ValueError('confirmation: candidate sources must use the same repository, branch and SHA')

    selection = confirmation['selection']
    keys(selection, ('main_skill_id', 'class_integer_id', 'ascendancy', 'passive_node_ids'),
         'confirmation.selection')
    skill, owner, asc, nodes = (selection[k] for k in
                               ('main_skill_id', 'class_integer_id', 'ascendancy', 'passive_node_ids'))
    if all(value is None for value in (skill, owner, asc, nodes)):
        raise ValueError('confirmation.selection: select at least one candidate or explicit empty nodes')
    if skill is not None:
        text(skill, 'selection.main_skill_id')
        queries = result['main_skill_candidates']
        ids = {row['id'] for by in ('name', 'id') if queries[by]
               for row in queries[by]['candidates']}
        if skill not in ids:
            raise ValueError('selection.main_skill_id: not in original candidates')
    classes = result['class_ascendancy_candidates']
    if owner is not None:
        _integer(owner, 'selection.class_integer_id')
        query = classes['class_name']
        if query is None or owner not in {r['class_identity']['integer_id'] for r in query['candidates']}:
            raise ValueError('selection.class_integer_id: not in original candidates')
    if asc is not None:
        keys(asc, ('class_integer_id', 'id'), 'selection.ascendancy')
        _integer(asc['class_integer_id'], 'selection.ascendancy.class_integer_id')
        text(asc['id'], 'selection.ascendancy.id')
        if owner is None or asc['class_integer_id'] != owner:
            raise ValueError('selection.ascendancy: requires matching selected class_integer_id')
        query = classes['ascendancy_name']
        if query is None or (owner, asc['id']) not in {
                (r['class_identity']['integer_id'], r['ascendancy']['id']) for r in query['candidates']}:
            raise ValueError('selection.ascendancy: not in original candidates for selected class')
    if nodes is not None:
        if (not isinstance(nodes, list)
                or any(type(n) is not int or n < 0 for n in nodes)
                or len(set(nodes)) != len(nodes)):
            raise ValueError('selection.passive_node_ids: expected unique non-negative integer IDs')
        queries = result['passive_node_candidates']['nodes']
        if queries is None:
            raise ValueError('selection.passive_node_ids: no original node candidates')
        ids = {row['id'] for query in queries for row in query['candidates']}
        if not set(nodes) <= ids:
            raise ValueError('selection.passive_node_ids: not in original candidates')
    result['candidate_selection'] = dict(status='validated', input=deepcopy(confirmation))
    return result
