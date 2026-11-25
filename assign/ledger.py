from assign.provenance import AssignmentRow
from assign.replay import replay_assignments
from record.revisions import read_frozen_revision
from record.store import RecordingStore


def online_ledger(store: RecordingStore, revision: str) -> tuple[AssignmentRow, ...]:
    snapshot = read_frozen_revision(store, revision)
    return replay_assignments(snapshot.events)
