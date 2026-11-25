from collections.abc import Iterable

from assign.ledger import online_ledger
from issue.archive import DispatchArchive
from issue.evidence import build_evidence
from issue.package import V2_VERSION, encode_envelope, encode_package
from issue.scope import select_trials
from issue.supplement import build_supplement_body, validate_gates
from record.events import TrialUse
from record.origins import valid_name
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


def issue_supplement(
    store: RecordingStore,
    archive: DispatchArchive,
    revision: str,
    trials: Iterable[str],
    compatibility: str,
    gates: Iterable,
) -> bytes:
    snapshot = read_frozen_revision(store, revision)
    if not valid_name(compatibility):
        raise ValueError('supplement compatibility class requires a valid key')
    ordered_gates = validate_gates(gates)
    selected = select_trials(snapshot, trials)
    outside = tuple(sorted({
        trial.trial for trial in selected
        if not isinstance(trial, TrialUse) or trial.compatibility != compatibility
    }))
    if outside:
        raise ValueError(f'selected trials outside the compatibility class: {outside}')
    body = build_supplement_body(snapshot, selected, compatibility, ordered_gates)
    selection = tuple(trial.trial for trial in selected)
    dispatch = archive.save_dispatch(
        revision,
        selection,
        lambda dispatch_id: encode_envelope(
            archive.issuer, dispatch_id, revision, body, V2_VERSION,
        ),
    )
    return dispatch.wire


def reissue_package(archive: DispatchArchive, dispatch_id: str) -> bytes:
    return archive.load_dispatch(dispatch_id).wire
