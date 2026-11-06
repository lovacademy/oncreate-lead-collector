"""No-network tests for OnCreate's low-cost Claude contact review guardrails."""
import os
import unittest
from unittest.mock import patch, MagicMock
import json

from claude_contact_review import enabled, triage_contact, stats

class ClaudeBudgetTests(unittest.TestCase):
    def test_default_is_no_spend(self):
        with patch.dict(os.environ, {}, clear=True):
            with patch("claude_contact_review.request.urlopen") as call:
                self.assertFalse(enabled())
                self.assertEqual(triage_contact(
                    "Medical Clinic", "https://exampleclinic.com",
                    "contato@exampleclinic.com", "https://exampleclinic.com/contato", "visible"
                ), "skipped")
                call.assert_not_called()

    def test_free_only_never_calls_claude_even_with_key(self):
        settings = {"DISCOVERY_SOURCE_MODE": "FREE_ONLY", "CLAUDE_CONTACT_REVIEW": "true",
                    "ANTHROPIC_API_KEY": "fake-key"}
        with patch.dict(os.environ, settings, clear=True):
            with patch("claude_contact_review.request.urlopen") as call:
                self.assertFalse(enabled())
                self.assertEqual(triage_contact(
                    "Medical Clinic","https://exampleclinic.com","info@exampleclinic.com",
                    "https://exampleclinic.com/contact","visible"), "skipped")
                call.assert_not_called()

    def test_explicit_mode_skips_mailto_and_external_domains(self):
        settings = {"DISCOVERY_SOURCE_MODE":"FREE_PLUS","CLAUDE_CONTACT_REVIEW":"true",
                    "ANTHROPIC_API_KEY":"fake-key"}
        with patch.dict(os.environ, settings, clear=True):
            with patch("claude_contact_review.request.urlopen") as call:
                self.assertTrue(enabled())
                self.assertEqual(triage_contact(
                    "Medical Clinic","https://exampleclinic.com","info@exampleclinic.com",
                    "https://exampleclinic.com/contact","mailto"),"skipped")
                self.assertEqual(triage_contact(
                    "Medical Clinic","https://exampleclinic.com","contato@accounting.example",
                    "https://exampleclinic.com/contact","visible"),"skipped")
                call.assert_not_called()

    def test_model_verdict_is_not_an_email_guess(self):
        settings = {"DISCOVERY_SOURCE_MODE":"FREE_PLUS","CLAUDE_CONTACT_REVIEW":"true",
                    "ANTHROPIC_API_KEY":"fake-key"}
        response = MagicMock()
        response.read.return_value=json.dumps({
            "usage":{"input_tokens":80,"output_tokens":20},
            "content":[{"type":"text","text":'{"verdict":"third_party"}'}]
        }).encode()
        context=MagicMock()
        context.__enter__.return_value=response
        with patch.dict(os.environ,settings,clear=True):
            with patch("claude_contact_review.request.urlopen",return_value=context):
                self.assertEqual(triage_contact(
                    "Medical Clinic","https://exampleclinic.com","info@exampleclinic.com",
                    "https://exampleclinic.com/contact","schema"),"needs_review")

if __name__ == "__main__":
    unittest.main()
