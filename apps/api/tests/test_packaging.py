"""Tests for app.services.ml.packaging — export/import ZIP (requires TensorFlow).

All tests are skipped if TensorFlow is not installed.
"""

from __future__ import annotations

import pytest

tf = pytest.importorskip("tensorflow", reason="TensorFlow not installed — skipping packaging tests")


class TestPackaging:
    """Placeholder: these tests require TensorFlow to create model artifacts."""

    @pytest.mark.skip(reason="TensorFlow required for full packaging test")
    def test_export_import_roundtrip(self):
        pass
