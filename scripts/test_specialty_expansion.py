"""Ensure geographic search cannot regress to six specialties or email-less records."""
import unittest
from unittest.mock import patch

from specialties import (
    BASE_BR,BASE_US,BR_SPECIALTIES,US_SPECIALTIES,
    TOTAL_SPECIALTIES,search_phrases,specialty_at
)
from daily_lead_discovery import MailtoParser,persist

class SpecialtyExpansionTests(unittest.TestCase):
    def test_both_countries_cover_same_number_of_specialties(self):
        self.assertEqual(TOTAL_SPECIALTIES,153)
        self.assertEqual(len(BR_SPECIALTIES),153)
        self.assertEqual(len(US_SPECIALTIES),153)

    def test_keep_existing_six_specialty_checkpoints(self):
        self.assertEqual(tuple(BASE_BR),(
            "Dermatologia","Cardiologia","Pediatria",
            "Neurologia","Ginecologia","Clínica Médica"
        ))
        self.assertEqual(tuple(BASE_US),(
            "Dermatology","Cardiology","Pediatrics",
            "Neurology","Obstetrics","Internal Medicine"
        ))

    def test_requested_brazilian_specialties_in_catalog(self):
        labels=" | ".join(BR_SPECIALTIES).casefold()
        for name in (
            "Nutricionista Clínico","Urologia","Psicologia Clínica","Odontologia",
            "Cardiologia Pediátrica","Gastroenterologia Pediátrica",
            "Alergia e Imunologia Pediátrica","Reprodução Assistida",
            "Nutrição Parenteral e Enteral Pediátrica","Obstetrícia",
            "Psiquiatria da Infância e Adolescência",
            "Ultrassonografia em Ginecologia e Obstetrícia"
        ):
            with self.subTest(name=name):
                self.assertIn(name.casefold(),labels)

    def test_two_search_variations_cover_each_specialty(self):
        for country in ("BR","US"):
            for i in (0,6,52,90,152):
                variants=search_phrases(country,i)
                self.assertEqual(len(variants),2)
                self.assertNotEqual(variants[0],variants[1])
                self.assertIn(specialty_at(country,i),variants[0])

    def test_public_first_party_medical_email_allowed(self):
        parser=MailtoParser("exampleclinic.com")
        parser.feed("<a href='mailto:dr.silva@exampleclinic.com'>Contato</a>")
        self.assertIn("dr.silva@exampleclinic.com",parser.emails)

    def test_third_party_private_personal_email_rejected(self):
        parser=MailtoParser("exampleclinic.com")
        parser.feed("<a href='mailto:firstname.lastname@gmail.com'>Contato</a>")
        self.assertNotIn("firstname.lastname@gmail.com",parser.emails)

    def test_email_less_leads_are_never_sent_to_database(self):
        with patch("daily_lead_discovery.pg") as mocked:
            self.assertFalse(persist({"business_email":""}))
            mocked.assert_not_called()

    def test_database_duplicate_does_not_count_as_new(self):
        with patch("daily_lead_discovery.pg",return_value={"accepted":0}):
            self.assertFalse(persist({
                "business_email":"info@exampleclinic.com",
                "email_source_url":"https://exampleclinic.com/contact",
                "email_confidence":95
            }))

if __name__=="__main__":
    unittest.main()
