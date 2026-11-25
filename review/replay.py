from dataclasses import dataclass
from heapq import merge
from operator import itemgetter

from assign.availability import AvailableReferences
from receive.verify import VerifiedPackage


@dataclass(frozen=True)
class ReviewRow:
    position: int
    trial: str
    reference: dict | None


def review_allocations(package: VerifiedPackage, excluded: frozenset[str]) -> tuple[ReviewRow, ...]:
    if package.kind == 'paired':
        if excluded:
            raise ValueError('this historical package has no withdrawal replay evidence')
        return tuple(ReviewRow(**row) for row in package.original)

    arrivals = {reference['position'] for reference in package.references}
    selected = {trial['position']: trial['trial'] for trial in package.selected}
    available = AvailableReferences[dict]()
    rows = []
    ordered = merge(package.references, package.uses, key=itemgetter('position'))
    for event in ordered:
        if event['batch'] in excluded:
            continue
        position = event['position']
        if position in arrivals:
            available.admit(event)
            continue
        candidates = set(event['eligible'])
        reference = available.take_earliest(lambda instance: instance['position'] in candidates)
        if position in selected:
            rows.append(ReviewRow(position, selected[position], reference))
    return tuple(rows)
