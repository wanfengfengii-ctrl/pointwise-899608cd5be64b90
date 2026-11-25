from collections.abc import Collection
from dataclasses import asdict, dataclass

from issue.package import valid_identifier
from receive.lookup import load_verified_receipt
from receive.store import ReceiptStore
from receive.verify import VerifiedSupplement
from review.publish import publish_report
from review.replay import review_allocations
from review.store import ReportStore, SignedReport, SupplementReport
from review.supplement import review_supplement


@dataclass(frozen=True)
class AuditRequest:
    receipt_id: str
    request_id: str
    excluded_batches: Collection[str] = ()


def audit_package(receipts: ReceiptStore, reports: ReportStore, request: AuditRequest) -> SignedReport:
    if not valid_identifier(request.receipt_id) or not valid_identifier(request.request_id):
        raise ValueError('receipt and report request require valid identifiers')
    values = request.excluded_batches
    if isinstance(values, (str, bytes)) or not isinstance(values, Collection):
        raise ValueError('excluded batches must be a collection of batch names')
    batches = tuple(values)
    if any(not valid_identifier(batch) for batch in batches):
        raise ValueError('invalid excluded batch name')
    excluded = frozenset(batches)
    package = load_verified_receipt(receipts, request.receipt_id)
    if isinstance(package, VerifiedSupplement):
        raise ValueError('V2 supplement packages use the supplement audit entry')
    unknown = excluded.difference(package.batches)
    if unknown:
        raise ValueError(f'batches are undeclared for receipt {request.receipt_id}: {sorted(unknown)}')
    rows = review_allocations(package, excluded)
    return publish_report(reports, request.request_id, request.receipt_id, excluded, rows)


def _normalize_arrivals(arrivals) -> tuple[tuple[str, str, str, int], ...]:
    if isinstance(arrivals, (str, bytes)) or not isinstance(arrivals, Collection):
        raise ValueError('arrivals must be an ordered collection of (gate, reference, document, line) tuples')
    normalized = []
    seen_names = set()
    for entry in arrivals:
        if not isinstance(entry, (tuple, list)) or len(entry) != 4:
            raise ValueError('each arrival must be a (gate, reference, document, line) tuple')
        gate, name, document, line = entry
        if not valid_identifier(gate) or not valid_identifier(name) or not valid_identifier(document):
            raise ValueError('arrival gate, reference and document require valid identifiers')
        if type(line) is not int or line < 1:
            raise ValueError('arrival origin line must be a positive integer')
        if name in seen_names:
            raise ValueError(f'duplicate arrival reference: {name}')
        seen_names.add(name)
        normalized.append((gate, name, document, line))
    return tuple(normalized)


def audit_supplement(
    receipts: ReceiptStore,
    reports: ReportStore,
    receipt_id: str,
    request_id: str,
    arrivals,
) -> SupplementReport:
    if not valid_identifier(receipt_id) or not valid_identifier(request_id):
        raise ValueError('receipt and report request require valid identifiers')
    ordered = _normalize_arrivals(arrivals)
    package = load_verified_receipt(receipts, receipt_id)
    if not isinstance(package, VerifiedSupplement):
        raise ValueError('the supplement audit entry requires a V2 package')
    declared_gates = {gate['gate'] for gate in package.gates}
    unknown = tuple(sorted({entry[0] for entry in ordered}.difference(declared_gates)))
    if unknown:
        raise ValueError(f'gates are undeclared for receipt {receipt_id}: {unknown}')
    gate_rank = {gate['gate']: index for index, gate in enumerate(package.gates)}
    effective = tuple(sorted(ordered, key=lambda entry: gate_rank[entry[0]]))
    rows = review_supplement(package, effective)
    signed_rows = tuple(asdict(row) for row in rows)
    return reports.save_supplement_report(request_id, receipt_id, effective, signed_rows)
