from receive.store import ReceiptStore, ReceivedPackage
from receive.verify import verify_package


def accept_package(store: ReceiptStore, wire: bytes) -> ReceivedPackage:
    package = verify_package(wire)
    with store.transaction():
        existing = store.find_by_dispatch(package.issuer, package.dispatch_id)
        if existing is not None:
            if existing.wire != package.wire:
                raise ValueError(f'different package for dispatch {package.issuer}/{package.dispatch_id}')
            return existing
        receipt = store.save_receipt(
            package.issuer, package.dispatch_id, package.revision, package.checksum, package.wire,
        )
    return receipt
