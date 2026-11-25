from collections.abc import Iterable

from record.events import Event, ReferenceArrival, validate_event_fields, validate_event_positions
from record.origins import valid_name, validate_origin
from record.store import RecordingStore, WorkingRevision


def _identity(event: Event) -> tuple[type, str]:
    name = event.reference if isinstance(event, ReferenceArrival) else event.trial
    return type(event), name


def record_batch(store: RecordingStore, working_revision: str, batch: str, events: Iterable[Event]) -> str:
    if not valid_name(working_revision) or not valid_name(batch):
        raise ValueError('working revision and batch require valid names')
    incoming = tuple(events)
    with store.transaction():
        try:
            current = store.load_working_revision(working_revision)
        except KeyError:
            current = WorkingRevision(working_revision, (), ())
        if batch in current.batches:
            raise ValueError(f'batch already recorded: {batch}')
        validate_event_positions(incoming, (event.position for event in current.events))
        identities = {_identity(event) for event in current.events}
        for event in incoming:
            validate_event_fields(event, batch)
            if isinstance(event, ReferenceArrival):
                validate_origin(event.origin, batch)
            identity = _identity(event)
            if identity in identities:
                raise ValueError(f'event identity already recorded: {identity[1]}')
            identities.add(identity)
        store.save_batch(working_revision, batch, incoming)
    return working_revision
