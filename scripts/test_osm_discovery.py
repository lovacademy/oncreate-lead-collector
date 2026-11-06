"""Free healthcare map harvesting tests: no live Overpass calls."""
import unittest
from unittest.mock import patch

from osm_discovery import overpass_query,medical_candidates,scan_city

class OSMDiscoveryTests(unittest.TestCase):
    def test_bounded_query_covers_healthcare_services(self):
        query=overpass_query(-21.79,-46.57)
        self.assertIn('["healthcare"]',query)
        self.assertIn('["amenity"~',query)
        self.assertIn("around:5500",query)
        with self.assertRaises(ValueError):overpass_query(200,300)

    def test_only_official_public_websites_in_candidate_list(self):
        rows=[
            {"type":"node","id":5,"tags":{"name":"Clínica Alfa","amenity":"doctors",
                "website":"https://alfa.example.org"}},
            {"type":"way","id":9,"tags":{"name":"Clínica sem website","amenity":"clinic"}},
            {"type":"node","id":6,"tags":{"name":"Clínica Alfa","website":"https://alfa.example.org"}},
            {"type":"node","id":7,"tags":{"name":"Clínica Beta","website":"https://instagram.com/doctor"}},
        ]
        with patch("osm_discovery.public_web_url",side_effect=lambda x:x if
                    x.startswith("https://alfa.example.org") else None):
            leads=medical_candidates(rows)
        self.assertEqual(len(leads),1)
        self.assertEqual(leads[0]["name"],"Clínica Alfa")
        self.assertEqual(leads[0]["source_url"],"https://www.openstreetmap.org/node/5")

    def test_no_inbox_lead_without_site_evidence(self):
        row={"type":"node","id":15,"tags":{"name":"Centro Médico Beta",
             "website":"https://beta.example.org","contact:email":"contato@beta.example.org"}}
        with patch("osm_discovery.overpass_results",return_value=[row]), \
             patch("osm_discovery.public_web_url",return_value="https://beta.example.org"), \
             patch("osm_discovery.find_public_contact",return_value={
                 "email":"","confidence":0,"status":"not_found"}), \
             patch("osm_discovery.persist") as save:
            result=scan_city("BR","MG","Poços de Caldas",-21.79,-46.57)
            self.assertEqual(result["saved"],0)
            self.assertEqual(result["sites_checked"],1)
            save.assert_not_called()

    def test_verified_mail_is_saved_with_osm_attribution(self):
        row={"type":"node","id":44,"tags":{"name":"Consultório São Lucas",
             "website":"https://clinicasaolucas.example.org","healthcare":"doctor"}}
        evidence={"email":"contato@clinicasaolucas.example.org",
                  "confidence":90,"source_url":"https://clinicasaolucas.example.org/contato",
                  "source_type":"mailto","status":"found",
                  "pages_scanned":2,"last_crawled_at":"2026-11-06T15:00:00Z"}
        with patch("osm_discovery.overpass_results",return_value=[row]), \
             patch("osm_discovery.public_web_url",return_value="https://clinicasaolucas.example.org"), \
             patch("osm_discovery.find_public_contact",return_value=evidence), \
             patch("osm_discovery.persist",return_value=True) as save, \
             patch("osm_discovery.time.sleep"):
            result=scan_city("BR","MG","Poços de Caldas",-21.79,-46.57)
        self.assertEqual(result["saved"],1)
        data=save.call_args.args[0]
        self.assertEqual(data["email_source_type"],"mailto")
        self.assertIn("OpenStreetMap",data["note"])
        self.assertEqual(data["source_name"],"website")

if __name__=="__main__":
    unittest.main()
