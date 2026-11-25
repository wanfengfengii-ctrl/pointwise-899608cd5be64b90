from assign.eligibility import is_compatible
from assign.provenance import AssignmentRow, reference_citation
from record.events import ReferenceArrival, TrialUse
from record.revisions import FrozenRevision


def build_evidence(
    snapshot: FrozenRevision,
    selected: tuple[TrialUse, ...],
    ledger: tuple[AssignmentRow, ...],
) -> dict:
    selected_positions = {trial.position for trial in selected}
    originals = []
    for row in ledger:
        if row.position not in selected_positions:
            continue
        reference = None if row.reference is None else reference_citation(row.reference)
        originals.append({'position': row.position, 'trial': row.trial, 'reference': reference})

    arrived: list[ReferenceArrival] = []
    uses = []
    for event in snapshot.events:
        if isinstance(event, ReferenceArrival):
            arrived.append(event)
        else:
            uses.append({
                'position': event.position,
                'batch': event.batch,
                'eligible': [reference.position for reference in arrived if is_compatible(event, reference)],
            })
    return {
        'kind': 'replay',
        'batches': list(snapshot.batches),
        'selected': [
            {'position': event.position, 'batch': event.batch, 'trial': event.trial} for event in selected
        ],
        'original': originals,
        'references': [reference_citation(reference) for reference in arrived],
        'uses': uses,
    }
