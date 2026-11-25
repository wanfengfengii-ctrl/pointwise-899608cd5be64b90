from dataclasses import asdict

from review.replay import ReviewRow
from review.store import ReportStore, SignedReport


def publish_report(
    store: ReportStore,
    request_id: str,
    receipt_id: str,
    excluded: frozenset[str],
    rows: tuple[ReviewRow, ...],
) -> SignedReport:
    return store.save_signed_report(
        request_id, receipt_id, tuple(sorted(excluded)), tuple(asdict(row) for row in rows),
    )
