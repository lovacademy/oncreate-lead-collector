import unittest
from unittest.mock import patch
from daily_lead_discovery import (
    eligible_domain, public_web_url, MailtoParser, nppes_records, possible_official_site,
    MAX_LEADS, DENIED, email_score, find_public_contact,nppes_physicians
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

    def test_published_email_evidence_from_visible_text_and_schema(self):
        parser=MailtoParser()
        parser.feed("""<html><body><div>office@clinic.org</div>
          <script type="application/ld+json">{"email":"info@clinic.org"}</script>
          <a href="mailto:contact@clinic.org">Email us</a>
          <script>var fake='admin@evil.org';</script>
          <div>john.doe@clinic.org</div>
        </body></html>""")
        self.assertIn(("info@clinic.org","schema"),parser.evidence)
        self.assertIn(("office@clinic.org","visible"),parser.evidence)
        self.assertIn(("contact@clinic.org","mailto"),parser.evidence)
        self.assertNotIn("admin@evil.org",parser.emails)
        self.assertNotIn("john.doe@clinic.org",parser.emails)

    def test_mailto_contact_page_has_higher_source_confidence(self):
        home=email_score("info@clinic.org","mailto","https://clinic.org/","https://clinic.org")
        contact=email_score("info@clinic.org","mailto","https://clinic.org/contact","https://clinic.org")
        other=email_score("info@gmail.com","mailto","https://clinic.org/contact","https://clinic.org")
        self.assertGreaterEqual(contact,90)
        self.assertGreater(contact,home)
        self.assertLess(other,contact)

    def test_scans_homepage_and_official_contact_page_without_network(self):
        class FakeResponse:
            def __init__(self,url,body,kind):
                self.url,self.content,self.headers=url,body.encode(),{"Content-Type":kind}
            def __enter__(self):return self
            def __exit__(self,*args):return False
            def read(self,size=999999):return self.content[:size]
            def geturl(self):return self.url
        class FakeOpener:
            def open(self,req,timeout=9):
                u=req.full_url
                if u.endswith("/robots.txt"):
                    return FakeResponse(u,"User-agent: *\nAllow: /\n","text/plain")
                if u.endswith("/contact"):
                    return FakeResponse(u,'<a href="mailto:info@clinic.org">Email us</a>',"text/html")
                return FakeResponse(u,'<a href="/contact">Contact us</a>',"text/html")
        with patch("daily_lead_discovery.public_web_url",side_effect=lambda url:url),\
             patch("daily_lead_discovery.request.build_opener",return_value=FakeOpener()),\
             patch("daily_lead_discovery.time.sleep"):
            result=find_public_contact("https://clinic.org")
        self.assertEqual(result["email"],"info@clinic.org")
        self.assertEqual(result["source_url"],"https://clinic.org/contact")
        self.assertGreater(result["confidence"],90)
        self.assertEqual(result["status"],"found")
        self.assertLessEqual(result["pages_scanned"],7)

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

    def test_collects_physicians_not_nurses_and_ignores_mailing_addresses(self):
        fixture={"results":[
            {"number":1234567890,"basic":{"first_name":"JANE","last_name":"SMITH","credential":"M.D.","status":"A"},
             "addresses":[{"address_purpose":"LOCATION","city":"Boston","state":"MA"}],
             "taxonomies":[{"code":"207N00000X","desc":"Dermatology","primary":True}]},
            {"number":2222222222,"basic":{"first_name":"ANN","last_name":"RN"},
             "addresses":[{"address_purpose":"LOCATION","city":"Boston","state":"MA"}],
             "taxonomies":[{"code":"363L00000X","desc":"Nurse Practitioner"}]},
            {"number":3333333333,"basic":{"first_name":"JOHN","last_name":"MILLER"},
             "addresses":[{"address_purpose":"MAILING","city":"Residential","state":"MA"}],
             "taxonomies":[{"code":"207N00000X","desc":"Dermatology"}]}
        ]}
        with patch("daily_lead_discovery.fetch_json",return_value=fixture):
            rows=list(nppes_physicians("MA","dermatology",20))
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]["company_name"],"Dr. Jane Smith")
        self.assertEqual(rows[0]["city"],"Boston")
        self.assertEqual(rows[0]["business_email"],"")
        self.assertNotIn("phone",rows[0])

    def test_official_domain_needs_name_match(self):
        with patch("daily_lead_discovery.public_web_url",return_value="https://acmedental.example"):
            self.assertEqual(possible_official_site("Acme Dental Group",
                {"title":"Acme Dental - Professional Care","url":"https://acmedental.example"}),
                "https://acmedental.example")
            self.assertEqual(possible_official_site("Acme Dental Group",
                {"title":"Other Dental Reviews","url":"https://other.example"}),"")
            self.assertEqual(possible_official_site("Medical Group",
                {"title":"Medical Group","url":"https://other.example"}),"")

    def test_prevents_third_party_directory_and_chain_misidentification(self):
        with patch("daily_lead_discovery.public_web_url", side_effect=lambda url:url):
            self.assertEqual(possible_official_site(
                "ADVANCED HOME CARE SPECIALIST, INC",
                {"title":"Advanced Home Care Specialist Profile",
                 "url":"https://profiles.health.ny.gov/practice"}),"")
            self.assertEqual(possible_official_site(
                "18TH AVE CARE LLC",
                {"title":"Health Care | CityMD",
                 "url":"https://www.citymd.com"}),"")
            self.assertEqual(possible_official_site(
                "Mountain Valley Dermatology LLC",
                {"title":"Mountain Valley Dermatology - Appointments",
                 "url":"https://mountainvalleyderm.com/contact"}),
                "https://mountainvalleyderm.com/contact")

    def test_daily_bound(self):
        self.assertTrue(1<=MAX_LEADS<=250)

if __name__ == "__main__":
    unittest.main()
