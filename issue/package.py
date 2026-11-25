import hashlib
import hmac
import json


V1_VERSION = 1
V2_VERSION = 2
SUPPORTED_VERSIONS = (V1_VERSION, V2_VERSION)
_FIELDS = {'version', 'issuer', 'dispatch_id', 'revision', 'body'}


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode('ascii')


def package_checksum(payload: dict) -> str:
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def encode_package(issuer: str, dispatch_id: str, revision: str, body: dict) -> bytes:
    return encode_envelope(issuer, dispatch_id, revision, body, V1_VERSION)


def encode_envelope(issuer: str, dispatch_id: str, revision: str, body: dict, version: int) -> bytes:
    if version not in SUPPORTED_VERSIONS:
        raise ValueError('unsupported package version')
    payload = {
        'version': version,
        'issuer': issuer,
        'dispatch_id': dispatch_id,
        'revision': revision,
        'body': body,
    }
    return _canonical_json({**payload, 'checksum': package_checksum(payload)})


def _unique_fields(entries: list[tuple[str, object]]) -> dict:
    fields = {}
    for name, value in entries:
        if name in fields:
            raise ValueError(f'duplicate JSON field: {name}')
        fields[name] = value
    return fields


def _reject_constant(value: str):
    raise ValueError(f'invalid JSON constant: {value}')


def valid_identifier(value: object) -> bool:
    return isinstance(value, str) and bool(value) and value == value.strip() and value.isprintable()


def decode_envelope(wire: bytes) -> dict:
    if not isinstance(wire, bytes):
        raise ValueError('a fixed package must be bytes')
    try:
        envelope = json.loads(wire.decode('utf-8'), object_pairs_hook=_unique_fields, parse_constant=_reject_constant)
        if type(envelope) is not dict or envelope.keys() != _FIELDS | {'checksum'}:
            raise ValueError('invalid package envelope fields')
        version = envelope['version']
        if type(version) is not int or version not in SUPPORTED_VERSIONS:
            raise ValueError('unsupported package envelope version')
        for name in ('issuer', 'dispatch_id', 'revision'):
            if not valid_identifier(envelope[name]):
                raise ValueError(f'invalid package {name}')
        checksum = envelope['checksum']
        if not isinstance(checksum, str) or len(checksum) != 64 or not checksum.isascii():
            raise ValueError('invalid package checksum')
        payload = {name: envelope[name] for name in _FIELDS}
        if not hmac.compare_digest(checksum, package_checksum(payload)):
            raise ValueError('package checksum mismatch')
        if wire != _canonical_json(envelope):
            raise ValueError('package encoding is not the canonical fixed envelope')
    except (UnicodeError, RecursionError) as error:
        raise ValueError('invalid package encoding') from error
    return envelope
