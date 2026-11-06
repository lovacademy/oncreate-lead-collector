"""Verify CNPJ-based enrichment without real network access or personal data."""
import io
import json
import unittest
from unittest.mock import patch
from cnpj_enrichment import valid_cnpj, extract_cnpjs, public_company_email

class PublicCNPJTests(unittest.TestCase):
    def test_cnpj_checksum(self):
        self.assertTrue(valid_cnpj("00.000.000/0001-91"))
        self.assertTrue(valid_cnpj("33.000.167/0001-01"))
        self.assertFalse(valid_cnpj("00.000.000/0000-00"))
        self.assertFalse(valid_cnpj("12.345.678/9012-00"))

    def test_extraction_from_first_party_page(self):
        self.assertIn("00000000000191",
                      extract_cnpjs("CNPJ: 00.000.000/0001-91"))

    def _lookup(self,email,uf="MG",city="Poços de Caldas"):
        data={
            "success":True,
            "data":{
                "cnpj":"00000000000191","situacaoCadastral":"Ativa",
                "uf":uf,"municipio":city,
                "email":email,"razaoSocial":"Clinica Demo de Saúde LTDA"
            }
        }
        class FakeReply:
            def __enter__(self):return self
            def __exit__(self,*args):return False
            def read(self,*args):return json.dumps(data).encode("utf-8")
        with patch("cnpj_enrichment.request.urlopen",return_value=FakeReply()):
            return public_company_email(
                "00000000000191","clinicademo.com.br","MG","Poços de Caldas")

    def test_corresponding_company_domain(self):
        result=self._lookup("contato@clinicademo.com.br")
        self.assertEqual(result["source_type"],"registry")
        self.assertEqual(result["confidence"],92)

    def test_personal_free_mail_not_auto_imported(self):
        self.assertIsNone(self._lookup("particular@gmail.com"))
        self.assertIsNone(self._lookup("contato@outraclinica.com.br"))

    def test_wrong_state_or_city_not_auto_imported(self):
        self.assertIsNone(self._lookup("info@clinicademo.com.br",uf="SP"))
        self.assertIsNone(self._lookup("info@clinicademo.com.br",city="Belo Horizonte"))

if __name__=="__main__":
    unittest.main()
