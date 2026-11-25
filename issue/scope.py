from collections.abc import Iterable

from record.events import TrialUse
from record.origins import valid_name
from record.revisions import FrozenRevision


def select_trials(snapshot: FrozenRevision, trials: Iterable[str]) -> tuple[TrialUse, ...]:
    if isinstance(trials, (str, bytes)):
        raise ValueError('selection must be a collection of trial names')
    wanted = tuple(trials)
    if any(not valid_name(trial) for trial in wanted):
        raise ValueError('invalid selected trial name')
    names = set(wanted)
    selected = tuple(
        event for event in snapshot.events if isinstance(event, TrialUse) and event.trial in names
    )
    missing = names.difference(event.trial for event in selected)
    if missing:
        raise ValueError(f'trials outside frozen revision {snapshot.revision}: {sorted(missing)}')
    return selected
