import json

from issue.dispatch import issue_package, reissue_package
from issue.package import decode_envelope, encode_package
from receive.lookup import get_received
from receive.register import accept_package
from receive.verify import verify_package
from record.batches import record_batch
from record.events import TrialUse
from record.revisions import freeze
from tests.fixtures import ExchangeCase, citation, independent_package


class ExchangeTests(ExchangeCase):
    def test_scope(self):
        old = self.frozen()
        record_batch(self.source, 'shift', 'BW', [TrialUse(60, 'BW', 'W', 'private-alloy-key-27')])
        new = freeze(self.source, 'shift')
        with self.assertRaises(ValueError):
            issue_package(self.source, self.archive, old, ['V', 'W'])
        with self.assertRaises(KeyError):
            reissue_package(self.archive, 'D-1')
        new_piece = issue_package(self.source, self.archive, new, ['W'])
        self.assertEqual(decode_envelope(new_piece)['dispatch_id'], 'D-1')

    def test_repeat(self):
        revision = self.frozen()
        wire = issue_package(self.source, self.archive, revision, ['V'])
        issued = decode_envelope(wire)
        receipt = accept_package(self.receipts, wire)
        resend = reissue_package(self.archive, issued['dispatch_id'])
        self.assertEqual(resend, wire)
        self.assertEqual(accept_package(self.receipts, resend), receipt)
        retained = get_received(self.receipts, receipt.receipt_id)
        self.assertEqual(retained, receipt)
        self.assertEqual((retained.issuer, retained.dispatch_id, retained.revision), ('chengwan', 'D-1', revision))
        expected = {'receipt_id': 'I-1', 'acknowledgment': 'received/I-1', 'original_bytes': True}
        actual = {
            'receipt_id': retained.receipt_id,
            'acknowledgment': retained.acknowledgment,
            'original_bytes': retained.wire == wire,
        }
        self.assertEqual(actual, expected)
        print('POINTWISE_SCENARIO ' + json.dumps({
            'case_id': 'repeat', 'input': {'revision': revision, 'selected': ['V']},
            'expected': True, 'actual': resend == wire,
            'downstream_expected': expected, 'downstream_actual': actual,
            'code_paths': ['issue/archive.py', 'issue/dispatch.py', 'receive/register.py', 'receive/lookup.py'],
            'oracle': 'Compare the entire reissued byte string with the original and read the first receipt back.',
        }, sort_keys=True))

    def test_after_source_change(self):
        revision = self.frozen()
        receipt = self.receive(revision)
        record_batch(self.source, 'shift', 'BW', [TrialUse(60, 'BW', 'W', 'private-alloy-key-27')])
        newer = freeze(self.source, 'shift')
        newer_receipt = self.receive(newer, ['W'])
        resend = reissue_package(self.archive, receipt.dispatch_id)
        self.assertEqual(resend, receipt.wire)
        self.assertEqual(decode_envelope(resend)['revision'], revision)
        self.assertNotEqual(newer_receipt.revision, revision)
        self.assertEqual(accept_package(self.receipts, resend), receipt)

    def test_contest_evidence(self):
        first = self.receive(self.frozen())
        second = self.receive(self.frozen('alternate', 'alternate.json'))
        first_body = decode_envelope(first.wire)['body']
        second_body = decode_envelope(second.wire)['body']
        self.assertEqual(first_body['batches'], second_body['batches'])
        self.assertEqual(first_body['selected'], second_body['selected'])
        self.assertEqual(first_body['original'], second_body['original'])
        self.assertNotEqual(first_body, second_body)
        for receipt in (first, second):
            self.assertEqual(reissue_package(self.archive, receipt.dispatch_id), receipt.wire)
        self.close_source()
        self.reopen_offline()
        self.assertEqual(self.audit(first, 'first', ['BH']).rows[0]['reference'], citation(10, 'B1', 'R1', 1))
        self.assertEqual(self.audit(second, 'second', ['BH']).rows[0]['reference'], citation(20, 'B2', 'R2', 2))

    def test_disclosure(self):
        receipt = self.receive(self.frozen())
        decoded = json.dumps(decode_envelope(receipt.wire), sort_keys=True)
        for private in ('bench-only-H', 'private-alloy-key-27', '8843.937100', '672.1030', '17.500'):
            with self.subTest(private=private):
                self.assertNotIn(private, decoded)
        self.assertEqual([trial['trial'] for trial in verify_package(receipt.wire).selected], ['V'])

    def test_same_number_different_body(self):
        first = independent_package()
        second = independent_package(document='register-copy')
        one, two = verify_package(first), verify_package(second)
        self.assertEqual((one.issuer, one.dispatch_id), (two.issuer, two.dispatch_id))
        self.assertNotEqual(one.original, two.original)
        accepted = accept_package(self.receipts, first)
        with self.assertRaises(ValueError):
            accept_package(self.receipts, second)
        self.assertEqual(get_received(self.receipts, accepted.receipt_id), accepted)
        self.assertEqual(accept_package(self.receipts, first), accepted)
        with self.assertRaises(KeyError):
            get_received(self.receipts, 'I-2')

    def test_distinct_dispatches(self):
        revision = self.frozen()
        one = self.receive(revision, ['V'])
        two = self.receive(revision, ['bench-only-H'])
        self.assertEqual(one.revision, two.revision)
        self.assertNotEqual(one.receipt_id, two.receipt_id)
        self.assertNotEqual(one.acknowledgment, two.acknowledgment)
        for receipt, trial in ((one, 'V'), (two, 'bench-only-H')):
            loaded = get_received(self.receipts, receipt.receipt_id)
            self.assertEqual(loaded, receipt)
            self.assertEqual([row['trial'] for row in verify_package(loaded.wire).selected], [trial])

    def test_offline_receipt(self):
        receipt = self.receive(self.frozen())
        self.close_source()
        self.reopen_offline()
        recovered = get_received(self.receipts, receipt.receipt_id)
        self.assertEqual(recovered, receipt)
        self.assertEqual(recovered.wire, receipt.wire)

    def test_init_preserves(self):
        receipt = self.receive(self.frozen())
        self.archive.initialize()
        self.receipts.initialize()
        self.close_source()
        self.open_source()
        self.reopen_offline()
        self.assertEqual(reissue_package(self.archive, receipt.dispatch_id), receipt.wire)
        self.assertEqual(get_received(self.receipts, receipt.receipt_id), receipt)
        self.assertEqual(accept_package(self.receipts, receipt.wire), receipt)

    def test_bad(self):
        receipt = self.receive(self.frozen())
        envelope = decode_envelope(receipt.wire)
        envelope['body']['uses'][0]['eligible'] = [50]
        bad_structure = encode_package('chengwan', 'another', envelope['revision'], envelope['body'])
        stale_checksum = json.dumps(envelope).encode('utf-8')
        for wire in (receipt.wire[:-4], stale_checksum, bad_structure):
            with self.subTest(wire=wire):
                with self.assertRaises(ValueError):
                    accept_package(self.receipts, wire)
        with self.assertRaises(KeyError):
            get_received(self.receipts, 'I-2')
        self.assertEqual(get_received(self.receipts, receipt.receipt_id), receipt)

    def test_empty_selection_and_empty_batch(self):
        self.frozen()
        record_batch(self.source, 'shift', 'EMPTY', [])
        receipt = self.receive(freeze(self.source, 'shift'), [])
        piece = verify_package(receipt.wire)
        self.assertIn('EMPTY', piece.batches)
        self.assertEqual(piece.selected, ())
        self.assertEqual(self.audit(receipt, 'empty-selection', {'EMPTY'}).rows, ())
