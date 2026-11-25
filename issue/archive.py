import json
import sqlite3
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass


@dataclass(frozen=True)
class DispatchRecord:
    dispatch_id: str
    revision: str
    selection: tuple[str, ...]
    wire: bytes


class DispatchArchive:
    def __init__(self, path, issuer: str):
        if not isinstance(issuer, str) or not issuer or issuer != issuer.strip() or not issuer.isprintable():
            raise ValueError('invalid dispatch issuer')
        self._issuer = issuer
        self._db = sqlite3.connect(path)

    @property
    def issuer(self) -> str:
        return self._issuer

    def close(self) -> None:
        self._db.close()

    @contextmanager
    def _transaction(self):
        self._db.execute('BEGIN IMMEDIATE')
        try:
            yield
            self._db.commit()
        except BaseException:
            self._db.rollback()
            raise

    def initialize(self) -> None:
        self._db.executescript('''
            CREATE TABLE IF NOT EXISTS dispatch_issuer (
                singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                issuer TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS dispatch_archive (
                number INTEGER PRIMARY KEY,
                revision TEXT NOT NULL,
                selection TEXT NOT NULL,
                wire BLOB NOT NULL
            );
        ''')
        with self._transaction():
            self._db.execute('''
                INSERT INTO dispatch_issuer VALUES (1, ?) ON CONFLICT (singleton) DO NOTHING
            ''', (self.issuer,))
            existing, = self._db.execute('SELECT issuer FROM dispatch_issuer WHERE singleton = 1').fetchone()
            if existing != self.issuer:
                raise ValueError(f'archive is already bound to issuer {existing!r}')

    def save_dispatch(
        self, revision: str, selection: tuple[str, ...], seal: Callable[[str], bytes],
    ) -> DispatchRecord:
        with self._transaction():
            number, = self._db.execute('SELECT COALESCE(MAX(number), 0) + 1 FROM dispatch_archive').fetchone()
            dispatch_id = f'D-{number}'
            wire = seal(dispatch_id)
            self._db.execute('INSERT INTO dispatch_archive VALUES (?, ?, ?, ?)', (
                number, revision, json.dumps(selection), wire,
            ))
        return DispatchRecord(dispatch_id, revision, selection, wire)

    def load_dispatch(self, dispatch_id: str) -> DispatchRecord:
        row = self._db.execute('''
            SELECT revision, selection, wire FROM dispatch_archive WHERE 'D-' || number = ?
        ''', (dispatch_id,)).fetchone()
        if row is None:
            raise KeyError(f'unknown dispatch: {dispatch_id}')
        revision, selection, wire = row
        return DispatchRecord(dispatch_id, revision, tuple(json.loads(selection)), wire)
