import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass


@dataclass(frozen=True)
class SignedReport:
    report_id: str
    request_id: str
    receipt_id: str
    excluded_batches: tuple[str, ...]
    rows: tuple[dict, ...]
    acknowledgment: str


@dataclass(frozen=True)
class SupplementReport:
    report_id: str
    request_id: str
    receipt_id: str
    arrivals: tuple[tuple[str, str, str, int], ...]
    rows: tuple[dict, ...]
    acknowledgment: str


class ReportStore:
    def __init__(self, path):
        self._db = sqlite3.connect(path)
        self._db.execute('PRAGMA foreign_keys = ON')

    def close(self) -> None:
        self._db.close()

    def initialize(self) -> None:
        self._db.executescript('''
            CREATE TABLE IF NOT EXISTS signed_reports (
                number INTEGER PRIMARY KEY,
                request_id TEXT NOT NULL UNIQUE,
                receipt_id TEXT NOT NULL,
                excluded_batches TEXT NOT NULL,
                rows TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS report_acknowledgments (
                number INTEGER PRIMARY KEY REFERENCES signed_reports (number),
                token TEXT NOT NULL UNIQUE
            );
            CREATE TABLE IF NOT EXISTS supplement_reports (
                number INTEGER PRIMARY KEY,
                request_id TEXT NOT NULL UNIQUE,
                receipt_id TEXT NOT NULL,
                arrivals TEXT NOT NULL,
                rows TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS supplement_acknowledgments (
                number INTEGER PRIMARY KEY REFERENCES supplement_reports (number),
                token TEXT NOT NULL UNIQUE
            );
        ''')

    @contextmanager
    def _transaction(self):
        self._db.execute('BEGIN IMMEDIATE')
        try:
            yield
            self._db.commit()
        except BaseException:
            self._db.rollback()
            raise

    def _read(self, where: str, value: str) -> SignedReport | None:
        result = self._db.execute(f'''
            SELECT r.number, r.request_id, r.receipt_id, r.excluded_batches, r.rows, a.token
            FROM signed_reports AS r JOIN report_acknowledgments AS a ON a.number = r.number
            WHERE {where}
        ''', (value,)).fetchone()
        if result is None:
            return None
        number, request, receipt, excluded, rows, token = result
        return SignedReport(f'Q-{number}', request, receipt, tuple(json.loads(excluded)), tuple(json.loads(rows)), token)

    def save_signed_report(
        self, request_id: str, receipt_id: str, excluded_batches: tuple[str, ...], rows: tuple[dict, ...],
    ) -> SignedReport:
        with self._transaction():
            existing = self._read('r.request_id = ?', request_id)
            if existing is not None:
                if (existing.receipt_id, existing.excluded_batches) != (receipt_id, excluded_batches):
                    raise ValueError(f'report request is already bound: {request_id}')
                return existing
            cursor = self._db.execute('''
                INSERT INTO signed_reports (request_id, receipt_id, excluded_batches, rows)
                VALUES (?, ?, ?, ?)
            ''', (request_id, receipt_id, json.dumps(excluded_batches), json.dumps(rows)))
            number = cursor.lastrowid
            report_id = f'Q-{number}'
            token = f'signed/{report_id}'
            self._db.execute('INSERT INTO report_acknowledgments VALUES (?, ?)', (number, token))
        return SignedReport(report_id, request_id, receipt_id, excluded_batches, rows, token)

    def load_signed_report(self, report_id: str):
        supplement = self._read_supplement("'S-' || s.number = ?", report_id)
        if supplement is not None:
            return supplement
        report = self._read("'Q-' || r.number = ?", report_id)
        if report is None:
            raise KeyError(f'unknown report: {report_id}')
        return report

    def _read_supplement(self, where: str, value: str) -> SupplementReport | None:
        result = self._db.execute(f'''
            SELECT s.number, s.request_id, s.receipt_id, s.arrivals, s.rows, a.token
            FROM supplement_reports AS s
            JOIN supplement_acknowledgments AS a ON a.number = s.number
            WHERE {where}
        ''', (value,)).fetchone()
        if result is None:
            return None
        number, request, receipt, arrivals, rows, token = result
        return SupplementReport(
            f'S-{number}', request, receipt,
            tuple(tuple(entry) for entry in json.loads(arrivals)),
            tuple(json.loads(rows)), token,
        )

    def save_supplement_report(
        self,
        request_id: str,
        receipt_id: str,
        arrivals: tuple[tuple[str, str, str, int], ...],
        rows: tuple[dict, ...],
    ) -> SupplementReport:
        with self._transaction():
            existing = self._read_supplement('s.request_id = ?', request_id)
            if existing is not None:
                if (existing.receipt_id, existing.arrivals) != (receipt_id, arrivals):
                    raise ValueError(f'report request is already bound: {request_id}')
                return existing
            cursor = self._db.execute('''
                INSERT INTO supplement_reports (request_id, receipt_id, arrivals, rows)
                VALUES (?, ?, ?, ?)
            ''', (request_id, receipt_id, json.dumps(arrivals), json.dumps(rows)))
            number = cursor.lastrowid
            report_id = f'S-{number}'
            token = f'signed/{report_id}'
            self._db.execute('INSERT INTO supplement_acknowledgments VALUES (?, ?)', (number, token))
        return SupplementReport(report_id, request_id, receipt_id, arrivals, rows, token)
