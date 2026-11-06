"""Brave Search adapter tests without network or billing."""
import json
import os
import unittest
from unittest.mock import patch
from brave_search import brave_page,available

class BraveProviderTests(unittest.TestCase):
    def test_disabled_without_secret(self):
        with patch.dict(os.environ,{"BRAVE_SEARCH_API_KEY":""}):
            self.assertFalse(available())
            with self.assertRaises(RuntimeError):
                brave_page("cardiologista em Poços de Caldas","BR")

    def test_page_range_and_country_validation(self):
        with patch.dict(os.environ,{"BRAVE_SEARCH_API_KEY":"fake-private-key"}):
            for invalid in (-1,10,100):
                with self.assertRaises(ValueError):
                    brave_page("cardiologist","US",invalid)
            with self.assertRaises(ValueError):
                brave_page("cardiologist","XX",0)

    def test_paged_authorized_api_response(self):
        payload={
            "query":{"original":"clinic","more_results_available":True},
            "web":{"results":[
                {"title":"Clinic Example","url":"https://exampleclinic.com/contact","description":"medical office"},
                {"title":"Bad link","url":"http://invalid.test/","description":"ignored"}
            ]}
        }
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):return False
            def read(self,*args):return json.dumps(payload).encode()
        with patch.dict(os.environ,{"BRAVE_SEARCH_API_KEY":"fake-private-key"}):
            with patch("brave_search.urllib.request.urlopen",return_value=Response()) as mock:
                results,more=brave_page("clinica","BR",9)
                self.assertEqual(len(results),1)
                self.assertTrue(more)
                request=mock.call_args.args[0]
                self.assertIn("offset=9",request.full_url)
                self.assertIn("country=BR",request.full_url)
                self.assertIn("search_lang=pt",request.full_url)

if __name__=="__main__":
    unittest.main()
