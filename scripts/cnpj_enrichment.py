"""Free public CNPJ enrichment for clinics that publish their own registration.

Source: the documented OpenCNPJ public API at kitana.opencnpj.com.
No directory scraping or private owner contact collection.
Only first-party company-domain addresses are eligible as sales contacts.
"""
import json
import re
from urllib import request, error, parse
from unicodedata import normalize, combining

CNPJ_RE=re.compile(r"(?<!\d)\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}(?!\d)")
EMAIL_RE=re.compile(r"^[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}$",re.I)
API="https://kitana.opencnpj.com/cnpj/"

def normalized(value):
    return "".join(c for c in normalize("NFKD",str(value or "")) if not
                   combining(c)).casefold().strip()

def valid_cnpj(value:str)->bool:
    digits=re.sub(r"\D","",str(value or ""))
    if len(digits)!=14 or len(set(digits))==1:return False
    def check(nums):
        size=len(nums)
        # canonical CNPJ weights for 12- and 13-digit bases
        w=([5,4,3,2,9,8,7,6,5,4,3,2] if size==12 else
           [6,5,4,3,2,9,8,7,6,5,4,3,2])
        remainder=sum(int(a)*b for a,b in zip(nums,w))%11
        return 0 if remainder<2 else 11-remainder
    return (int(digits[12])==check(digits[:12]) and
            int(digits[13])==check(digits[:13]))

def extract_cnpjs(text):
    return [value for v in CNPJ_RE.findall(str(text or "")) if
            (value:="".join(c for c in v if c.isdigit())) and valid_cnpj(value)]

def public_company_email(cnpj:str,website_host:str,expected_state:str,
                         expected_city:str):
    """Only return an address matching the entity's own practice domain.

    CNPJ lookup is an enrichment cross-check, not evidence of consent to mail.
    The CNPJ must already have been published by the company's own website.
    """
    if not valid_cnpj(cnpj):return None
    host=str(website_host or "").lower().removeprefix("www.").split(":")[0]
    if not host or "." not in host:return None
    endpoint=API+cnpj
    req=request.Request(endpoint,headers={
        "Accept":"application/json",
        "User-Agent":"OnCreate-Lead-Research/1.0 (public company registry verification)"
    })
    try:
        with request.urlopen(req,timeout=11) as res:
            payload=json.loads(res.read(700000).decode("utf-8"))
    except (error.HTTPError,error.URLError,TimeoutError,ValueError,OSError):
        return None
    info=payload.get("data") if isinstance(payload,dict) else None
    if not isinstance(info,dict):return None
    if str(info.get("cnpj") or "")!=cnpj:return None
    if str(info.get("situacaoCadastral") or "").casefold() not in ("ativa","ativo"):
        return None
    if str(info.get("uf") or "").upper()!=expected_state.upper():return None
    if expected_city and normalized(info.get("municipio"))!=normalized(expected_city):
        return None
    email=str(info.get("email") or "").strip().lower()
    if not EMAIL_RE.fullmatch(email):return None
    # Strict first-party validation: do not store personal Gmail, Hotmail etc.
    # even if the public tax registration happens to contain one.
    domain=email.rsplit("@",1)[1]
    if domain!=host:return None
    if email.split("@")[0] in ("noreply","no-reply","example","test"):
        return None
    return {
        "email":email,"source_url":endpoint,
        "source_type":"registry","confidence":92,
        "company_registered_name":str(info.get("razaoSocial") or "")[:160],
        "cnpj":cnpj
    }


# Public search endpoint documented by Consulta Data Stone.
# Source attribution: https://consulta.datastone.com.br/api-publica
# 60/min/IP best-effort; no broad scans, no repeated searches, no personal data.
SEARCH_API="https://consulta.datastone.com.br/api/v1/busca"

def search_company_cnpj(company_name:str, expected_state:str, expected_city:str):
    """Resolve a CNPJ candidate by name+municipality without guesswork.

    This search only yields a CNPJ when the firm name substantially overlaps the
    public listing. A physician's name alone will NOT imply ownership of an
    unrelated corporate registration. The official website must be matched by
    separate evidence before any contact is accepted.
    """
    name=normalized(company_name)
    state=str(expected_state or "").upper().strip()
    city=normalized(expected_city)
    if len(name)<8 or len(name)>150 or not re.fullmatch(r"[A-Z]{2}",state) or len(city)<3:
        return None
    generic={"dr","dra","doctor","doutor","doutora","clinica","clinical","medica",
             "medico","medicos","medicas","servicos","atendimento","consultorio",
             "de","da","do","das","dos","e","ltda","s","a"}
    tokens={w for w in re.findall(r"[a-z0-9]{3,}",name) if w not in generic}
    if len(tokens)<2:
        return None
    # No unrestricted pagination or broad first-name-only lookups.
    query={"q":str(company_name).strip()[:110]}
    url=SEARCH_API+"?"+parse.urlencode(query)
    req=request.Request(url,headers={
        "Accept":"application/json",
        "User-Agent":"OnCreate-Lead-Research/1.0 (public business verification)"
    })
    try:
        with request.urlopen(req,timeout=8) as res:
            if int(res.headers.get("Content-Length","0"))>160000:return None
            payload=json.loads(res.read(160000).decode("utf-8"))
    except (error.HTTPError,error.URLError,TimeoutError,ValueError,OSError):
        return None
    results=payload.get("resultados") if isinstance(payload,dict) else None
    if not isinstance(results,list):
        return None
    best=None
    for item in results[:10]:
        if not isinstance(item,dict):
            continue
        number="".join(c for c in str(item.get("cnpj") or "") if c.isdigit())
        if not valid_cnpj(number):
            continue
        if str(item.get("uf") or "").upper().strip()!=state:
            continue
        if normalized(item.get("cidade"))!=city:
            continue
        if normalized(item.get("situacao")) not in ("ativa","ativo"):
            continue
        labels=[normalized(item.get("razao_social")), normalized(item.get("nome_fantasia"))]
        matched=False
        for label in labels:
            labeled={w for w in re.findall(r"[a-z0-9]{3,}",label) if w not in generic}
            if len(labeled)<2:
                continue
            overlap=len(tokens & labeled)
            coverage=overlap/max(len(tokens),len(labeled))
            if overlap>=2 and coverage>=0.65:
                matched=True
                break
        if not matched:
            continue
        if best and best["cnpj"]!=number:
            # Multiple plausible registrations: require manual adjudication.
            return None
        best={"cnpj":number,"source_url":(
            (item.get("_links") or {}).get("pagina")
            or "https://consulta.datastone.com.br"
        ),"source_type":"company_name_lookup"}
    return best
