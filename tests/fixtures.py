import sqlite3
import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from demo import SAMPLES, record_sample
from issue.archive import DispatchArchive
from issue.dispatch import issue_package
from issue.package import encode_package
from receive.register import accept_package
from receive.store import ReceiptStore
from record.revisions import freeze
from record.store import RecordingStore
from review.request import AuditRequest, audit_package
from review.store import ReportStore


class ExchangeCase(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory(prefix='test-reference-exchange-')
        self.addCleanup(directory.cleanup)
        self.source_path = Path(directory.name) / 'source.sqlite3'
        self.offline_path = Path(directory.name) / 'offline.sqlite3'
        self.open_source()
        self.open_offline()

    def _initialize(self, store):
        self.addCleanup(store.close)
        store.initialize()
        return store

    def open_source(self):
        self.source = self._initialize(RecordingStore(self.source_path))
        self.archive = self._initialize(DispatchArchive(self.source_path, 'chengwan'))

    def close_source(self):
        self.archive.close()
        self.source.close()

    def open_offline(self):
        self.receipts = self._initialize(ReceiptStore(self.offline_path))
        self.reports = self._initialize(ReportStore(self.offline_path))

    def reopen_offline(self):
        self.receipts.close()
        self.reports.close()
        self.open_offline()

    def frozen(self, work='shift', sample='shift.json'):
        record_sample(self.source, work, SAMPLES / sample)
        return freeze(self.source, work)

    def receive(self, revision, trials=('V',)):
        return accept_package(self.receipts, issue_package(self.source, self.archive, revision, trials))

    def audit(self, receipt, request_id, excluded=()):
        return audit_package(self.receipts, self.reports, AuditRequest(receipt.receipt_id, request_id, excluded))


def citation(position, batch, reference, line, document='shift-register'):
    return {
        'position': position,
        'batch': batch,
        'reference': reference,
        'origin': {'batch': batch, 'document': document, 'line': line},
    }


def independent_package(*, historical=False, document='shift-register'):
    r1 = citation(10, 'B1', 'R1', 1, document)
    r2 = citation(20, 'B2', 'R2', 2, document)
    body = {
        'kind': 'paired' if historical else 'replay',
        'batches': ['B1', 'B2', 'BH', 'BV'],
        'selected': [{'position': 40, 'batch': 'BV', 'trial': 'V'}],
        'original': [{'position': 40, 'trial': 'V', 'reference': r2}],
    }
    if not historical:
        body['references'] = [r1, r2]
        body['uses'] = [
            {'position': 30, 'batch': 'BH', 'eligible': [10, 20]},
            {'position': 40, 'batch': 'BV', 'eligible': [10, 20]},
        ]
    return encode_package('independent-station', 'manual-1', 'reference-shift', body)


def install_commit_failure(path):
    with closing(sqlite3.connect(path)) as connection:
        connection.executescript('''
            CREATE TABLE test_submit_allowed (token TEXT PRIMARY KEY);
            CREATE TABLE test_submit_pending (
                token TEXT REFERENCES test_submit_allowed (token) DEFERRABLE INITIALLY DEFERRED
            );
            CREATE TRIGGER test_reject_report_on_commit AFTER INSERT ON report_acknowledgments
            BEGIN
                INSERT INTO test_submit_pending (token) VALUES (NEW.token);
            END;
        ''')


def persisted_reports(path):
    with closing(sqlite3.connect(path)) as connection:
        numbers = connection.execute('SELECT number, request_id FROM signed_reports ORDER BY number').fetchall()
        acknowledgments = connection.execute('SELECT number, token FROM report_acknowledgments ORDER BY number').fetchall()
        return numbers, acknowledgments
