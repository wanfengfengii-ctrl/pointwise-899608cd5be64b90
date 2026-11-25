import json
import sqlite3
from contextlib import closing

from issue.dispatch import issue_supplement
from issue.package import V2_VERSION, decode_envelope, encode_envelope
from receive.lookup import get_received
from receive.register import accept_package
from receive.verify import VerifiedSupplement, verify_package
from record.batches import record_batch
from record.events import ReferenceArrival, TrialUse
from record.origins import ReferenceOrigin
from record.revisions import freeze
from review.history import get_report
from review.request import AuditRequest, audit_package, audit_supplement
from review.store import SupplementReport
from tests.fixtures import ExchangeCase


COMPAT = 'private-alloy-key-27'
GATES = (('before', 0), ('after-v', 30))


def arrival(position, batch, name, key=COMPAT, document='shift-register', line=None):
    return ReferenceArrival(
        position, batch, name, key, '17.500', 'MPa',
        ReferenceOrigin(batch, document, line if line is not None else position),
    )


class SupplementCase(ExchangeCase):
    def build_revision(self, work='supplement'):
        record_batch(self.source, work, 'B1', [arrival(10, 'B1', 'R1', line=1)])
        record_batch(self.source, work, 'B2', [arrival(20, 'B2', 'R2', line=2)])
        record_batch(self.source, work, 'BH', [
            TrialUse(25, 'BH', 'bench-only-middle', COMPAT, '8843.937100', 'MPa'),
        ])
        record_batch(self.source, work, 'BV', [TrialUse(30, 'BV', 'V', COMPAT)])
        record_batch(self.source, work, 'BW', [TrialUse(40, 'BW', 'W', COMPAT)])
        self.revision = freeze(self.source, work)
        return self.revision

    def issue(self, revision=None, trials=('V', 'W'), gates=GATES, compatibility=COMPAT):
        revision = revision or getattr(self, 'revision', None) or self.build_revision()
        return issue_supplement(self.source, self.archive, revision, trials, compatibility, gates)

    def _received(self):
        return accept_package(self.receipts, self.issue())


class SupplementIssueTests(SupplementCase):
    def test_envelope_and_public_body(self):
        wire = self.issue()
        envelope = decode_envelope(wire)
        self.assertEqual(envelope['version'], V2_VERSION)
        body = envelope['body']
        self.assertEqual(body['kind'], 'supplement')
        self.assertEqual([row['trial'] for row in body['selected']], ['V', 'W'])
        self.assertEqual([row['reference'] for row in body['references']], ['R1', 'R2'])
        self.assertEqual(body['gates'], [{'gate': 'before', 'cutoff': 0}, {'gate': 'after-v', 'cutoff': 30}])
        kinds = [step['step'] for step in body['schedule']]
        self.assertEqual(kinds[0], 'demand')
        self.assertEqual(kinds[-1], 'demand')
        verified = verify_package(wire)
        self.assertIsInstance(verified, VerifiedSupplement)
        self.assertEqual(verified.gates, tuple(body['gates']))

    def test_internal_details_never_leave_station(self):
        wire = self.issue()
        public = json.dumps(decode_envelope(wire)['body'])
        for private in (
            'bench-only-middle', COMPAT, '8843.937100', '17.500', 'MPa', '"BH"',
        ):
            with self.subTest(private=private):
                self.assertNotIn(private, public)

    def test_empty_selection(self):
        wire = self.issue(trials=())
        body = decode_envelope(wire)['body']
        self.assertEqual(body['selected'], [])
        receipt = accept_package(self.receipts, wire)
        report = audit_supplement(self.receipts, self.reports, receipt.receipt_id, 'empty', [])
        self.assertEqual(report.rows, ())

    def test_selection_order_follows_positions(self):
        wire = self.issue(trials=('W', 'V'))
        self.assertEqual(
            [row['trial'] for row in decode_envelope(wire)['body']['selected']], ['V', 'W'],
        )

    def test_reissue_returns_original_bytes(self):
        wire = self.issue()
        dispatch_id = decode_envelope(wire)['dispatch_id']
        from issue.dispatch import reissue_package
        self.assertEqual(reissue_package(self.archive, dispatch_id), wire)

    def test_invalid_gates_rejected(self):
        revision = self.build_revision()
        with self.assertRaises(ValueError):
            issue_supplement(self.source, self.archive, revision, ('V',), COMPAT, (('before', 0), ('later', -5)))
        with self.assertRaises(ValueError):
            issue_supplement(self.source, self.archive, revision, ('V',), COMPAT, (('same', 1), ('same', 2)))
        with self.assertRaises(ValueError):
            issue_supplement(self.source, self.archive, revision, ('V',), COMPAT, (('bool-cutoff', True),))
        with self.assertRaises(ValueError):
            issue_supplement(self.source, self.archive, revision, ('V',), ' ', GATES)

    def test_selected_trial_must_share_class(self):
        work = 'mixed'
        record_batch(self.source, work, 'B1', [arrival(10, 'B1', 'R1')])
        record_batch(self.source, work, 'BV', [TrialUse(30, 'BV', 'V', COMPAT)])
        record_batch(self.source, work, 'BO', [TrialUse(40, 'BO', 'Other', 'another-key')])
        revision = freeze(self.source, work)
        with self.assertRaises(ValueError):
            issue_supplement(self.source, self.archive, revision, ('V', 'Other'), COMPAT, GATES)

    def test_unknown_trial_rejected(self):
        revision = self.build_revision()
        with self.assertRaises(ValueError):
            issue_supplement(self.source, self.archive, revision, ('V', 'Missing'), COMPAT, GATES)


class SupplementReceiveTests(SupplementCase):
    def test_accept_and_repeat(self):
        wire = self.issue()
        receipt = accept_package(self.receipts, wire)
        self.assertEqual(accept_package(self.receipts, wire), receipt)
        self.assertEqual(get_received(self.receipts, receipt.receipt_id), receipt)
        self.assertEqual(receipt.acknowledgment, f'received/{receipt.receipt_id}')

    def test_bad_wire_rejected_without_persistence(self):
        wire = self.issue()
        envelope = decode_envelope(wire)
        tampered = encode_envelope(
            envelope['issuer'], envelope['dispatch_id'], envelope['revision'], None, V2_VERSION,
        )
        for bad in (wire[:-1], b' ' + wire, tampered):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    accept_package(self.receipts, bad)
        self.assertEqual(accept_package(self.receipts, wire).receipt_id, 'I-1')

    def test_same_dispatch_different_bytes_rejected(self):
        wire = self.issue()
        accept_package(self.receipts, wire)
        envelope = decode_envelope(wire)
        body = json.loads(json.dumps(envelope['body']))
        body['gates'] = []
        different = encode_envelope(
            envelope['issuer'], envelope['dispatch_id'], envelope['revision'], body, V2_VERSION,
        )
        with self.assertRaises(ValueError):
            accept_package(self.receipts, different)

    def test_malformed_schedule_rejected(self):
        wire = self.issue()
        envelope = decode_envelope(wire)
        body = json.loads(json.dumps(envelope['body']))
        # Swap the first gate with a later station step: canonical gate/order
        # invariants must reject the replayed schedule.
        body['schedule'][1], body['schedule'][3] = body['schedule'][3], body['schedule'][1]
        bad = encode_envelope(
            envelope['issuer'], 'another-dispatch', envelope['revision'], body, V2_VERSION,
        )
        with self.assertRaises(ValueError):
            accept_package(self.receipts, bad)

    def test_gate_cutoff_mismatch_rejected(self):
        wire = self.issue()
        envelope = decode_envelope(wire)
        body = json.loads(json.dumps(envelope['body']))
        gate_step = next(step for step in body['schedule'] if step['step'] == 'gate')
        gate_step['cutoff'] = 5
        bad = encode_envelope(
            envelope['issuer'], 'another-dispatch', envelope['revision'], body, V2_VERSION,
        )
        with self.assertRaises(ValueError):
            accept_package(self.receipts, bad)

    def test_forged_demand_changes_replay_but_keeps_structure(self):
        # Internal demand counts are private whole-segment evidence. The
        # receiving side validates structure and evidence references; the
        # station ledger remains the reconciliation authority for the counts.
        wire = self.issue()
        envelope = decode_envelope(wire)
        body = json.loads(json.dumps(envelope['body']))
        demand = next(step for step in body['schedule'] if step['step'] == 'demand' and step['count'])
        demand['count'] += 1
        forged = encode_envelope(
            envelope['issuer'], 'another-dispatch', envelope['revision'], body, V2_VERSION,
        )
        receipt = accept_package(self.receipts, forged)
        report = audit_supplement(self.receipts, self.reports, receipt.receipt_id, 'forged', [])
        names = [row['reference']['reference'] if row['reference'] else None for row in report.rows]
        self.assertEqual(names, [None, None])

    def test_undeclared_reference_batch_rejected(self):
        wire = self.issue()
        envelope = decode_envelope(wire)
        body = json.loads(json.dumps(envelope['body']))
        body['references'][0]['batch'] = 'UNLEAKED'
        body['references'][0]['origin']['batch'] = 'UNLEAKED'
        bad = encode_envelope(
            envelope['issuer'], 'another-dispatch', envelope['revision'], body, V2_VERSION,
        )
        with self.assertRaises(ValueError):
            accept_package(self.receipts, bad)

    def test_unknown_gate_in_schedule_rejected(self):
        wire = self.issue()
        envelope = decode_envelope(wire)
        body = json.loads(json.dumps(envelope['body']))
        body['schedule'][1]['gate'] = 'undeclared'
        bad = encode_envelope(
            envelope['issuer'], 'another-dispatch', envelope['revision'], body, V2_VERSION,
        )
        with self.assertRaises(ValueError):
            accept_package(self.receipts, bad)

    def test_v1_and_v2_route_to_different_verifiers(self):
        from issue.dispatch import issue_package
        v1 = issue_package(self.source, self.archive, self.build_revision(), ('V', 'W'))
        v2 = self.issue()
        self.assertEqual(decode_envelope(v1)['version'], 1)
        self.assertEqual(decode_envelope(v2)['version'], 2)
        self.assertNotIsInstance(verify_package(v1), VerifiedSupplement)
        self.assertIsInstance(verify_package(v2), VerifiedSupplement)


class SupplementAuditTests(SupplementCase):
    def test_station_only_allocation_and_late_arrival(self):
        receipt = self._received()
        report = audit_supplement(self.receipts, self.reports, receipt.receipt_id, 'none', [])
        self.assertEqual(
            [row['reference']['reference'] if row['reference'] else None for row in report.rows],
            ['R2', None],
        )
        late = audit_supplement(
            self.receipts, self.reports, receipt.receipt_id, 'late',
            [('after-v', 'X', 'partner-register', 1)],
        )
        names = [row['reference']['reference'] if row['reference'] else None for row in late.rows]
        self.assertEqual(names, ['R2', 'X'])
        arrival_ref = late.rows[1]['reference']
        self.assertEqual(arrival_ref['source'], 'arrival')
        self.assertEqual(arrival_ref['gate'], 'after-v')
        self.assertEqual(arrival_ref['origin'], {'document': 'partner-register', 'line': 1})
        station_ref = late.rows[0]['reference']
        self.assertEqual(station_ref['source'], 'station')
        self.assertEqual(station_ref['batch'], 'B2')

    def test_gate_insertion_and_effective_order(self):
        receipt = self._received()
        report = audit_supplement(
            self.receipts, self.reports, receipt.receipt_id, 'mixed',
            [('after-v', 'Y', 'partner-register', 2), ('before', 'X', 'partner-register', 1)],
        )
        self.assertEqual(report.arrivals, (
            ('before', 'X', 'partner-register', 1),
            ('after-v', 'Y', 'partner-register', 2),
        ))
        names = [row['reference']['reference'] if row['reference'] else None for row in report.rows]
        # X joins at the first gate and sits at the queue head; the internal
        # use at position 25 consumes X, so V takes station R1 and W takes R2.
        # Y only arrives after V and stays unused beyond the selected trials.
        self.assertEqual(names, ['R1', 'R2'])
        self.assertTrue(all(row['reference']['source'] == 'station' for row in report.rows))

    def test_null_rows_kept_and_later_arrivals_do_not_rewrite(self):
        receipt = self._received()
        report = audit_supplement(
            self.receipts, self.reports, receipt.receipt_id, 'one-late',
            [('after-v', 'X', 'partner-register', 1)],
        )
        self.assertEqual([row['position'] for row in report.rows], [30, 40])
        self.assertEqual(report.rows[0]['reference']['reference'], 'R2')
        self.assertEqual(report.rows[1]['reference']['reference'], 'X')

    def test_used_reference_never_returns(self):
        receipt = self._received()
        report = audit_supplement(
            self.receipts, self.reports, receipt.receipt_id, 'three',
            [('before', name, 'partner-register', index) for index, name in enumerate(('X', 'Y', 'Z'), 1)],
        )
        # The internal middle use consumes X first; each later use takes the
        # current head, so neither X nor the station references reappear.
        names = [row['reference']['reference'] for row in report.rows]
        self.assertEqual(names, ['Y', 'Z'])
        self.assertTrue(all(row['reference']['source'] == 'arrival' for row in report.rows))

    def test_station_reference_surfaces_after_partners_consumed(self):
        receipt = self._received()
        report = audit_supplement(
            self.receipts, self.reports, receipt.receipt_id, 'two',
            [('before', 'X', 'partner-register', 1), ('before', 'Y', 'partner-register', 2)],
        )
        names = [row['reference']['reference'] for row in report.rows]
        self.assertEqual(names, ['Y', 'R1'])
        self.assertEqual(report.rows[1]['reference']['source'], 'station')

    def test_repeat_request_returns_same_report(self):
        receipt = self._received()
        arrivals = [('before', 'X', 'partner-register', 1)]
        first = audit_supplement(self.receipts, self.reports, receipt.receipt_id, 'same', arrivals)
        second = audit_supplement(self.receipts, self.reports, receipt.receipt_id, 'same', list(arrivals))
        self.assertEqual(second, first)

    def test_same_request_different_parameters_rejected(self):
        receipt = self._received()
        audit_supplement(self.receipts, self.reports, receipt.receipt_id, 'bound', [])
        with self.assertRaises(ValueError):
            audit_supplement(
                self.receipts, self.reports, receipt.receipt_id, 'bound',
                [('before', 'X', 'partner-register', 1)],
            )
        other = self._received()
        with self.assertRaises(ValueError):
            audit_supplement(self.receipts, self.reports, other.receipt_id, 'bound', [])

    def test_unknown_gate_duplicate_name_and_bad_lines_rejected(self):
        receipt = self._received()
        with self.assertRaises(ValueError):
            audit_supplement(
                self.receipts, self.reports, receipt.receipt_id, 'bad-gate',
                [('nowhere', 'X', 'partner-register', 1)],
            )
        with self.assertRaises(ValueError):
            audit_supplement(
                self.receipts, self.reports, receipt.receipt_id, 'dup',
                [('before', 'X', 'partner-register', 1), ('after-v', 'X', 'partner-register', 2)],
            )
        for bad_line in (0, -1, True, '1'):
            with self.subTest(bad_line=bad_line):
                with self.assertRaises(ValueError):
                    audit_supplement(
                        self.receipts, self.reports, receipt.receipt_id, f'line-{bad_line}',
                        [('before', 'X', 'partner-register', bad_line)],
                    )

    def test_unknown_receipt_raises_key_error(self):
        self._received()
        with self.assertRaises(KeyError):
            audit_supplement(self.receipts, self.reports, 'I-99', 'missing', [])

    def test_version_entries_cannot_cross(self):
        from issue.dispatch import issue_package
        v1_receipt = accept_package(
            self.receipts, issue_package(self.source, self.archive, self.build_revision(), ('V', 'W')),
        )
        v2_receipt = self._received()
        with self.assertRaises(ValueError):
            audit_supplement(self.receipts, self.reports, v1_receipt.receipt_id, 'wrong', [])
        with self.assertRaises(ValueError):
            audit_package(
                self.receipts, self.reports, AuditRequest(v2_receipt.receipt_id, 'wrong'),
            )

    def test_persisted_and_reopened_after_closure(self):
        receipt = self._received()
        report = audit_supplement(
            self.receipts, self.reports, receipt.receipt_id, 'signed',
            [('before', 'X', 'partner-register', 1)],
        )
        self.assertIsInstance(report, SupplementReport)
        self.close_source()
        self.reopen_offline()
        readback = get_report(self.reports, report.report_id)
        self.assertEqual(readback, report)
        self.assertEqual(readback.acknowledgment, report.acknowledgment)

    def test_commit_failure_leaves_no_supplement_report(self):
        import sqlite3
        receipt = self._received()
        self.close_source()
        self.reopen_offline()
        self.reports._db.set_authorizer(
            lambda action, name, *_: sqlite3.SQLITE_DENY
            if action == sqlite3.SQLITE_TRANSACTION and name == 'COMMIT' else sqlite3.SQLITE_OK
        )
        with self.assertRaises(sqlite3.Error):
            audit_supplement(
                self.receipts, self.reports, receipt.receipt_id, 'failed',
                [('before', 'X', 'partner-register', 1)],
            )
        self.reports._db.set_authorizer(None)
        with self.assertRaises(KeyError):
            get_report(self.reports, 'S-1')
        recovered = audit_supplement(self.receipts, self.reports, receipt.receipt_id, 'recovered', [])
        self.assertEqual(
            [row['reference']['reference'] if row['reference'] else None for row in recovered.rows],
            ['R2', None],
        )

    def test_v1_history_remains_readable_alongside(self):
        from issue.dispatch import issue_package
        v1 = accept_package(
            self.receipts, issue_package(self.source, self.archive, self.build_revision(), ('V',)),
        )
        v1_report = audit_package(self.receipts, self.reports, AuditRequest(v1.receipt_id, 'legacy'))
        v2_report = audit_supplement(self.receipts, self.reports, self._received().receipt_id, 'new', [])
        self.reopen_offline()
        self.assertEqual(get_report(self.reports, v1_report.report_id), v1_report)
        self.assertEqual(get_report(self.reports, v2_report.report_id), v2_report)
        with closing(sqlite3.connect(self.offline_path)) as connection:
            self.assertEqual(
                connection.execute('SELECT count(*) FROM supplement_reports').fetchone(), (1,),
            )
