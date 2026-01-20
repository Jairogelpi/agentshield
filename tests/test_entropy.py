import asyncio
import unittest

from app.services.pii_guard import advanced_redact_pii, pii_guard


class TestEntropyGuard(unittest.TestCase):
    def test_low_entropy_pass(self):
        """Test that normal text is NOT redacted."""
        text = "Hello world this is a normal sentence."
        scanned = pii_guard._entropy_scan(text)
        self.assertEqual(text, scanned)

    def test_high_entropy_detection(self):
        """Test that high entropy secrets are blocked."""
        # A high entropy string like an API key
        secret = "sk-proj-89823982398293d9823_ABS"
        text = f"My secret key is {secret}"
        scanned = pii_guard._entropy_scan(text)

        print(f"Original: {text}")
        print(f"Scanned:  {scanned}")

        self.assertIn("<SECRET_REDACTED>", scanned)
        self.assertNotIn(secret, scanned)

    def test_mixed_content(self):
        """Test a mix of normal text and secrets."""
        text = "Here is a password: 7F9a#99!xL and here is a dog."
        scanned = pii_guard._entropy_scan(text)

        self.assertIn("Here is a password:", scanned)
        self.assertIn("and here is a dog.", scanned)
        self.assertIn("<SECRET_REDACTED>", scanned)


if __name__ == "__main__":
    unittest.main()
