from receive.store import ReceiptStore, ReceivedPackage
from receive.verify import VerifiedPackage, verify_package


def get_received(store: ReceiptStore, receipt_id: str) -> ReceivedPackage:
    return store.load_receipt(receipt_id)


def load_verified_receipt(store: ReceiptStore, receipt_id: str) -> VerifiedPackage:
    receipt = get_received(store, receipt_id)
    package = verify_package(receipt.wire)
    recorded_identity = (receipt.issuer, receipt.dispatch_id, receipt.revision, receipt.checksum)
    package_identity = (package.issuer, package.dispatch_id, package.revision, package.checksum)
    if recorded_identity != package_identity:
        raise ValueError(f'package does not match the recorded receipt: {receipt_id}')
    return package
