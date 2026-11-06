"""Free U.S. EIN verification through the SEC's official EDGAR API.

Only applicable to organizations filing with the SEC. An EIN does not reveal
a contact mailbox, and most private physician offices are NOT SEC filers.
No third-party paid EIN services or CAPTCHA automation.
"""
import json
import re
from urllib import request,error

EIN_RE=re.compile(r"\b(?:EIN|Employer Identification Number|Federal Tax ID|Tax Identification Number)\s*(?::|#|no\.?)?\s*(\d{2}[-\s]?\d{7})\b",re.I)
CIK_RE=re.compile(r"\bCIK\s*(?::|#|no\.?)?\s*(\d{1,10})\b",re.I)
ENDPOINT="https://data.sec.gov/submissions/CIK{cik:010d}.json"
AGENT="OnCreate Business Research oncreateagencia@gmail.com"

def published_ids(text):
    text=str(text or "")[:500000]
    eins={"".join(c for c in m if c.isdigit()) for m in EIN_RE.findall(text)}
    ciks={int(m) for m in CIK_RE.findall(text)}
    return eins,ciks

def verify_sec_ein(cik,ein):
    """Return a verified public company identity ONLY on exact EIN match."""
    digits="".join(c for c in str(ein) if c.isdigit())
    try:cik=int(cik)
    except (TypeError,ValueError):return None
    if cik<1 or cik>9999999999 or len(digits)!=9:return None
    url=ENDPOINT.format(cik=cik)
    req=request.Request(url,headers={
        "Accept":"application/json","User-Agent":AGENT
    })
    try:
        with request.urlopen(req,timeout=12) as res:
            data=json.loads(res.read(1300000).decode("utf-8"))
    except (error.HTTPError,error.URLError,OSError,ValueError,TimeoutError):
        return None
    if str(data.get("ein") or "").replace("-","")!=digits:
        return None
    if int(data.get("cik") or 0)!=cik:return None
    return {
        "ein":digits,"cik":cik,"legal_name":str(data.get("name") or "")[:180],
        "source_url":url,"source_type":"sec_verified"
    }
