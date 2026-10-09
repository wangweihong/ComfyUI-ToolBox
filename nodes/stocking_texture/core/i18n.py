"""Keep core messages independent of the original desktop settings service."""


def tr(text, **params):
    return text.format(**params) if params else text
