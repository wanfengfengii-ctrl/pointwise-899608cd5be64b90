from collections.abc import Iterable

from assign.ledger import online_ledger
from issue.archive import DispatchArchive
from issue.evidence import build_evidence
from issue.package import encode_package
from issue.scope import select_trials
from record.revisions import read_frozen_revision
from record.store import RecordingStore


def issue_package(
    store: RecordingStore, archive: DispatchArchive, revision: str, trials: Iterable[str],
) -> bytes:
    snapshot = read_frozen_revision(store, revision)
    selected = select_trials(snapshot, trials)
    ledger = online_ledger(store, revision)
    body = build_evidence(snapshot, selected, ledger)
    selection = tuple(trial.trial for trial in selected)
    dispatch = archive.save_dispatch(
        revision,
        selection,
        lambda dispatch_id: encode_package(archive.issuer, dispatch_id, revision, body),
    )
    return dispatch.wire


def reissue_package(archive: DispatchArchive, dispatch_id: str) -> bytes:
    return archive.load_dispatch(dispatch_id).wire
