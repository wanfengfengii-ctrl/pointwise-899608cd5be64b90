from dataclasses import dataclass


@dataclass(frozen=True)
class ReferenceOrigin:
    batch: str
    document: str
    line: int


def valid_name(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and value == value.strip()
        and value.isprintable()
    )


def validate_origin(origin: ReferenceOrigin, batch: str) -> None:
    if not isinstance(origin, ReferenceOrigin):
        raise ValueError('a reference requires a source document and line')
    if not valid_name(origin.batch) or origin.batch != batch:
        raise ValueError('reference origin belongs to a different batch')
    if not valid_name(origin.document):
        raise ValueError('reference origin has an invalid document name')
    if type(origin.line) is not int or origin.line < 1:
        raise ValueError('reference origin line must be a positive integer')
