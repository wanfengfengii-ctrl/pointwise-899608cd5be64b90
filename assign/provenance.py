from dataclasses import dataclass

from record.events import ReferenceArrival, TrialUse


@dataclass(frozen=True)
class AssignmentRow:
    position: int
    batch: str
    trial: str
    reference: ReferenceArrival | None


def make_assignment_row(trial: TrialUse, reference: ReferenceArrival | None) -> AssignmentRow:
    return AssignmentRow(trial.position, trial.batch, trial.trial, reference)


def reference_citation(reference: ReferenceArrival) -> dict:
    return {
        'position': reference.position,
        'batch': reference.batch,
        'reference': reference.reference,
        'origin': {
            'batch': reference.origin.batch,
            'document': reference.origin.document,
            'line': reference.origin.line,
        },
    }
