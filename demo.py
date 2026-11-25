import json
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from assign.ledger import online_ledger
from issue.archive import DispatchArchive
from issue.dispatch import issue_package, reissue_package
from issue.package import decode_envelope
from receive.lookup import get_received
from receive.register import accept_package
from receive.store import ReceiptStore
from record.batches import record_batch
from record.events import event_from_data
from record.revisions import freeze
from record.store import RecordingStore
from review.history import get_report
from review.request import AuditRequest, audit_package
from review.store import ReportStore


SAMPLES = Path(__file__).resolve().parent / 'samples'


def sample_batches(path: Path):
    batches = json.loads(path.read_text(encoding='utf-8'))
    return [(batch['batch'], tuple(event_from_data(event) for event in batch['events'])) for batch in batches]


def record_sample(store: RecordingStore, work: str, path: Path) -> None:
    for batch, events in sample_batches(path):
        record_batch(store, work, batch, events)


def report_summary(report) -> list[list]:
    rows = []
    for row in report.rows:
        reference = row['reference']
        if reference is None:
            rows.append([row['trial'], None])
        else:
            origin = reference['origin']
            rows.append([row['trial'], [reference['reference'], origin['batch'], origin['document'], origin['line']]])
    return rows


def main() -> None:
    with TemporaryDirectory(prefix='reference-exchange-') as temporary:
        source_path = Path(temporary) / 'center.sqlite3'
        offline_path = Path(temporary) / 'partner.sqlite3'
        with closing(ReceiptStore(offline_path)) as receipts:
            receipts.initialize()
            with closing(RecordingStore(source_path)) as source, closing(DispatchArchive(source_path, 'chengwan')) as archive:
                source.initialize()
                archive.initialize()
                record_sample(source, 'white-shift', SAMPLES / 'shift.json')
                revision = freeze(source, 'white-shift')
                ledger = online_ledger(source, revision)
                online = [[row.trial, row.reference.reference if row.reference else None] for row in ledger]
                if online != [['bench-only-H', 'R1'], ['V', 'R2']]:
                    raise SystemExit(f'unexpected station ledger: {online!r}')
                wire = issue_package(source, archive, revision, {'V'})
                dispatch = decode_envelope(wire)['dispatch_id']
                if reissue_package(archive, dispatch) != wire:
                    raise SystemExit('resend did not return the archived bytes')
                receipt = accept_package(receipts, wire)

        exclusions = [(), ('BH',), ('B1',), ('BV',)]
        expected = [
            [['V', ['R2', 'B2', 'shift-register', 2]]],
            [['V', ['R1', 'B1', 'shift-register', 1]]],
            [['V', None]],
            [],
        ]
        with closing(ReceiptStore(offline_path)) as receipts, closing(ReportStore(offline_path)) as reports:
            reports.initialize()
            if get_received(receipts, receipt.receipt_id) != receipt:
                raise SystemExit('reopened receipt differs from the original')
            signed = [
                audit_package(receipts, reports, AuditRequest(receipt.receipt_id, f'night-{index}', excluded))
                for index, excluded in enumerate(exclusions)
            ]
        actual = [report_summary(report) for report in signed]
        if actual != expected:
            raise SystemExit(f'unexpected offline allocations: {actual!r}')
        with closing(ReportStore(offline_path)) as reopened:
            original = get_report(reopened, signed[0].report_id)
        downstream_expected = {'rows': expected[0], 'acknowledgment': 'signed/Q-1'}
        downstream_actual = {'rows': report_summary(original), 'acknowledgment': original.acknowledgment}
        if original != signed[0] or downstream_actual != downstream_expected:
            raise SystemExit('first signed report changed when reread')

        print(f'{revision} online: {online}')
        print(f'{dispatch} received as {receipt.receipt_id}: {receipt.acknowledgment}')
        for excluded, report in zip(exclusions, signed):
            print(f'{report.report_id} exclusions={list(excluded)} rows={report_summary(report)}')
        print('POINTWISE_SCENARIO ' + json.dumps({
            'case_id': 'counterfactual',
            'input': {'sample': 'samples/shift.json', 'receipt_id': receipt.receipt_id, 'exclusions': exclusions},
            'expected': expected,
            'actual': actual,
            'downstream_expected': downstream_expected,
            'downstream_actual': downstream_actual,
            'code_paths': ['issue/evidence.py', 'receive/lookup.py', 'review/replay.py', 'review/store.py'],
            'oracle': 'Hand trace of positions 10, 20, 30 and 40 with each exclusion applied independently.',
        }, sort_keys=True))


if __name__ == '__main__':
    main()
