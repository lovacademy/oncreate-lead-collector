"""SEC EIN checks must not fabricate emails, and do not use paid providers."""
import json
import unittest
from unittest.mock import patch
from ein_enrichment import published_ids,verify_sec_ein

class EINTests(unittest.TestCase):
    def test_published_identifiers(self):
        eins,ciks=published_ids("Our EIN: 12-3456789 and SEC CIK: 0000987654")
        self.assertIn("123456789",eins)
        self.assertIn(987654,ciks)

    def test_requires_known_sec_filer_and_exact_match(self):
        class Fake:
            def __enter__(self):return self
            def __exit__(self,*args):return False
            def read(self,*args):return json.dumps({
                "cik":987654,"ein":"123456789","name":"Demo Healthcare Inc."
            }).encode()
        with patch("ein_enrichment.request.urlopen",return_value=Fake()):
            match=verify_sec_ein(987654,"12-3456789")
            self.assertEqual(match["source_type"],"sec_verified")
            self.assertIsNone(verify_sec_ein(987654,"98-7654321"))
        self.assertIsNone(verify_sec_ein("unknown","12-3456789"))

if __name__=="__main__":
    unittest.main()
