import argparse
import json
import sqlite3
from contextlib import ExitStack, closing
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from assign.replay import replay_assignments
from issue.archive import DispatchArchive
from issue.dispatch import issue_package, reissue_package
from issue.package import decode_envelope, package_checksum
from receive.register import accept_package
from receive.store import ReceiptStore
from record.batches import record_batch
from record.events import ReferenceArrival, event_from_data
from record.origins import ReferenceOrigin
from record.revisions import freeze, read_frozen_revision
from record.store import RecordingStore
from review.history import get_report
from review.request import AuditRequest, audit_package
from review.store import ReportStore


def open_store(stack, factory, *args):
    store = stack.enter_context(closing(factory(*args)))
    store.initialize()
    return store


def load_freezes(source, data):
    revisions = {}
    for label in ("A", "B"):
        batches = list(data["common_batches"])
        if label == "A":
            batches.append(data["a_only"])
        for batch in batches:
            events = [event_from_data(row) for row in batch["events"]]
            record_batch(source, label, batch["batch"], events)
        revisions[label] = freeze(source, label)
    return revisions


def chosen_names(report):
    return [row["reference"]["reference"] if row["reference"] else None for row in report.rows]


def effective_arrivals(data, arrivals):
    rank = {gate: index for index, (gate, _) in enumerate(data["gates"])}
    return tuple(sorted((tuple(row) for row in arrivals), key=lambda row: rank[row[0]]))


def source_oracle(data, events, arrivals):
    # Replay the complete source fixture with concrete extra references.
    stride = len(arrivals) + 1
    cutoffs = dict(data["gates"])
    augmented = [replace(event, position=event.position * stride) for event in events]
    for index, (gate, name, document, line) in enumerate(effective_arrivals(data, arrivals), 1):
        origin = ReferenceOrigin("LATE", document, line)
        position = cutoffs[gate] * stride + index
        augmented.append(ReferenceArrival(position, "LATE", name, data["compatibility"], "17.500", "MPa", origin))
    return [row.reference.reference if row.reference else None
            for row in replay_assignments(augmented) if row.trial in data["trials"]]


def control(data):
    with ExitStack() as isolated:
        receipts = open_store(isolated, ReceiptStore, ":memory:")
        reports = open_store(isolated, ReportStore, ":memory:")
        frozen, received = {}, {}
        with ExitStack() as station:
            source = open_store(station, RecordingStore, ":memory:")
            archive = open_store(station, DispatchArchive, ":memory:", "chengwan")
            for label, revision in load_freezes(source, data).items():
                frozen[label] = read_frozen_revision(source, revision).events
                wire = issue_package(source, archive, revision, data["trials"])
                envelope = decode_envelope(wire)
                assert reissue_package(archive, envelope["dispatch_id"]) == wire
                assert 25 in {row["position"] for row in envelope["body"]["uses"]}
                received[label] = accept_package(receipts, wire)
        for label, receipt in received.items():
            report = audit_package(receipts, reports, AuditRequest(receipt.receipt_id, "v1-" + label))
            assert chosen_names(report) == ["R2", None]
            assert get_report(reports, report.report_id) == report
            for case in data["cases"]:
                truth = source_oracle(data, frozen[label], case["arrivals"])
                assert truth == case["expected"][label], (label, case["name"], truth)
                print(label, case["name"], json.dumps(truth))


def rejects(action, error=ValueError):
    try:
        action()
    except error:
        return
    raise AssertionError("invalid operation succeeded")


def wrong_body(envelope):
    payload = {name: value for name, value in envelope.items() if name != "checksum"}
    payload["body"] = None
    return json.dumps({**payload, "checksum": package_checksum(payload)}).encode("utf-8")


def check_row_sources(data, report, arrivals):
    expected = {
        ("station", "R1"): {"batch": "B1", "document": "shift-register", "line": 1},
        ("station", "R2"): {"batch": "B2", "document": "shift-register", "line": 2},
    }
    arrival_gates = {}
    for gate, name, document, line in arrivals:
        expected["arrival", name] = {"document": document, "line": line}
        arrival_gates[name] = gate
    assert [(row["position"], row["trial"]) for row in report.rows] == [(30, "V"), (40, "W")]
    assert report.arrivals == effective_arrivals(data, arrivals)
    for row in report.rows:
        ref = row["reference"]
        if ref is not None:
            assert ref["origin"] == expected[ref["source"], ref["reference"]]
            if ref["source"] == "arrival":
                assert ref["gate"] == arrival_gates[ref["reference"]]


def check_commit_failure(reports, submit, arrivals):
    def authorize(action, name, *_):
        if action == sqlite3.SQLITE_TRANSACTION and name == "COMMIT":
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    reports._db.set_authorizer(authorize)
    try:
        rejects(lambda: submit("A", "commit-retry", arrivals), sqlite3.Error)
    finally:
        reports._db.set_authorizer(None)
    assert chosen_names(submit("A", "commit-retry", [])) == ["R2", None]


def supplement(data, demo):
    from issue.dispatch import issue_supplement
    from review.request import audit_supplement

    with TemporaryDirectory(prefix="reference-supplement-") as temporary:
        source_path = Path(temporary) / "station.sqlite3"
        offline_path = Path(temporary) / "partner.sqlite3"
        signed = {}
        with ExitStack() as isolated:
            receipts = open_store(isolated, ReceiptStore, offline_path)
            reports = open_store(isolated, ReportStore, offline_path)
            selected = {}
            with ExitStack() as station:
                source = open_store(station, RecordingStore, source_path)
                archive = open_store(station, DispatchArchive, source_path, "chengwan")
                revisions = load_freezes(source, data)
                legacy_wire = issue_package(source, archive, revisions["A"], data["trials"])
                legacy = accept_package(receipts, legacy_wire)
                for label, revision in revisions.items():
                    wire = issue_supplement(source, archive, revision, data["trials"], data["compatibility"], data["gates"])
                    envelope = decode_envelope(wire)
                    assert envelope["version"] == 2 and envelope["revision"] == revision
                    assert reissue_package(archive, envelope["dispatch_id"]) == wire
                    public = json.dumps(envelope["body"])
                    for private in ("bench-only-early", "bench-only-middle", "private-alloy-key-27",
                                    "unrelated-register", "8843.937100", "9342.281100", "\"BH\"", "\"BE\""):
                        assert private not in public, private
                    rejects(lambda: accept_package(receipts, wire[:-1]))
                    rejects(lambda: accept_package(receipts, wrong_body(envelope)))
                    selected[label] = accept_package(receipts, wire)
                    assert accept_package(receipts, wire) == selected[label]
                    rejects(lambda: accept_package(receipts, b" " + wire))
            source_path.rename(source_path.with_suffix(".offline"))

            def submit(label, request, arrivals):
                return audit_supplement(receipts, reports, selected[label].receipt_id, request, arrivals)

            cases = {entry["name"]: entry for entry in data["cases"]}
            for name in (["pre-X", "late-X"] if demo else cases):
                case = cases[name]
                for label in selected:
                    request = label + "-" + name
                    arrivals = case["arrivals"]
                    report = submit(label, request, arrivals)
                    assert report.receipt_id == selected[label].receipt_id and report.request_id == request
                    assert report.acknowledgment and chosen_names(report) == case["expected"][label]
                    check_row_sources(data, report, arrivals)
                    assert submit(label, request, arrivals) == report
                    signed[request] = report
            if not demo:
                x = cases["pre-X"]["arrivals"]
                rejects(lambda: submit("A", "unknown-gate", [["unknown", "X", "partner-register", 1]]))
                rejects(lambda: submit("A", "duplicate", x + [["after-V", "X", "partner-register", 1]]))
                rejects(lambda: submit("A", "A-pre-X", []))
                rejects(lambda: submit("B", "A-pre-X", x))
                rejects(lambda: submit("A", "A-pre-XYZ", list(reversed(cases["pre-XYZ"]["arrivals"]))))
                assert submit("A", "A-both", list(reversed(cases["both"]["arrivals"]))) == signed["A-both"]
                rejects(lambda: audit_supplement(receipts, reports, legacy.receipt_id, "wrong-mode", []))
                rejects(lambda: audit_package(receipts, reports, AuditRequest(selected["A"].receipt_id, "wrong-mode")))
                check_commit_failure(reports, submit, cases["pre-XYZ"]["arrivals"])
                old = audit_package(receipts, reports, AuditRequest(legacy.receipt_id, "v1-withdrawal", ["BH"]))
                assert chosen_names(old) == ["R1", "R2"]
                signed[old.request_id] = old
        with closing(ReportStore(offline_path)) as reopened:
            reopened.initialize()
            for request, report in signed.items():
                readback = get_report(reopened, report.report_id)
                assert readback == report
                if demo:
                    print(json.dumps({"request": request, "report": readback.report_id,
                                      "receipt": readback.receipt_id, "arrivals": readback.arrivals,
                                      "rows": readback.rows, "acknowledgment": readback.acknowledgment}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("control", "verify", "demo"))
    mode = parser.parse_args().mode
    data = json.loads((Path(__file__).resolve().parent / "samples" / "supplement.json").read_text(encoding="utf-8"))
    if mode == "control":
        control(data)
        return
    if mode == "verify":
        from check_project import main as original_regression
        if original_regression():
            raise SystemExit(1)
    supplement(data, demo=mode == "demo")


if __name__ == "__main__":
    main()
