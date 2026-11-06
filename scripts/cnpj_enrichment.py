"""Free public CNPJ enrichment for clinics that publish their own registration.

Source: the documented OpenCNPJ public API at kitana.opencnpj.com.
No directory scraping or private owner contact collection.
Only first-party company-domain addresses are eligible as sales contacts.
"""
import json
import re
from urllib import request, error, parse
from unicodedata import normalize

CNPJ_RE=re.compile(r"(?<!\d)\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}(?!\d)")
EMAIL_RE=re.compile(r"^[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}$",re.I)
API="https://kitana.opencnpj.com/cnpj/"

def normalized(value):
    return "".join(c for c in normalize("NFKD",str(value or "")) if not
                   __import__("unicodedata").combining(c)).casefold().strip()

def valid_cnpj(value:str)->bool:
    digits=re.sub(r"\D","",str(value or ""))
    if len(digits)!=14 or len(set(digits))==1:return False
    def check(nums):
        size=len(nums)
        weights=list(range(size-7,1,-1))+list(range(9,9-(size-(size-8)), -1))
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
