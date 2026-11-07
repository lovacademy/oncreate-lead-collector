"""Offline tests for optional official Anthropic web search: strict cost and source checks."""
import json
import unittest
from unittest.mock import MagicMock, patch

from claude_web_discovery import official_candidate, search_results, scan_city

SITE={"type":"web_search_result",
      "title":"Clínica Alfa Campinas | Dermatologia",
      "url":"https://clinicaalfacampinas.com.br/"}
FAKE_RESPONSE={
    "usage":{"input_tokens":415,"output_tokens":120,
             "server_tool_use":{"web_search_requests":1}},
    "content":[
        {"type":"web_search_tool_result","tool_use_id":"srvtoolu_fake",
         "content":[SITE,
          {"type":"web_search_result","title":"Doctoralia Campinas",
           "url":"https://doctoralia.com.br/clinicas/campinas"}]},
        {"type":"text","text":"Clínica Alfa Campinas: https://clinicaalfacampinas.com.br/"}
    ]
}

class FakeHTTPResponse:
    def __init__(self,data):
        self.body=json.dumps(data).encode()
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def read(self,size):return self.body[:size]

class ClaudeWebDiscoveryTests(unittest.TestCase):
    def test_free_mode_never_uses_api_even_with_key(self):
        env={"ANTHROPIC_API_KEY":"fake","CLAUDE_WEB_SEARCH":"true",
             "DISCOVERY_SOURCE_MODE":"FREE_ONLY"}
        with patch.dict("os.environ",env,clear=True), \
             patch("claude_web_discovery.request.urlopen") as call:
            results=search_results("BR","SP","Campinas","dermatologia")
            self.assertEqual(results["search_requests"],0)
            call.assert_not_called()

    def test_requires_explicit_web_search_mode(self):
        env={"ANTHROPIC_API_KEY":"fake","CLAUDE_WEB_SEARCH":"false",
             "DISCOVERY_SOURCE_MODE":"FREE_PLUS"}
        with patch.dict("os.environ",env,clear=True), \
             patch("claude_web_discovery.request.urlopen") as call:
            search_results("BR","SP","Campinas","dermatologia")
            call.assert_not_called()

    def test_rejects_directory_and_mismatched_websites(self):
        self.assertIsNotNone(official_candidate(SITE))
        self.assertIsNone(official_candidate({
            "type":"web_search_result","title":"Clínica Alfa Campinas",
            "url":"https://randombusiness.com.br/"}))
        self.assertIsNone(official_candidate({
            "type":"web_search_result","title":"Doctoralia Campinas",
            "url":"https://doctoralia.com.br/clinicas/campinas"}))
        self.assertIsNone(official_candidate({
            "type":"web_search_result","title":"Clínica Alfa Campinas",
            "url":"http://clinicaalfacampinas.com.br/"}))

    def test_real_search_response_requires_cited_search_results(self):
        env={"ANTHROPIC_API_KEY":"fake","CLAUDE_WEB_SEARCH":"true",
             "DISCOVERY_SOURCE_MODE":"FREE_PLUS"}
        with patch.dict("os.environ",env,clear=True), \
             patch("claude_web_discovery.request.urlopen",
                   return_value=FakeHTTPResponse(FAKE_RESPONSE)):
            result=search_results("BR","SP","Campinas","dermatologia")
        self.assertEqual(result["search_requests"],1)
        self.assertEqual(len(result["sites"]),1)
        self.assertEqual(result["input_tokens"],415)

    def test_only_direct_public_clinic_email_reaches_staging(self):
        with patch("claude_web_discovery.search_results",return_value={
            "sites":[{"name":SITE["title"],"url":SITE["url"],
                      "host":"clinicaalfacampinas.com.br"}],
            "search_requests":1,"input_tokens":200,"output_tokens":100}), \
             patch("claude_web_discovery.public_web_url",
                   return_value="https://clinicaalfacampinas.com.br"), \
             patch("claude_web_discovery.find_public_contact",return_value={
                 "email":"contato@clinicaalfacampinas.com.br",
                 "source_url":"https://clinicaalfacampinas.com.br/contato",
                 "source_type":"mailto","confidence":96,"status":"found"}), \
             patch("claude_web_discovery.triage_contact",return_value="skipped"), \
             patch("claude_web_discovery.persist",return_value=True) as save, \
             patch("claude_web_discovery.time.sleep"):
            result=scan_city("BR","SP","Campinas","dermatologia")
        self.assertEqual(result["saved"],1)
        self.assertEqual(result["search_requests"],1)
        self.assertEqual(save.call_args.args[0]["email_source_type"],"mailto")

if __name__ == "__main__":
    unittest.main()
