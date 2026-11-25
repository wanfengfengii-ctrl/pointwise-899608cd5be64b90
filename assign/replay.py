from collections.abc import Iterable

from assign.availability import AvailableReferences
from assign.eligibility import is_compatible
from assign.provenance import AssignmentRow, make_assignment_row
from record.events import Event, ReferenceArrival, order_events


def replay_assignments(events: Iterable[Event]) -> tuple[AssignmentRow, ...]:
    available = AvailableReferences[ReferenceArrival]()
    rows = []
    for event in order_events(events):
        if isinstance(event, ReferenceArrival):
            available.admit(event)
            continue
        reference = available.take_earliest(lambda instance: is_compatible(event, instance))
        rows.append(make_assignment_row(event, reference))
    return tuple(rows)
