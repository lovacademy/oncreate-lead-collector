"""Stable bilingual medical, dental, nutrition and behavioral-health search catalog.

Keep the first six pass positions stable to preserve existing location checkpoints.
All other specialties come from the user's requested medical areas and broader
healthcare specialties. New entries append; never silently reorder persisted indexes.
"""
BASE_US=["Dermatology", "Cardiology", "Pediatrics", "Neurology", "Obstetrics", "Internal Medicine"]
BASE_BR=["Dermatologia", "Cardiologia", "Pediatria", "Neurologia", "Ginecologia", "Clínica Médica"]
EXTENDED_DATA="""Alergia e Imunologia Pediátrica|Pediatric Allergy and Immunology
Angiorradiologia e Cirurgia Endovascular|Endovascular Surgery and Interventional Vascular Radiology
Atendimento ao Queimado|Burn Care
Cardiologia Pediátrica|Pediatric Cardiology
Cirurgia Bariátrica|Bariatric Surgery
Cirurgia Crânio-Maxilo-Facial|Cranio-Maxillofacial Surgery
Cirurgia do Trauma|Trauma Surgery
Cirurgia Videolaparoscópica|Laparoscopic Surgery
Citopatologia|Cytopathology
Densitometria Óssea|Bone Densitometry
Dor|Pain Medicine
Ecocardiografia|Echocardiography
Ecografia Vascular com Doppler|Vascular Doppler Ultrasound
Eletrofisiologia Clínica Invasiva|Cardiac Electrophysiology
Emergência Pediátrica|Pediatric Emergency Medicine
Endocrinologia Pediátrica|Pediatric Endocrinology
Endoscopia Digestiva|Digestive Endoscopy
Endoscopia Ginecológica|Gynecologic Endoscopy
Endoscopia Respiratória|Respiratory Endoscopy
Ergometria|Exercise Stress Testing
Estimulação Cardíaca Eletrônica Implantável|Cardiac Device Implantation
Foniatria|Phoniatrics Voice Disorders
Gastroenterologia Pediátrica|Pediatric Gastroenterology
Hansenologia|Leprosy Medicine
Hematologia e Hemoterapia Pediátrica|Pediatric Hematology and Transfusion Medicine
Hemodinâmica e Cardiologia Intervencionista|Interventional Cardiology and Hemodynamics
Hepatologia|Hepatology
Infectologia Hospitalar|Hospital Infectious Diseases
Infectologia Pediátrica|Pediatric Infectious Diseases
Mamografia|Mammography
Medicina Aeroespacial|Aerospace Medicine
Medicina do Adolescente|Adolescent Medicine
Medicina do Sono|Sleep Medicine
Medicina Fetal|Maternal Fetal Medicine
Medicina Intensiva Pediátrica|Pediatric Critical Care Medicine
Medicina Paliativa|Palliative Care Medicine
Medicina Tropical|Tropical Medicine
Nefrologia Pediátrica|Pediatric Nephrology
Neonatologia|Neonatology
Neurofisiologia Clínica|Clinical Neurophysiology
Neurologia Pediátrica|Pediatric Neurology
Neurorradiologia|Neuroradiology
Nutrição Parenteral e Enteral|Parenteral and Enteral Nutrition
Nutrição Parenteral e Enteral Pediátrica|Pediatric Parenteral and Enteral Nutrition
Nutrologia Pediátrica|Pediatric Nutrition Medicine
Oncologia Pediátrica|Pediatric Oncology
Pneumologia Pediátrica|Pediatric Pulmonology
Psicogeriatria|Geriatric Psychiatry
Psicoterapia|Psychotherapy
Psiquiatria da Infância e Adolescência|Child and Adolescent Psychiatry
Psiquiatria Forense|Forensic Psychiatry
Radiologia Intervencionista e Angiorradiologia|Interventional Radiology
Reprodução Assistida|Assisted Reproductive Medicine
Reumatologia Pediátrica|Pediatric Rheumatology
Sexologia|Sexology Sexual Medicine
Toxicologia Médica|Medical Toxicology
Transplante de Medula Óssea|Bone Marrow Transplantation
Ultrassonografia em Ginecologia e Obstetrícia|Obstetric and Gynecologic Ultrasound
Nutricionista Clínico|Clinical Dietitian Nutritionist
Nutrição Esportiva|Sports Nutritionist
Nutricionista Materno Infantil|Maternal and Child Nutritionist
Nutricionista Pediátrico|Pediatric Dietitian
Nutrição Funcional|Functional Nutritionist
Nutrologia|Clinical Nutrition Medicine
Urologia|Urology
Urologia Pediátrica|Pediatric Urology
Andrologia|Andrology Men's Health
Dermatologia Estética|Cosmetic Dermatology
Dermatologia Pediátrica|Pediatric Dermatology
Psicologia Clínica|Clinical Psychology
Psicologia Infantil|Child Psychology
Psicologia Hospitalar|Health Psychology
Neuropsicologia|Neuropsychology
Psicologia Esportiva|Sports Psychology
Psicologia Organizacional|Occupational Psychology
Odontologia|Dentistry Dental Clinic
Odontopediatria|Pediatric Dentistry
Ortodontia|Orthodontics
Implantodontia|Dental Implants Implantology
Endodontia|Endodontics
Periodontia|Periodontics
Prótese Dentária|Prosthodontics
Cirurgia Bucomaxilofacial|Oral Maxillofacial Surgery
Dentística Restauradora|Cosmetic Restorative Dentistry
Cardiologia Intervencionista|Interventional Cardiology
Pré Natal de Alto Risco|High Risk Pregnancy
Gastroenterologia|Gastroenterology
Cirurgia do Aparelho Digestivo|Gastrointestinal Surgery
Hepatologia Clínica|Clinical Hepatology
Coloproctologia|Colorectal Surgery Proctology
Pediatria do Desenvolvimento|Developmental Pediatrics
Endocrinologia|Endocrinology
Diabetologia|Diabetes Medicine
Neurocirurgia|Neurosurgery
Psiquiatria|Psychiatry
Psicologia e Saúde Mental|Mental Health Psychology
Ortopedia e Traumatologia|Orthopedic Surgery
Medicina Esportiva|Sports Medicine
Medicina de Família|Family Medicine
Medicina Preventiva|Preventive Medicine
Medicina do Trabalho|Occupational Medicine
Geriatria|Geriatrics
Reumatologia|Rheumatology
Nefrologia|Nephrology
Pneumologia|Pulmonology
Alergia e Imunologia|Allergy and Immunology
Hematologia|Hematology
Oncologia Clínica|Medical Oncology
Radioterapia|Radiation Oncology
Cirurgia Oncológica|Surgical Oncology
Infectologia|Infectious Diseases
Oftalmologia|Ophthalmology Eye Care
Otorrinolaringologia|Otolaryngology ENT
Fonoaudiologia|Speech Language Pathology
Fisioterapia|Physical Therapy Physiotherapy
Fisioterapia Pélvica|Pelvic Floor Physical Therapy
Terapia Ocupacional|Occupational Therapy
Acupuntura|Acupuncture Medicine
Quiropraxia|Chiropractic Medicine
Anestesiologia|Anesthesiology
Medicina Intensiva|Critical Care Medicine
Medicina de Emergência|Emergency Medicine
Cirurgia Geral|General Surgery
Cirurgia Plástica|Plastic Surgery
Cirurgia Vascular|Vascular Surgery
Cirurgia Cardiovascular|Cardiothoracic Surgery
Cirurgia Pediátrica|Pediatric Surgery
Cirurgia Torácica|Thoracic Surgery
Cirurgia da Mão|Hand Surgery
Radiologia e Diagnóstico por Imagem|Diagnostic Radiology
Ultrassonografia|Ultrasound Imaging
Ressonância Magnética|Magnetic Resonance Imaging
Tomografia Computadorizada|Computed Tomography
Medicina Nuclear|Nuclear Medicine
Patologia|Pathology
Análises Clínicas|Clinical Laboratory Medicine
Genética Médica|Medical Genetics
Fertilidade e Reprodução Humana|Fertility and Reproductive Medicine
Medicina Integrativa|Integrative Medicine
Homeopatia|Homeopathic Medicine
Medicina Física e Reabilitação|Physical Medicine and Rehabilitation
Cuidados Paliativos|Palliative Care
Saúde da Mulher|Women's Health
Saúde do Homem|Men's Health
Saúde Infantil|Children's Healthcare
Clínica Multidisciplinar|Multispecialty Medical Clinic
Hospital e Centro Médico|Hospital Medical Center"""

EXTENDED=tuple(tuple(part.strip() for part in line.split("|",1))
               for line in EXTENDED_DATA.strip().splitlines())
US_SPECIALTIES=tuple(BASE_US)+tuple(en for br,en in EXTENDED)
BR_SPECIALTIES=tuple(BASE_BR)+tuple(br for br,en in EXTENDED)
TOTAL_SPECIALTIES=len(US_SPECIALTIES)
assert len(BR_SPECIALTIES)==TOTAL_SPECIALTIES and TOTAL_SPECIALTIES<250

def specialty_at(country:str,index:int)->str:
    if not 0<=index<TOTAL_SPECIALTIES:
        raise IndexError("Specialty checkpoint out of bounds")
    return (BR_SPECIALTIES if country=="BR" else US_SPECIALTIES)[index]

def search_phrases(country:str,index:int)->tuple[str,str]:
    """Two complementary query variants for the same indexed specialty."""
    name=specialty_at(country,index)
    if country=="BR":
        return (f"{name} clínica consultório médico site contato e-mail",
                f"{name} profissionais clínicas agendamento contato email")
    return (f"{name} physician clinic medical practice contact email",
            f"{name} doctors specialists healthcare practice official website")

if __name__=="__main__":
    print("Total indexed healthcare specialties per city:",TOTAL_SPECIALTIES)
