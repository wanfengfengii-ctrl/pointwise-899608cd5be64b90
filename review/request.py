from collections.abc import Collection
from dataclasses import dataclass

from issue.package import valid_identifier
from receive.lookup import load_verified_receipt
from receive.store import ReceiptStore
from review.publish import publish_report
from review.replay import review_allocations
from review.store import ReportStore, SignedReport


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
    unknown = excluded.difference(package.batches)
    if unknown:
        raise ValueError(f'batches are undeclared for receipt {request.receipt_id}: {sorted(unknown)}')
    rows = review_allocations(package, excluded)
    return publish_report(reports, request.request_id, request.receipt_id, excluded, rows)
