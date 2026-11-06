"""Offline tests for strict free Brazilian company-name to CNPJ matching."""
import json
import unittest
from unittest.mock import patch

from cnpj_enrichment import search_company_cnpj

class Response:
    def __init__(self,data):
        self.data=json.dumps(data).encode()
        self.headers={"Content-Length":str(len(self.data))}
    def __enter__(self):
        return self
    def __exit__(self,*args):
        return False
    def read(self,n):
        return self.data[:n]

VALID_CNPJ="00000000000191"

class NameLookupTests(unittest.TestCase):
    def test_city_name_and_state_must_match(self):
        payload={"resultados":[{"cnpj":VALID_CNPJ,
            "razao_social":"CLINICA ALPHA BETA LTDA",
            "nome_fantasia":"CLINICA ALPHA BETA",
            "cidade":"Campinas","uf":"SP","situacao":"Ativa",
            "_links":{"pagina":"https://www.datastone.com.br/consulta/empresa/example"}}]}
        with patch("cnpj_enrichment.request.urlopen",return_value=Response(payload)):
            result=search_company_cnpj("Clinica Alpha Beta","SP","Campinas")
        self.assertEqual(result["cnpj"],VALID_CNPJ)
        with patch("cnpj_enrichment.request.urlopen",return_value=Response(payload)):
            self.assertIsNone(search_company_cnpj("Clinica Alpha Beta","MG","Campinas"))
        with patch("cnpj_enrichment.request.urlopen",return_value=Response(payload)):
            self.assertIsNone(search_company_cnpj("Clinica Alpha Beta","SP","Ribeirao Preto"))

    def test_generic_name_avoids_remote_request(self):
        with patch("cnpj_enrichment.request.urlopen") as call:
            self.assertIsNone(search_company_cnpj("Clínica Médica","SP","Campinas"))
            call.assert_not_called()

    def test_similar_legal_name_does_not_mean_same_professional(self):
        payload={"resultados":[{"cnpj":VALID_CNPJ,
            "razao_social":"AAL SERVICOS MEDICOS LTDA",
            "nome_fantasia":"AAL",
            "cidade":"Poços de Caldas","uf":"MG","situacao":"Ativa"}]}
        with patch("cnpj_enrichment.request.urlopen",return_value=Response(payload)):
            result=search_company_cnpj("Doutor Alvaro Avila Lemos","MG","Poços de Caldas")
        self.assertIsNone(result)

if __name__ == "__main__":
    unittest.main()
