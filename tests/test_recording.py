import json

from assign.ledger import online_ledger
from demo import SAMPLES, sample_batches
from record.batches import record_batch
from record.events import ReferenceArrival, TrialUse
from record.origins import ReferenceOrigin
from record.revisions import freeze, read_frozen_revision
from tests.fixtures import ExchangeCase


def ledger_rows(ledger):
    return [
        [row.position, row.trial, None if row.reference is None else [
            row.reference.reference, row.reference.origin.batch, row.reference.origin.document, row.reference.origin.line,
        ]]
        for row in ledger
    ]


EXPECTED = [
    [30, 'bench-only-H', ['R1', 'B1', 'shift-register', 1]],
    [40, 'V', ['R2', 'B2', 'shift-register', 2]],
]


class RecordingTests(ExchangeCase):
    def test_normal(self):
        revision = self.frozen()
        actual = ledger_rows(online_ledger(self.source, revision))
        self.assertEqual(actual, EXPECTED)
        snapshot = read_frozen_revision(self.source, revision)
        positions = [event.position for event in snapshot.events]
        self.assertEqual(positions, [10, 20, 30, 40, 50])
        self.assertEqual(snapshot.batches, ('B1', 'B2', 'BH', 'BV'))
        print('POINTWISE_SCENARIO ' + json.dumps({
            'case_id': 'normal',
            'input': {'sample': 'samples/shift.json', 'revision': revision},
            'expected': EXPECTED, 'actual': actual,
            'downstream_expected': [10, 20, 30, 40, 50], 'downstream_actual': positions,
            'code_paths': ['record/revisions.py', 'record/store.py', 'assign/ledger.py', 'assign/replay.py'],
            'oracle': 'Hand trace of arrivals and uses in original position order.',
        }, sort_keys=True))

    def test_shuffled_input(self):
        for batch, events in reversed(sample_batches(SAMPLES / 'shift.json')):
            record_batch(self.source, 'shuffled', batch, reversed(events))
        revision = freeze(self.source, 'shuffled')
        self.assertEqual(ledger_rows(online_ledger(self.source, revision)), EXPECTED)

    def test_same_value(self):
        h, v = online_ledger(self.source, self.frozen())
        self.assertEqual((h.reference.value, v.reference.value), ('17.500', '17.500'))
        self.assertEqual((h.reference.unit, v.reference.unit), ('MPa', 'MPa'))
        self.assertEqual((h.reference.reference, v.reference.reference), ('R1', 'R2'))
        self.assertEqual(h.reference.origin, ReferenceOrigin('B1', 'shift-register', 1))
        self.assertEqual(v.reference.origin, ReferenceOrigin('B2', 'shift-register', 2))

    def test_late(self):
        record_batch(self.source, 'timing', 'BT', [
            TrialUse(30, 'BT', 'W', 'key'),
            ReferenceArrival(20, 'BT', 'R', 'key', '1.00', 'MPa', ReferenceOrigin('BT', 'sheet', 3)),
            TrialUse(10, 'BT', 'V', 'key'),
        ])
        ledger = online_ledger(self.source, freeze(self.source, 'timing'))
        self.assertEqual(ledger_rows(ledger), [[10, 'V', None], [30, 'W', ['R', 'BT', 'sheet', 3]]])

    def test_position(self):
        revision = self.frozen()
        arrival = ReferenceArrival(70, 'BD', 'R3', 'key', '1', 'MPa', ReferenceOrigin('BD', 'sheet', 1))
        with self.assertRaises(ValueError):
            record_batch(self.source, 'shift', 'BD', [arrival, TrialUse(70, 'BD', 'D', 'key')])
        with self.assertRaises(ValueError):
            record_batch(self.source, 'shift', 'BD', [TrialUse(40, 'BD', 'D', 'key')])
        self.assertNotIn('BD', self.source.load_working_revision('shift').batches)
        self.assertEqual(ledger_rows(online_ledger(self.source, revision)), EXPECTED)
        self.assertEqual(ledger_rows(online_ledger(self.source, freeze(self.source, 'shift'))), EXPECTED)

    def test_illegal_origin(self):
        revision = self.frozen()
        origin = ReferenceOrigin('another-batch', 'sheet', 2)
        incoming = [
            TrialUse(60, 'BAD', 'valid-first', 'key'),
            ReferenceArrival(70, 'BAD', 'bad-ref', 'key', '2', 'MPa', origin),
        ]
        with self.assertRaises(ValueError):
            record_batch(self.source, 'shift', 'BAD', incoming)
        self.assertNotIn('BAD', self.source.load_working_revision('shift').batches)
        self.assertEqual(ledger_rows(online_ledger(self.source, revision)), EXPECTED)
        self.assertEqual(ledger_rows(online_ledger(self.source, freeze(self.source, 'shift'))), EXPECTED)

    def test_snapshot_isolation(self):
        revision = self.frozen()
        recorded = read_frozen_revision(self.source, revision)
        record_batch(self.source, 'shift', 'BW', [TrialUse(60, 'BW', 'W', 'private-alloy-key-27')])
        self.close_source()
        self.open_source()
        self.assertEqual(read_frozen_revision(self.source, revision), recorded)
        self.assertEqual(ledger_rows(online_ledger(self.source, revision)), EXPECTED)
        later = freeze(self.source, 'shift')
        self.assertNotEqual(later, revision)
        self.assertEqual(ledger_rows(online_ledger(self.source, later)), EXPECTED + [[60, 'W', ['L', 'B1', 'shift-register', 5]]])

    def test_unknown_revision(self):
        with self.assertRaises(KeyError):
            freeze(self.source, 'missing-work')
        with self.assertRaises(KeyError):
            online_ledger(self.source, 'F-1')
        self.assertEqual(self.frozen(), 'F-1')
        with self.assertRaises(KeyError):
            online_ledger(self.source, 'F-2')

    def test_init_preserves(self):
        revision = self.frozen()
        record_batch(self.source, 'shift', 'BW', [TrialUse(60, 'BW', 'W', 'private-alloy-key-27')])
        work = self.source.load_working_revision('shift')
        self.source.initialize()
        self.source.initialize()
        self.close_source()
        self.open_source()
        self.assertEqual(self.source.load_working_revision('shift'), work)
        self.assertIn('BW', work.batches)
        self.assertEqual(ledger_rows(online_ledger(self.source, revision)), EXPECTED)
        latest = online_ledger(self.source, freeze(self.source, 'shift'))
        self.assertEqual((latest[-1].trial, latest[-1].reference.reference), ('W', 'L'))
