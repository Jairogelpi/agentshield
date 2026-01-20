"""
Tests for Receipt Manager - Forensic Blockchain & Hash Chaining.
"""

import pytest

from app.services.receipt_manager import ReceiptManager, create_forensic_receipt, receipt_manager


class TestReceiptManager:
    """Tests for ReceiptManager class."""

    def test_singleton_exists(self):
        """Receipt manager singleton should exist."""
        assert receipt_manager is not None

    def test_instantiation(self):
        """ReceiptManager should instantiate."""
        manager = ReceiptManager()
        assert manager is not None

    def test_has_create_method(self):
        """Should have create_and_sign_receipt method."""
        manager = ReceiptManager()
        assert hasattr(manager, "create_and_sign_receipt")
        assert callable(manager.create_and_sign_receipt)


class TestForensicReceipt:
    """Tests for forensic receipt creation."""

    def test_function_callable(self):
        """create_forensic_receipt should be callable."""
        assert callable(create_forensic_receipt)

    def test_function_is_async(self):
        """create_forensic_receipt should be async."""
        import asyncio

        assert asyncio.iscoroutinefunction(create_forensic_receipt)
