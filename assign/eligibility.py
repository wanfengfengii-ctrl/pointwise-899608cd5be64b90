from record.events import ReferenceArrival, TrialUse


def is_compatible(trial: TrialUse, reference: ReferenceArrival) -> bool:
    return trial.compatibility == reference.compatibility
