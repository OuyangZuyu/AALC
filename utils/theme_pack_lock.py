"""Per-selection weight copies. Never mutate or save user weight tables."""

LOCKED_WEIGHT = 10
OTHER_WEIGHT = -10


def temporary_theme_pack_weights(weights, keywords):
    wanted = set(keywords)
    return {key: LOCKED_WEIGHT if key in wanted else OTHER_WEIGHT for key in weights}


def target_data(target):
    return target.model_dump() if hasattr(target, "model_dump") else target
