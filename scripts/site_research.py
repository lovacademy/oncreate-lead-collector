"""Checkpointed investigation of official healthcare business websites.

Runs without extra Claude searches. Saves verified first-party email contacts to
the existing manual-review queue; phone-only business opportunities to a separate
table only when at least two objective website issues are evidenced.
Never creates CRM contacts or outbound emails.
"""
import datetime as dt
import json
import os
import re
import time
from html.parser import HTMLParser
from urllib import error, parse, request, robotparser

from daily_lead_discovery import (
    AGENT, EMAIL_RE, ROLE_RE, find_public_contact, persist, pg, public_web_url
)
from cnpj_enrichment import (
    extract_cnpjs, public_company_profile, search_company_cnpj
)

USER_AGENT="OnCreate-Company-Site-Research/1.0 (public business pages)"
PAGE_LIMIT=6
MAX_HTML=240000
SITEMAP_PATHS=("/contato","/contact","/fale-conosco","/sobre","/about")
BR_PHONE=re.compile(r"(?<!\d)(?:\+?55[\s().-]*)?\(?\d{2}\)?[\s.-]*(?:9[\s.-]*)?\d{4}[\s.-]?\d{4}(?!\d)")
US_PHONE=re.compile(r"(?<!\d)(?:\+?1[\s().-]*)?\(?[2-9]\d{2}\)?[\s.-]*[2-9]\d{2}[\s.-]*\d{4}(?!\d)")

class PublicPage(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title=[]
        self.heading=[]
        self.text=[]
        self.phones=[]
        self.cnpjs=set()
        self.links=[]
        self.tags={}
        self._in_title=False
        self._in_h1=False
        self._skip=0
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag in ("script","style","noscript","svg"):
            self._skip+=1
        if tag=="title":self._in_title=True
        if tag=="h1":self._in_h1=True
        if tag=="meta":
            key=(attrs.get("name") or attrs.get("property") or "").lower()
            if key in ("description","viewport","og:title","og:description"):
                self.tags[key]=str(attrs.get("content") or "")[:260]
        if tag=="a":
            href=str(attrs.get("href") or "").strip()
            if href.startswith("tel:"):
                self.phones.append((parse.unquote(href[4:].split(";",1)[0]),"tel"))
            elif href:
                self.links.append(href[:300])
    def handle_endtag(self,tag):
        if tag=="title":self._in_title=False
        if tag=="h1":self._in_h1=False
        if tag in ("script","style","noscript","svg"):
            self._skip=max(0,self._skip-1)
    def handle_data(self,data):
        if self._skip or not data.strip():return
        if self._in_title:self.title.append(data.strip())
        if self._in_h1:self.heading.append(data.strip())
        if len(self.text)<280:
            self.text.append(data[:550])
        if len(self.cnpjs)<3:
            self.cnpjs.update(extract_cnpjs(data)[:3])
    def summary(self):
        return " ".join(self.text)[:26000]

def phone_number(raw,country):
    """Format *business listing* phones as E.164, not private-number enrichment."""
    digits=re.sub(r"\D","",str(raw or "").split("ext",1)[0])
    if country=="BR":
        if len(digits) in (10,11) and digits[:2]!="00":
            return "+55"+digits
        if len(digits) in (12,13) and digits.startswith("55"):
            return "+"+digits
    if country=="US":
        if len(digits)==10 and digits[0] in "23456789" and digits[3] in "23456789":
            return "+1"+digits
        if len(digits)==11 and digits.startswith("1") and digits[1] in "23456789":
            return "+"+digits
    return ""

def website_issues(page):
    """Technical indicators, not a claim that design quality is definitively poor."""
    issues=[]
    if not page.tags.get("viewport"):issues.append("missing_viewport")
    if not page.tags.get("description"):issues.append("missing_description")
    if not page.heading:issues.append("missing_h1")
    if not " ".join(page.title).strip():issues.append("missing_title")
    if not any("contato" in x.lower() or "contact" in x.lower() or
               "fale-conosco" in x.lower() for x in page.links):
        issues.append("no_contact_navigation")
    if not page.tags.get("og:title"):issues.append("missing_social_preview")
    return issues

def opportunity_score(issues):
    weights={"missing_viewport":29,"missing_description":17,
             "missing_h1":21,"missing_title":23,
             "no_contact_navigation":14,"missing_social_preview":7}
    return min(100,14+sum(weights.get(x,0) for x in issues))

def crawl_business_pages(website,country):
    site=public_web_url(website)
    if not site:raise RuntimeError("Official business domain is not safe to visit")
    host=parse.urlsplit(site).hostname
    class NoRedirect(request.HTTPRedirectHandler):
        def redirect_request(self,req,fp,code,msg,headers,newurl):
            return None
    opener=request.build_opener(request.HTTPHandler(),request.HTTPSHandler(),NoRedirect)
    rules=robotparser.RobotFileParser()
    try:
        r=request.Request(site+"/robots.txt",headers={"User-Agent":USER_AGENT})
        with opener.open(r,timeout=7) as resp:
            if int(resp.headers.get("Content-Length","0"))>180000:
                raise RuntimeError("robots.txt too large")
            rules.parse(resp.read(180000).decode("utf-8","replace").splitlines())
    except error.HTTPError as exc:
        if exc.code==404:rules.parse([])
        else:raise RuntimeError("Website robots rules unavailable") from None
    except (OSError,ValueError):
        raise RuntimeError("Website robots rules unavailable") from None
    queue=[site+"/"]
    seen=set()
    pages=[]
    numbers=[]
    published_cnpjs=set()
    home=None
    for url in queue:
        if len(pages)>=PAGE_LIMIT:break
        if url in seen or not rules.can_fetch(USER_AGENT,url):continue
        seen.add(url)
        if public_web_url(url)!=site:continue
        try:
            req=request.Request(url,headers={"User-Agent":USER_AGENT,"Accept":"text/html"})
            with opener.open(req,timeout=9) as res:
                final=parse.urlsplit(res.geturl())
                if (final.scheme!="https" or final.hostname!=host or
                    "text/html" not in res.headers.get("Content-Type","")):
                    continue
                if int(res.headers.get("Content-Length","0"))>MAX_HTML:continue
                html=res.read(MAX_HTML).decode("utf-8","replace")
        except (error.HTTPError,error.URLError,OSError,TimeoutError,ValueError):
            continue
        parser=PublicPage()
        try:parser.feed(html)
        except ValueError:continue
        if home is None:home=parser
        pages.append(url)
        published_cnpjs.update(list(parser.cnpjs)[:3])
        for phone,method in parser.phones[:12]:
            formatted=phone_number(phone,country)
            if formatted:numbers.append((formatted,url,2 if method=="tel" else 1))
        if ("/contato" in url or "/contact" in url or url==site+"/") and parser.summary():
            pattern=BR_PHONE if country=="BR" else US_PHONE
            for match in list(pattern.finditer(parser.summary()))[:10]:
                formatted=phone_number(match.group(0),country)
                if formatted:numbers.append((formatted,url,1))
        if len(queue)<12:
            for link in parser.links:
                next_url=parse.urljoin(site+"/",link)
                u=parse.urlsplit(next_url)
                if (u.scheme=="https" and u.hostname==host and not u.query and
                    any(h in u.path.lower() for h in ("contact","contato","fale-conosco","about","sobre"))):
                    link_url=site+(u.path.rstrip("/") or "/")
                    if link_url not in queue:queue.append(link_url)
        if len(queue)<10 and url==site+"/":
            queue.extend(site+path for path in SITEMAP_PATHS if site+path not in queue)
        time.sleep(.3)
    if not home or not pages:raise RuntimeError("No usable first-party HTML for site assessment")
    issues=website_issues(home)
    numbers.sort(key=lambda x:(-x[2],0 if "contact" in x[1] or "contato" in x[1] else 1))
    return {
        "site":site,"pages":pages,"issues":issues,
        "score":opportunity_score(issues),
        "site_title":" ".join(home.title).strip()[:160],
        "site_description":home.tags.get("description","")[:260],
        "site_h1":" ".join(home.heading).strip()[:180],
        "phone":numbers[0][0] if numbers else "",
        "phone_source_url":numbers[0][1] if numbers else "",
        "cnpjs":list(sorted(published_cnpjs))[:2],
    }

def research(site):
    country=site["country_code"]
    state=site["state"]
    city=site["city"]
    host=site["website_domain"]
    os.environ["DISCOVERY_COUNTRY"]=country
    os.environ["DISCOVERY_STATES"]=state
    os.environ["DISCOVERY_CITY"]=city
    landing=crawl_business_pages(site["website"],country)
    # Use existing validated 7-page crawler; preserves email checks and source evidence.
    evidence=find_public_contact(site["website"])
    cnpj=landing["cnpjs"][0] if landing["cnpjs"] and country=="BR" else ""
    registry=None
    if country=="BR":
        if not cnpj:
            lookup=search_company_cnpj(site["company_name"],state,city)
            cnpj=(lookup or {}).get("cnpj","")
        if cnpj:
            registry=public_company_profile(cnpj,state,city)
    official_email=str(evidence.get("email") or "").lower()
    valid_email=(bool(EMAIL_RE.fullmatch(official_email)) and
                 official_email.rsplit("@",1)[-1]==host and
                 int(evidence.get("confidence") or 0)>=75)
    if not valid_email and registry:
        registered=str(registry.get("business_email") or "").strip().lower()
        if EMAIL_RE.fullmatch(registered) and registered.rsplit("@",1)[-1]==host:
            official_email=registered
            valid_email=True
            evidence.update({"email":registered,"confidence":90,
                             "source_type":"registry",
                             "source_url":registry["source_url"],"status":"found"})
    email_saved=0
    if valid_email:
        lead={
          "source_name":"website","source_key":host[:145],
          "company_name":site["company_name"][:160],
          "contact_name":"","business_email":official_email,
          "website":landing["site"],
          "country_code":country,"state":state,"city":city,
          "specialty":site["specialty"][:100],"source_url":site["source_url"],
          "site_confidence":80,"email_confidence":int(evidence["confidence"]),
          "email_source_url":evidence["source_url"],
          "email_source_type":evidence["source_type"],
          "crawl_status":evidence.get("status","found"),
          "pages_scanned":evidence.get("pages_scanned",0),
          "last_crawled_at":evidence.get("last_crawled_at"),
          "note":"Site oficial investigado. Revisão manual obrigatória antes de importar ao CRM."
        }
        email_saved=int(bool(persist(lead)))
    business_phone=landing["phone"]
    phone_source_url=landing["phone_source_url"]
    phone_kind="official_site"
    if not business_phone and registry:
        number=phone_number(registry.get("business_phone"),country)
        if number:
            business_phone=number
            phone_source_url=registry["source_url"]
            phone_kind="verified_company_registry"
    # Store business data only; do not copy partners, personal details or extraneous emails.
    company_details={k:v for k,v in (registry or {}).items() if k not in
                     ("business_email","business_phone")}
    details={
       "verified_site":landing["site"],
       "site_title":landing["site_title"],
       "site_description":landing["site_description"],
       "site_h1":landing["site_h1"],
       "technical_issues":landing["issues"],
       "opportunity_score":landing["score"],
       "pages_visited":landing["pages"],
       "pages_scanned":len(landing["pages"]),
       "email_status":"verified" if valid_email else "no_qualified_business_email",
       "email_source_url":evidence.get("source_url","") if valid_email else "",
       "published_business_phone":business_phone,
       "business_phone_source":phone_source_url,
       "registered_company":company_details,
       "cnpj_checked":bool(cnpj),"research_date":dt.datetime.now(dt.timezone.utc).isoformat(),
       "assessment_notice":"Objective technical signals only. Human sales review required."
    }
    phone_saved=0
    if (not valid_email and business_phone and phone_source_url and
        int(evidence.get("pages_scanned") or 0)>=1 and
        evidence.get("status") not in ("blocked","error","no_official_site") and
        len(landing["issues"])>=2 and landing["score"]>=65):
        lead={
          "email_absent":True,"business_phone":business_phone,
          "phone_source_url":phone_source_url,"phone_source_type":phone_kind,
          "cnpj":cnpj,"legal_name":(registry or {}).get("legal_name",""),
          "opportunity_score":landing["score"],
          "website_issues":landing["issues"],
          "research_data":details
        }
        result=pg("research_control",{"action":"research_phone_candidate",
                        "job_id":os.getenv("COLLECTION_JOB_ID",""),
                        "id":site["id"],"lead":lead})
        phone_saved=int(result.get("accepted") or 0)
    return {"email_saved":email_saved,"phone_saved":phone_saved,"details":details}

def main():
    job=os.environ["COLLECTION_JOB_ID"]
    record=pg("research_control",{"action":"research_claim","job_id":job})
    site=record.get("site")
    if not site:
        print(json.dumps({"work":False,"email_saved":0,"phone_saved":0}),flush=True)
        return
    try:
        result=research(site)
        finish=pg("research_control",{
            "action":"research_finish","job_id":job,"id":site["id"],
            "status":"completed","details":result["details"]})
        if not finish.get("ok"):
            raise RuntimeError("Research checkpoint not saved")
        print(json.dumps({"work":True,"email_saved":result["email_saved"],
                          "phone_saved":result["phone_saved"],
                          "website_domain":site["website_domain"]}),flush=True)
    except Exception as exc:
        # No website body or private business fields in logs.
        reason=type(exc).__name__+": "+str(exc)[:95]
        try:
            pg("research_control",{"action":"research_finish","job_id":job,
             "id":site["id"],"status":"failed",
             "details":{"status":"retryable_error"},
             "error":reason})
        except Exception:
            pass
        print(json.dumps({"work":True,"email_saved":0,"phone_saved":0,
                          "failed":True,"error_type":type(exc).__name__}),flush=True)

if __name__=="__main__":
    main()
