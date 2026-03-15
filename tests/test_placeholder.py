"""Basic smoke tests for AutoDev Framework."""


def test_import_autodev() -> None:
    """Verify the autodev package is importable."""
    import autodev
    assert autodev is not None
