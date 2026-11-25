from dataclasses import dataclass

from record.events import Event
from record.store import RecordingStore


@dataclass(frozen=True)
class FrozenRevision:
    revision: str
    working_revision: str
    batches: tuple[str, ...]
    events: tuple[Event, ...]


def freeze(store: RecordingStore, working_revision: str) -> str:
    with store.transaction():
        current = store.load_working_revision(working_revision)
        revision = store.save_frozen_revision(current)
    return revision


def read_frozen_revision(store: RecordingStore, revision: str) -> FrozenRevision:
    snapshot = store.load_frozen_revision(revision)
    return FrozenRevision(revision, snapshot.working_revision, snapshot.batches, snapshot.events)
