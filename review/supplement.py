from dataclasses import dataclass

from receive.verify import VerifiedSupplement


@dataclass(frozen=True)
class SupplementRow:
    position: int
    trial: str
    reference: dict | None


def _station_entry(citation: dict) -> dict:
    return {
        'source': 'station',
        'reference': citation['reference'],
        'position': citation['position'],
        'batch': citation['batch'],
        'origin': dict(citation['origin']),
    }


def _arrival_entry(gate: str, name: str, document: str, line: int) -> dict:
    return {
        'source': 'arrival',
        'reference': name,
        'gate': gate,
        'origin': {'document': document, 'line': line},
    }


def review_supplement(package: VerifiedSupplement, arrivals: tuple[tuple[str, str, str, int], ...]):
    """Replay one supplement audit from an empty queue.

    Station events follow the frozen schedule; approved arrivals join the
    queue at their declared gates. Each selected trial takes the earliest
    unused same-class reference and later arrivals never change earlier rows.
    """
    gate_order = [gate['gate'] for gate in package.gates]
    arrivals_by_gate: dict[str, list[tuple[str, str, str, int]]] = {gate: [] for gate in gate_order}
    for arrival in arrivals:
        arrivals_by_gate[arrival[0]].append(arrival)

    station = {citation['position']: citation for citation in package.references}
    queue: list[dict] = []
    rows = []
    for step in package.schedule:
        kind = step['step']
        if kind == 'demand':
            for _ in range(step['count']):
                if queue:
                    queue.pop(0)
        elif kind == 'arrival':
            queue.append(_station_entry(station[step['position']]))
        elif kind == 'gate':
            for _, name, document, line in arrivals_by_gate[step['gate']]:
                queue.append(_arrival_entry(step['gate'], name, document, line))
        else:
            entry = queue.pop(0) if queue else None
            rows.append(SupplementRow(step['position'], _trial_name(package, step['position']), entry))
    return tuple(rows)


def _trial_name(package: VerifiedSupplement, position: int) -> str:
    for trial in package.selected:
        if trial['position'] == position:
            return trial['trial']
    raise ValueError('schedule use is not a selected trial')
