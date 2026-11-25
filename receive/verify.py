from dataclasses import dataclass

from issue.package import decode_envelope, valid_identifier


@dataclass(frozen=True)
class VerifiedPackage:
    issuer: str
    dispatch_id: str
    revision: str
    checksum: str
    wire: bytes
    kind: str
    batches: tuple[str, ...]
    selected: tuple[dict, ...]
    original: tuple[dict, ...]
    references: tuple[dict, ...]
    uses: tuple[dict, ...]


def _object(value: object, keys: set[str], label: str) -> dict:
    if type(value) is not dict or value.keys() != keys:
        raise ValueError(f'invalid {label} fields')
    return value


def _array(value: object, label: str) -> list:
    if type(value) is not list:
        raise ValueError(f'{label} must be an array')
    return value


def _ordered_records(value: object, keys: set[str], label: str) -> list[dict]:
    records = _array(value, label)
    previous = None
    for item in records:
        _object(item, keys, label)
        position = item['position']
        if type(position) is not int or (previous is not None and position <= previous):
            raise ValueError(f'{label} positions must strictly increase')
        previous = position
    return records


def _validate_citation(citation: dict, batches: set[str]) -> None:
    _object(citation, {'position', 'batch', 'reference', 'origin'}, 'reference citation')
    if type(citation['position']) is not int or not valid_identifier(citation['reference']):
        raise ValueError('invalid reference position or name')
    batch = citation['batch']
    if not valid_identifier(batch) or batch not in batches:
        raise ValueError('reference batch is undeclared')
    origin = _object(citation['origin'], {'batch', 'document', 'line'}, 'reference origin')
    if origin['batch'] != batch or not valid_identifier(origin['document']):
        raise ValueError('reference origin does not identify a document in its batch')
    if type(origin['line']) is not int or origin['line'] < 1:
        raise ValueError('invalid reference origin line')


def _validate_selection(value: object, batches: set[str]) -> list[dict]:
    selected = _ordered_records(value, {'position', 'batch', 'trial'}, 'selected trial')
    seen = set()
    for trial in selected:
        if not valid_identifier(trial['batch']) or trial['batch'] not in batches:
            raise ValueError('selected trial batch is undeclared')
        if not valid_identifier(trial['trial']) or trial['trial'] in seen:
            raise ValueError('invalid or repeated selected trial name')
        seen.add(trial['trial'])
    return selected


def _validate_original(value: object, selected: list[dict], batches: set[str]) -> list[dict]:
    rows = _ordered_records(value, {'position', 'trial', 'reference'}, 'original allocation')
    if len(rows) != len(selected):
        raise ValueError('original allocation does not cover the selection')
    used_positions, used_names = set(), set()
    selected_positions = {trial['position'] for trial in selected}
    for row, trial in zip(rows, selected):
        if row['position'] != trial['position'] or row['trial'] != trial['trial']:
            raise ValueError('original allocation does not match selected trial')
        citation = row['reference']
        if citation is None:
            continue
        _validate_citation(citation, batches)
        position = citation['position']
        name = citation['reference']
        if position >= trial['position'] or position in selected_positions or position in used_positions:
            raise ValueError('invalid or repeated original reference position')
        if name in used_names:
            raise ValueError('repeated original reference instance')
        used_positions.add(position)
        used_names.add(name)
    return rows


def _validate_replay(body: dict, batches: set[str], selected: list[dict], original: list[dict]):
    references = _ordered_records(body['references'], {'position', 'batch', 'reference', 'origin'}, 'arrival')
    arrivals = {row['position']: row for row in references}
    seen_names = set()
    for citation in references:
        _validate_citation(citation, batches)
        if citation['reference'] in seen_names:
            raise ValueError('repeated reference instance name')
        seen_names.add(citation['reference'])

    uses = _ordered_records(body['uses'], {'position', 'batch', 'eligible'}, 'trial use')
    uses_by_position = {row['position']: row for row in uses}
    for use in uses:
        position = use['position']
        if position in arrivals or not valid_identifier(use['batch']) or use['batch'] not in batches:
            raise ValueError('trial use position or batch is invalid')
        previous = None
        for candidate in _array(use['eligible'], 'eligible references'):
            if type(candidate) is not int or candidate >= position or candidate not in arrivals:
                raise ValueError('trial eligibility must address an earlier known reference')
            if previous is not None and candidate <= previous:
                raise ValueError('eligible reference positions must strictly increase')
            previous = candidate

    for chosen, row in zip(selected, original):
        use = uses_by_position.get(chosen['position'])
        if use is None or use['batch'] != chosen['batch']:
            raise ValueError('selected trial has no corresponding use')
        citation = row['reference']
        if citation is not None:
            position = citation['position']
            if position not in use['eligible'] or arrivals[position] != citation:
                raise ValueError('original reference does not match a cited candidate')
    return references, uses


def verify_package(wire: bytes) -> VerifiedPackage:
    envelope = decode_envelope(wire)
    body = envelope['body']
    kind = body.get('kind') if type(body) is dict else None
    fields = {'kind', 'batches', 'selected', 'original'}
    if kind == 'replay':
        fields |= {'references', 'uses'}
    elif kind != 'paired':
        raise ValueError('unsupported V1 body kind')
    _object(body, fields, 'package body')
    batches = _array(body['batches'], 'batches')
    if any(not valid_identifier(batch) for batch in batches) or len(set(batches)) != len(batches):
        raise ValueError('invalid or repeated batch name')
    declared = set(batches)
    selected = _validate_selection(body['selected'], declared)
    original = _validate_original(body['original'], selected, declared)
    references, uses = ([], [])
    if kind == 'replay':
        references, uses = _validate_replay(body, declared, selected, original)
    return VerifiedPackage(
        issuer=envelope['issuer'], dispatch_id=envelope['dispatch_id'], revision=envelope['revision'],
        checksum=envelope['checksum'], wire=wire, kind=kind, batches=tuple(batches),
        selected=tuple(selected), original=tuple(original), references=tuple(references), uses=tuple(uses),
    )
