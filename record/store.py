import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass

from record.events import Event, event_from_data, event_to_data, order_events


@dataclass(frozen=True)
class WorkingRevision:
    working_revision: str
    batches: tuple[str, ...]
    events: tuple[Event, ...]


class RecordingStore:
    def __init__(self, path):
        self._db = sqlite3.connect(path)
        self._db.execute('PRAGMA foreign_keys = ON')

    def close(self) -> None:
        self._db.close()

    def initialize(self) -> None:
        self._db.executescript('''
            CREATE TABLE IF NOT EXISTS record_batches (
                work_id TEXT NOT NULL,
                batch TEXT NOT NULL,
                PRIMARY KEY (work_id, batch)
            );
            CREATE TABLE IF NOT EXISTS record_events (
                work_id TEXT NOT NULL,
                position TEXT NOT NULL,
                batch TEXT NOT NULL,
                payload TEXT NOT NULL,
                PRIMARY KEY (work_id, position),
                FOREIGN KEY (work_id, batch) REFERENCES record_batches (work_id, batch)
            );
            CREATE TABLE IF NOT EXISTS frozen_revisions (
                number INTEGER PRIMARY KEY,
                work_id TEXT NOT NULL,
                batches TEXT NOT NULL,
                events TEXT NOT NULL
            );
        ''')

    @contextmanager
    def transaction(self):
        self._db.execute('BEGIN IMMEDIATE')
        try:
            yield
            self._db.commit()
        except BaseException:
            self._db.rollback()
            raise

    def load_working_revision(self, working_revision: str) -> WorkingRevision:
        rows = self._db.execute('''
            SELECT b.batch, e.payload
            FROM record_batches AS b
            LEFT JOIN record_events AS e ON e.work_id = b.work_id AND e.batch = b.batch
            WHERE b.work_id = ?
        ''', (working_revision,)).fetchall()
        if not rows:
            raise KeyError(f'unknown working revision: {working_revision}')
        batches = tuple(sorted({batch for batch, _ in rows}))
        events = order_events(event_from_data(json.loads(payload)) for _, payload in rows if payload is not None)
        return WorkingRevision(working_revision, batches, events)

    def save_batch(self, working_revision: str, batch: str, events: tuple[Event, ...]) -> None:
        self._db.execute('INSERT INTO record_batches VALUES (?, ?)', (working_revision, batch))
        self._db.executemany('INSERT INTO record_events VALUES (?, ?, ?, ?)', (
            (working_revision, str(event.position), batch, json.dumps(event_to_data(event)))
            for event in events
        ))

    def save_frozen_revision(self, current: WorkingRevision) -> str:
        cursor = self._db.execute('''
            INSERT INTO frozen_revisions (work_id, batches, events) VALUES (?, ?, ?)
        ''', (
            current.working_revision,
            json.dumps(current.batches),
            json.dumps([event_to_data(event) for event in current.events]),
        ))
        return f'F-{cursor.lastrowid}'

    def load_frozen_revision(self, revision: str) -> WorkingRevision:
        row = self._db.execute('''
            SELECT work_id, batches, events FROM frozen_revisions WHERE 'F-' || number = ?
        ''', (revision,)).fetchone()
        if row is None:
            raise KeyError(f'unknown frozen revision: {revision}')
        work_id, batches, events = row
        return WorkingRevision(
            work_id,
            tuple(json.loads(batches)),
            tuple(event_from_data(event) for event in json.loads(events)),
        )
