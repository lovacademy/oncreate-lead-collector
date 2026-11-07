"""Deterministic tests: site quality and phone-only separation, no live web calls."""
import unittest
from unittest.mock import patch

from site_research import (
    PublicPage,phone_number,website_issues,opportunity_score,research
)

SITE={
    "id":"00000000-0000-4000-8000-000000000001",
    "country_code":"BR","state":"MG","city":"Belo Horizonte",
    "company_name":"Clínica Teste BH","website":"https://clinicateste.com.br",
    "website_domain":"clinicateste.com.br","specialty":"Endocrinologia",
    "source_url":"https://clinicateste.com.br/"
}
LANDING={
    "site":"https://clinicateste.com.br",
    "pages":["https://clinicateste.com.br/","https://clinicateste.com.br/contato"],
    "issues":["missing_viewport","missing_description","missing_h1"],
    "score":80,"site_title":"Clínica Teste BH",
    "site_description":"","site_h1":"",
    "phone":"+553133334444",
    "phone_source_url":"https://clinicateste.com.br/contato",
    "cnpjs":[]
}
NO_MAIL={"email":"","source_url":"","confidence":0,"source_type":"",
         "status":"not_found","pages_scanned":2}
GOOD_MAIL={"email":"contato@clinicateste.com.br",
           "source_url":"https://clinicateste.com.br/contato",
           "source_type":"mailto","confidence":95,"status":"found","pages_scanned":2}

class SiteResearchTests(unittest.TestCase):
    def test_phone_normalizes_business_numbers(self):
        self.assertEqual(phone_number("(31) 3333-4444","BR"),"+553133334444")
        self.assertEqual(phone_number("(55) 99999-9999","BR"),"+5555999999999")
        self.assertEqual(phone_number("+1 (415) 555-2671","US"),"+14155552671")
        self.assertEqual(phone_number("12345","BR"),"")
    def test_objective_website_score(self):
        page=PublicPage()
        page.feed("<html><head><title>Clínica Exemplo</title></head><body><p>Agende aqui</p></body></html>")
        issues=website_issues(page)
        self.assertIn("missing_viewport",issues)
        self.assertIn("missing_h1",issues)
        self.assertGreaterEqual(opportunity_score(issues),65)
    def test_phone_only_qualified_without_business_mail(self):
        with patch("site_research.crawl_business_pages",return_value=dict(LANDING)),\
             patch("site_research.find_public_contact",return_value=dict(NO_MAIL)),\
             patch("site_research.search_company_cnpj",return_value=None),\
             patch("site_research.pg",return_value={"accepted":1}) as post:
            result=research(SITE)
        self.assertEqual(result["phone_saved"],1)
        self.assertEqual(result["email_saved"],0)
        payload=post.call_args.args[1]
        self.assertEqual(payload["action"],"research_phone_candidate")
        self.assertEqual(payload["lead"]["phone_source_type"],"official_site")
        self.assertTrue(payload["lead"]["email_absent"])
    def test_email_qualified_never_enters_phone_only(self):
        with patch("site_research.crawl_business_pages",return_value=dict(LANDING)),\
             patch("site_research.find_public_contact",return_value=dict(GOOD_MAIL)),\
             patch("site_research.search_company_cnpj",return_value=None),\
             patch("site_research.pg") as phone_write,\
             patch("site_research.persist",return_value=True):
            result=research(SITE)
        self.assertEqual(result["email_saved"],1)
        self.assertEqual(result["phone_saved"],0)
        phone_write.assert_not_called()
    def test_healthy_site_is_not_phone_sales_lead(self):
        healthy=dict(LANDING,issues=["missing_social_preview"],score=21)
        with patch("site_research.crawl_business_pages",return_value=healthy),\
             patch("site_research.find_public_contact",return_value=dict(NO_MAIL)),\
             patch("site_research.search_company_cnpj",return_value=None),\
             patch("site_research.pg") as phone_write:
            result=research(SITE)
        self.assertEqual(result["phone_saved"],0)
        phone_write.assert_not_called()

if __name__=="__main__":
    unittest.main()
