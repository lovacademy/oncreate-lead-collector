import unittest
from unittest.mock import patch
from daily_lead_discovery import (
    eligible_domain, public_web_url, MailtoParser, nppes_records, possible_official_site,
    MAX_LEADS, DENIED
)

class DiscoveryTests(unittest.TestCase):
    def test_forbidden_directory_sources(self):
        for domain in DENIED:
            self.assertFalse(eligible_domain(domain))
            self.assertFalse(eligible_domain("www." + domain))
        self.assertTrue(eligible_domain("sample-clinic.example"))

    def test_public_only(self):
        for address in ("http://example.org", "https://localhost", "https://127.0.0.1",
                        "https://10.0.0.3", "https://www.zocdoc.com",
                        "https://user:password@clinic.org", "https://clinic.org:8090"):
            self.assertIsNone(public_web_url(address), address)
        with patch("daily_lead_discovery.socket.getaddrinfo", return_value=[
            (0,0,0,"",("192.168.1.2",443))]):
            self.assertIsNone(public_web_url("https://clinic.org"))
        with patch("daily_lead_discovery.socket.getaddrinfo", return_value=[
            (0,0,0,"",("8.8.8.8",443))]):
            self.assertEqual(public_web_url("https://clinic.org/about"),"https://clinic.org")

    def test_only_role_based_mailto(self):
        parser = MailtoParser()
        parser.feed("""<a href="mailto:info@clinic.org">Contact</a>
         <a href="mailto:doctor.personal@clinic.org">Private</a>
         <a href="mailto:office@clinic.org?subject=Hi">Office</a>""")
        self.assertEqual(parser.emails, {"info@clinic.org","office@clinic.org"})

    def test_nppes_public_organization_not_person(self):
        fixture={"results":[
            {"number":1234567890,"basic":{"organization_name":"Test Clinic LLC"},
             "addresses":[{"address_purpose":"LOCATION","city":"Albany","state":"NY"}]},
            {"number":2222222222,"basic":{"first_name":"John","last_name":"Smith"}}
        ]}
        with patch("daily_lead_discovery.fetch_json", return_value=fixture):
            found=list(nppes_records("NY","dental",20))
        self.assertEqual(len(found),1)
        self.assertEqual(found[0]["source_key"],"1234567890")
        self.assertEqual(found[0]["business_email"],"")
        self.assertEqual(found[0]["city"],"Albany")

    def test_official_domain_needs_name_match(self):
        with patch("daily_lead_discovery.public_web_url",return_value="https://acmedental.example"):
            self.assertEqual(possible_official_site("Acme Dental Group",
                {"title":"Acme Dental - Professional Care","url":"https://acmedental.example"}),
                "https://acmedental.example")
            self.assertEqual(possible_official_site("Acme Dental Group",
                {"title":"Other Dental Reviews","url":"https://other.example"}),"")
            self.assertEqual(possible_official_site("Medical Group",
                {"title":"Medical Group","url":"https://other.example"}),"")

    def test_daily_bound(self):
        self.assertTrue(1<=MAX_LEADS<=250)

if __name__ == "__main__":
    unittest.main()
