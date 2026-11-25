import sqlite3
from contextlib import closing
from itertools import combinations

from issue.package import decode_envelope, encode_package
from receive.register import accept_package
from record.batches import record_batch
from record.events import ReferenceArrival, TrialUse
from record.revisions import freeze, read_frozen_revision
from review.history import get_report
from tests.fixtures import ExchangeCase, citation, independent_package, install_commit_failure, persisted_reports


def row(position, trial, reference):
    return {'position': position, 'trial': trial, 'reference': reference}


def original_event_oracle(events, selected, excluded):
    inventory = {
        event.position: event for event in events
        if isinstance(event, ReferenceArrival) and event.batch not in excluded
    }
    trials = sorted(
        (event for event in events if isinstance(event, TrialUse) and event.batch not in excluded),
        key=lambda event: event.position,
    )
    result = []
    for trial in trials:
        earliest = min((position for position, candidate in inventory.items()
                        if position < trial.position and candidate.compatibility == trial.compatibility), default=None)
        reference = inventory.pop(earliest) if earliest is not None else None
        if trial.trial in selected:
            sourced = None
            if reference is not None:
                sourced = citation(reference.position, reference.batch, reference.reference,
                                    reference.origin.line, reference.origin.document)
            result.append(row(trial.position, trial.trial, sourced))
    return tuple(result)


class ReviewTests(ExchangeCase):
    def test_counterfactual(self):
        receipt = self.receive(self.frozen())
        self.close_source()
        self.reopen_offline()
        original = self.audit(receipt, 'Q0')
        released = self.audit(receipt, 'without-H', {'BH'})
        reallocated = self.audit(receipt, 'without-R1', {'B1'})
        self.assertEqual(original.rows, (row(40, 'V', citation(20, 'B2', 'R2', 2)),))
        self.assertEqual(released.rows, (row(40, 'V', citation(10, 'B1', 'R1', 1)),))
        self.assertEqual(reallocated.rows, (row(40, 'V', None),))
        self.assertEqual(released.excluded_batches, ('BH',))
        self.assertEqual(reallocated.excluded_batches, ('B1',))
        self.assertEqual(original.acknowledgment, 'signed/Q-1')
        self.reopen_offline()
        self.assertEqual(get_report(self.reports, original.report_id), original)

    def test_empty_exclusions(self):
        receipt = self.receive(self.frozen())
        self.close_source()
        report = self.audit(receipt, 'no-exclusions', ())
        self.assertEqual(report.excluded_batches, ())
        self.assertEqual(report.rows, (row(40, 'V', citation(20, 'B2', 'R2', 2)),))
        self.assertEqual(report.receipt_id, receipt.receipt_id)

    def test_withdraw_selected(self):
        receipt = self.receive(self.frozen())
        self.close_source()
        report = self.audit(receipt, 'withdraw-V', ['BV'])
        self.assertEqual(report.rows, ())
        self.assertEqual(get_report(self.reports, report.report_id), report)

    def test_late_and_equal(self):
        self.frozen()
        record_batch(self.source, 'shift', 'BW', [
            TrialUse(60, 'BW', 'W', 'private-alloy-key-27'),
            TrialUse(-5, 'BW', 'First', 'private-alloy-key-27'),
        ])
        receipt = self.receive(freeze(self.source, 'shift'), ['W', 'V', 'bench-only-H', 'First'])
        self.close_source()
        report = self.audit(receipt, 'late-equal')
        self.assertEqual(report.rows, (
            row(-5, 'First', None),
            row(30, 'bench-only-H', citation(10, 'B1', 'R1', 1)),
            row(40, 'V', citation(20, 'B2', 'R2', 2)),
            row(60, 'W', citation(50, 'B1', 'L', 5)),
        ))

    def test_subset_oracle(self):
        cases = []
        for work, sample in (('shift', 'shift.json'), ('alternate', 'alternate.json')):
            revision = self.frozen(work, sample)
            snapshot = read_frozen_revision(self.source, revision)
            cases.append((self.receive(revision), snapshot.batches, snapshot.events))
        self.close_source()
        self.reopen_offline()
        for receipt, batches, events in cases:
            original = None
            for size in range(len(batches) + 1):
                for removed in combinations(batches, size):
                    with self.subTest(receipt=receipt.receipt_id, removed=removed):
                        expected = original_event_oracle(events, {'V'}, set(removed))
                        request_id = f'{receipt.receipt_id}/{size}/{removed!r}'
                        report = self.audit(receipt, request_id, removed)
                        self.assertEqual(report.rows, expected)
                        if not removed:
                            original = report
            self.assertEqual(get_report(self.reports, original.report_id), original)

    def test_receipt_binding(self):
        primary = self.receive(self.frozen())
        self.frozen('alternate', 'alternate.json')
        record_batch(self.source, 'alternate', 'BW', [TrialUse(60, 'BW', 'W', 'private-alloy-key-27')])
        other = self.receive(freeze(self.source, 'alternate'), ('W', 'V'))
        self.close_source()
        self.reopen_offline()
        first = self.audit(primary, 'primary', ('BH',))
        second = self.audit(other, 'other', ('BH',))
        self.assertEqual(first.receipt_id, primary.receipt_id)
        self.assertEqual(second.receipt_id, other.receipt_id)
        self.assertEqual(first.rows, (row(40, 'V', citation(10, 'B1', 'R1', 1)),))
        self.assertEqual(second.rows, (
            row(40, 'V', citation(20, 'B2', 'R2', 2)),
            row(60, 'W', citation(50, 'B1', 'L', 5)),
        ))

    def test_independent_current_package(self):
        receipt = accept_package(self.receipts, independent_package())
        self.close_source()
        self.reopen_offline()
        original = self.audit(receipt, 'incoming-original')
        self.assertEqual(original.rows, (row(40, 'V', citation(20, 'B2', 'R2', 2)),))
        self.assertEqual(self.audit(receipt, 'incoming-without-H', ['BH']).rows,
                         (row(40, 'V', citation(10, 'B1', 'R1', 1)),))
        self.assertEqual(self.audit(receipt, 'incoming-without-R1', ['B1']).rows, (row(40, 'V', None),))
        self.assertEqual(get_report(self.reports, original.report_id), original)

    def test_unknown(self):
        receipt = self.receive(self.frozen())
        self.close_source()
        with self.assertRaises(ValueError):
            self.audit(receipt, 'unknown', ['B1', 'never-declared'])
        with self.assertRaises(KeyError):
            get_report(self.reports, 'Q-1')
        self.assertEqual(persisted_reports(self.offline_path), ([], []))

    def test_receipt_batches(self):
        primary = self.receive(self.frozen())
        record_batch(self.source, 'shift', 'OTHER-ONLY', [])
        other = self.receive(freeze(self.source, 'shift'))
        self.close_source()
        self.reopen_offline()
        valid = self.audit(other, 'other-can-remove', ['OTHER-ONLY'])
        with self.assertRaises(ValueError):
            self.audit(primary, 'primary-cannot-remove', ['OTHER-ONLY'])
        self.assertEqual(persisted_reports(self.offline_path), ([(1, 'other-can-remove')], [(1, valid.acknowledgment)]))

    def test_failure(self):
        receipt = self.receive(self.frozen())
        self.close_source()
        self.reopen_offline()
        old = self.audit(receipt, 'before-failure')
        install_commit_failure(self.offline_path)
        with self.assertRaises(sqlite3.IntegrityError):
            self.audit(receipt, 'failed-commit', ['BH'])
        self.assertEqual(get_report(self.reports, old.report_id), old)
        self.assertEqual(persisted_reports(self.offline_path), ([(1, 'before-failure')], [(1, old.acknowledgment)]))
        self.reopen_offline()
        self.reports.initialize()
        self.assertEqual(get_report(self.reports, old.report_id), old)
        with self.assertRaises(KeyError):
            get_report(self.reports, 'Q-2')
        self.assertEqual(persisted_reports(self.offline_path), ([(1, 'before-failure')], [(1, old.acknowledgment)]))
        with closing(sqlite3.connect(self.offline_path)) as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM test_submit_pending').fetchone(), (0,))
            connection.executescript('DROP TRIGGER test_reject_report_on_commit;')
        recovered = self.audit(receipt, 'failed-commit', ['BH'])
        self.assertEqual(recovered.rows, (row(40, 'V', citation(10, 'B1', 'R1', 1)),))
        self.assertEqual(recovered.acknowledgment, 'signed/Q-2')

    def test_corrupted_stored_package(self):
        receipt = self.receive(self.frozen())
        self.close_source()
        envelope = decode_envelope(receipt.wire)
        different_revision = encode_package(receipt.issuer, receipt.dispatch_id, 'other-freeze', envelope['body'])
        for corrupt_wire in (receipt.wire[:-1], different_revision):
            with self.subTest(corrupt_wire=corrupt_wire):
                with closing(sqlite3.connect(self.offline_path)) as connection, connection:
                    connection.execute('UPDATE received_packages SET wire = ?', (corrupt_wire,))
                with self.assertRaises(ValueError):
                    self.audit(receipt, 'corrupt', ['BH'])
                self.assertEqual(persisted_reports(self.offline_path), ([], []))

    def test_legacy_package_and_history(self):
        wire = independent_package(historical=True)
        receipt = accept_package(self.receipts, wire)
        self.close_source()
        original = self.audit(receipt, 'historical')
        self.assertEqual(original.rows, (row(40, 'V', citation(20, 'B2', 'R2', 2)),))
        self.reopen_offline()
        self.assertEqual(self.receipts.load_receipt(receipt.receipt_id).wire, wire)
        self.assertEqual(accept_package(self.receipts, wire), receipt)
        self.assertEqual(get_report(self.reports, original.report_id), original)
        with self.assertRaises(ValueError):
            self.audit(receipt, 'historical-counterfactual', ['BH'])
        self.assertEqual(persisted_reports(self.offline_path), ([(1, 'historical')], [(1, original.acknowledgment)]))

    def test_report_request_binding(self):
        receipt = self.receive(self.frozen())
        first = self.audit(receipt, 'same-request', ['B1', 'BH'])
        self.assertEqual(self.audit(receipt, 'same-request', ['BH', 'B1', 'BH']), first)
        with self.assertRaises(ValueError):
            self.audit(receipt, 'same-request', ['BH'])
        self.assertEqual(get_report(self.reports, first.report_id), first)
        self.assertEqual(persisted_reports(self.offline_path), ([(1, 'same-request')], [(1, first.acknowledgment)]))
