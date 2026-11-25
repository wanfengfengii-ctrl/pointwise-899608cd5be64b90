from review.store import ReportStore, SignedReport


def get_report(store: ReportStore, report_id: str) -> SignedReport:
    return store.load_signed_report(report_id)
