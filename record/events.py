from collections.abc import Iterable
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation

from record.origins import ReferenceOrigin, valid_name


@dataclass(frozen=True)
class ReferenceArrival:
    position: int
    batch: str
    reference: str
    compatibility: str
    value: str
    unit: str
    origin: ReferenceOrigin


@dataclass(frozen=True)
class TrialUse:
    position: int
    batch: str
    trial: str
    compatibility: str
    value: str | None = None
    unit: str | None = None


Event = ReferenceArrival | TrialUse


def validate_event_positions(events: Iterable[Event], occupied: Iterable[int] = ()) -> None:
    positions = set(occupied)
    for event in events:
        if not isinstance(event, (ReferenceArrival, TrialUse)):
            raise ValueError('unknown event type')
        position = event.position
        if type(position) is not int or position in positions:
            raise ValueError(f'invalid or occupied event position: {position!r}')
        positions.add(position)


def order_events(events: Iterable[Event]) -> tuple[Event, ...]:
    return tuple(sorted(events, key=lambda event: event.position))


def _validate_measurement(value: object, unit: object) -> None:
    if not valid_name(value) or not valid_name(unit):
        raise ValueError('measurement requires decimal text and a unit')
    try:
        finite = Decimal(value).is_finite()
    except InvalidOperation as error:
        raise ValueError('measurement is not decimal text') from error
    if not finite:
        raise ValueError('measurement must be finite')


def validate_event_fields(event: Event, batch: str) -> None:
    if event.batch != batch or not valid_name(event.compatibility):
        raise ValueError('event batch or compatibility key is invalid')
    if isinstance(event, ReferenceArrival):
        if not valid_name(event.reference):
            raise ValueError('invalid reference instance name')
        _validate_measurement(event.value, event.unit)
    else:
        if not valid_name(event.trial):
            raise ValueError('invalid trial name')
        if event.value is not None or event.unit is not None:
            _validate_measurement(event.value, event.unit)


def event_to_data(event: Event) -> dict:
    data = asdict(event)
    data['kind'] = 'arrival' if isinstance(event, ReferenceArrival) else 'use'
    return data


def event_from_data(data: dict) -> Event:
    fields = dict(data)
    kind = fields.pop('kind')
    if kind == 'arrival':
        fields['origin'] = ReferenceOrigin(**fields['origin'])
        return ReferenceArrival(**fields)
    if kind == 'use':
        return TrialUse(**fields)
    raise ValueError(f'unknown stored event kind: {kind!r}')
