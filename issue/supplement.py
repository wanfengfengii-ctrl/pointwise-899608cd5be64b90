from collections.abc import Iterable

from assign.provenance import reference_citation
from issue.package import valid_identifier
from record.events import ReferenceArrival, TrialUse
from record.revisions import FrozenRevision


def validate_gates(gates: Iterable) -> tuple[tuple[str, int], ...]:
    if isinstance(gates, (str, bytes)) or not isinstance(gates, Iterable):
        raise ValueError('gates must be a collection of (gate, cutoff) pairs')
    normalized = tuple(gates)
    declared = set()
    previous_cutoff = None
    for pair in normalized:
        if not isinstance(pair, (tuple, list)) or len(pair) != 2:
            raise ValueError('each gate must be a (gate, cutoff) pair')
        gate, cutoff = pair
        if not valid_identifier(gate) or gate in declared:
            raise ValueError('invalid or repeated gate name')
        if type(cutoff) is not int:
            raise ValueError('gate cutoff must be an integer')
        if previous_cutoff is not None and cutoff < previous_cutoff:
            raise ValueError('gate cutoffs must be non-decreasing in frozen position order')
        declared.add(gate)
        previous_cutoff = cutoff
    return normalized


def _demand(steps: list[dict], count: int) -> int:
    steps.append({'step': 'demand', 'count': count})
    return 0


def build_supplement_body(
    snapshot: FrozenRevision,
    selected: tuple[TrialUse, ...],
    compatibility: str,
    gates: tuple[tuple[str, int], ...],
) -> dict:
    """Freeze the whole-segment allocation basis for one compatibility class.

    Only public boundaries (selected trials and gates), the ordered identities
    of same-class station references and per-gap internal demand counts leave
    the station. Internal trial names, batches, per-item consumption and the
    original compatibility key never appear in the body.
    """
    selected_positions = {trial.position for trial in selected}
    class_events = [event for event in snapshot.events if event.compatibility == compatibility]
    references = [event for event in class_events if isinstance(event, ReferenceArrival)]

    steps: list[dict] = []
    pending_demand = 0
    gate_index = 0
    for event in class_events:
        while gate_index < len(gates) and gates[gate_index][1] < event.position:
            pending_demand = _demand(steps, pending_demand)
            gate, cutoff = gates[gate_index]
            steps.append({'step': 'gate', 'gate': gate, 'cutoff': cutoff})
            gate_index += 1
        if isinstance(event, ReferenceArrival):
            pending_demand = _demand(steps, pending_demand)
            steps.append({'step': 'arrival', 'position': event.position})
        elif event.position in selected_positions:
            pending_demand = _demand(steps, pending_demand)
            steps.append({'step': 'use', 'position': event.position})
        else:
            pending_demand += 1
    while gate_index < len(gates):
        pending_demand = _demand(steps, pending_demand)
        gate, cutoff = gates[gate_index]
        steps.append({'step': 'gate', 'gate': gate, 'cutoff': cutoff})
        gate_index += 1
    _demand(steps, pending_demand)

    public_batches = sorted({
        *(event.batch for event in references),
        *(event.batch for event in selected),
    })
    return {
        'kind': 'supplement',
        'batches': public_batches,
        'selected': [
            {'position': event.position, 'batch': event.batch, 'trial': event.trial}
            for event in selected
        ],
        'gates': [{'gate': gate, 'cutoff': cutoff} for gate, cutoff in gates],
        'references': [reference_citation(event) for event in references],
        'schedule': steps,
    }
