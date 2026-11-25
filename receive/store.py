import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass


@dataclass(frozen=True)
class ReceivedPackage:
    receipt_id: str
    issuer: str
    dispatch_id: str
    revision: str
    checksum: str
    wire: bytes
    acknowledgment: str


class ReceiptStore:
    def __init__(self, path):
        self._db = sqlite3.connect(path)

    def close(self) -> None:
        self._db.close()

    def initialize(self) -> None:
        self._db.executescript('''
            CREATE TABLE IF NOT EXISTS received_packages (
                number INTEGER PRIMARY KEY,
                issuer TEXT NOT NULL,
                dispatch_id TEXT NOT NULL,
                revision TEXT NOT NULL,
                checksum TEXT NOT NULL,
                wire BLOB NOT NULL,
                acknowledgment TEXT NOT NULL,
                UNIQUE (issuer, dispatch_id)
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

    def _read(self, where: str, parameters: tuple) -> ReceivedPackage | None:
        row = self._db.execute(f'''
            SELECT number, issuer, dispatch_id, revision, checksum, wire, acknowledgment
            FROM received_packages WHERE {where}
        ''', parameters).fetchone()
        if row is None:
            return None
        number, *fields = row
        return ReceivedPackage(f'I-{number}', *fields)

    def find_by_dispatch(self, issuer: str, dispatch_id: str) -> ReceivedPackage | None:
        return self._read('issuer = ? AND dispatch_id = ?', (issuer, dispatch_id))

    def save_receipt(
        self, issuer: str, dispatch_id: str, revision: str, checksum: str, wire: bytes,
    ) -> ReceivedPackage:
        number, = self._db.execute('SELECT COALESCE(MAX(number), 0) + 1 FROM received_packages').fetchone()
        receipt = ReceivedPackage(
            f'I-{number}', issuer, dispatch_id, revision, checksum, wire, f'received/I-{number}',
        )
        self._db.execute('INSERT INTO received_packages VALUES (?, ?, ?, ?, ?, ?, ?)', (
            number, issuer, dispatch_id, revision, checksum, wire, receipt.acknowledgment,
        ))
        return receipt

    def load_receipt(self, receipt_id: str) -> ReceivedPackage:
        receipt = self._read("'I-' || number = ?", (receipt_id,))
        if receipt is None:
            raise KeyError(f'unknown receipt: {receipt_id}')
        return receipt
