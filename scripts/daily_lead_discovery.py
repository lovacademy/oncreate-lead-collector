#!/usr/bin/env python3
"""Public collector for OnCreate. Public CMS NPI Registry + optional authorized data APIs.
Never crawls Zocdoc/Tebra/AMA or search result HTML. Does not send emails.
"""
import datetime as dt
import ipaddress
import json
import os
import random
import re
import socket
import sys
import time
from urllib import error, parse, request, robotparser
from collections import deque
from html import unescape
from html.parser import HTMLParser
from specialties import search_phrases, TOTAL_SPECIALTIES
from brave_search import available as brave_available, brave_page
from cnpj_enrichment import extract_cnpjs, public_company_email

DENIED = ("zocdoc.com", "tebra.com", "ama-assn.org", "google.com", "bing.com",
          "facebook.com", "instagram.com", "linkedin.com", "yelp.com", "healthgrades.com",
          "vitals.com", "webmd.com", "npiregistry.cms.hhs.gov", "mapquest.com", "profiles.health.ny.gov", "doctor.com", "sharecare.com",
          "doctoralia.com.br", "doctoralia.com", "docplanner.com")
EMAIL_RE = re.compile(r"^[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}$", re.I)
ROLE_RE = re.compile(r"^(info|contact|hello|office|frontdesk|admin|team|reception|appointments|support|sales|contato|atendimento|agendamento|secretaria|recepcao|comercial|consultorio|clinica)@", re.I)
EMAIL_LINK_RE = re.compile(r"mailto:([a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,})", re.I)
AGENT = "OnCreate-Lead-Research/1.0 (public contact page review)"
MAX_LEADS = min(max(int(os.getenv("DISCOVERY_MAX_LEADS", "80")), 1), 250)
DELAY = max(float(os.getenv("DISCOVERY_DELAY_SECONDS", "3")), 2.0)
STATES = [s.strip().upper() for s in os.getenv("DISCOVERY_STATES", "NY,CA,FL,TX,MA").split(",") if re.fullmatch(r"[A-Za-z]{2}", s.strip())]
KEYWORDS = [s.strip() for s in os.getenv("DISCOVERY_KEYWORDS", "dermatology,internal_medicine,pediatrics").split(",") if re.fullmatch(r"[\wÀ-ÿ &/\-]{3,100}", s.strip())]
INGEST_URL = os.getenv("ONCREATE_INGEST_URL", "").strip()
TOKEN = os.getenv("ONCREATE_INGEST_TOKEN", "").strip()
session_calls = 0
OAUTH_AUDIENCE="oncreate-lead-collector-supabase"
cached_oidc=None
cached_oidc_at=0.0

def github_oidc_token():
    """Get short-lived signed token from the running Actions job, never from repo secrets."""
    global cached_oidc,cached_oidc_at
    endpoint=os.getenv("ACTIONS_ID_TOKEN_REQUEST_URL","")
    job_token=os.getenv("ACTIONS_ID_TOKEN_REQUEST_TOKEN","")
    if not endpoint or not job_token:return ""
    if cached_oidc and time.monotonic()-cached_oidc_at<180:return cached_oidc
    sep="&" if "?" in endpoint else "?"
    url=endpoint+sep+parse.urlencode({"audience":OAUTH_AUDIENCE})
    req=request.Request(url,headers={"Authorization":"Bearer "+job_token,
                                    "Accept":"application/json"},method="GET")
    with request.urlopen(req,timeout=12) as response:
        result=json.loads(response.read(16000).decode("utf-8"))
    value=result.get("value","")
    if not isinstance(value,str) or len(value)<300:raise RuntimeError("GitHub OIDC token unavailable")
    cached_oidc=value
    cached_oidc_at=time.monotonic()
    return value

def fetch_json(url, payload=None, headers=None, timeout=18):
    global session_calls
    body = json.dumps(payload).encode() if payload is not None else None
    extra = {"User-Agent": AGENT, "Accept": "application/json"}
    extra.update(headers or {})
    if body is not None: extra["Content-Type"] = "application/json"
    req = request.Request(url, headers=extra, data=body, method="POST" if body else "GET")
    with request.urlopen(req, timeout=timeout) as rsp:
        blob = rsp.read(1_800_000)
        session_calls += 1
        return json.loads(blob.decode("utf-8"))

def pg(path, payload=None, method=None, prefer=None):
    """Write only reviewed candidate fields through a restricted Supabase Edge endpoint."""
    if not INGEST_URL.startswith("https://") or not (
      TOKEN or os.getenv("ACTIONS_ID_TOKEN_REQUEST_TOKEN")):
        raise RuntimeError("An HTTPS ingest URL and GitHub Actions OIDC or shared token are required")
    if path.startswith("discovery_runs?id=eq.") and method == "PATCH":
        req_body = {"action": "run_end", "id": path.split("eq.",1)[1],
                    "status": payload.get("status", "completed"),
                    "collected": payload.get("collected", 0),
                    "enriched": payload.get("enriched", 0),
                    "notes": payload.get("notes", "")}
    elif path == "discovery_runs" and payload:
        req_body = {"action":"run_start","source_name":payload.get("source_name","nppes"),
                    "notes":payload.get("notes","")}
    elif path.startswith("discovered_leads?") and payload:
        req_body = {"action":"candidates","records":[payload]}
    elif path == "collection_control" and payload and payload.get("action") in (
        "collection_claim","collection_progress","collection_complete",
        "geo_regions","geo_seed","geo_next","geo_mark","geo_budget"
    ):
        req_body = payload
    else:
        raise RuntimeError("Collector attempted an unsupported database operation")
    body = json.dumps(req_body).encode("utf-8")
    oidc=github_oidc_token()
    auth={"X-GitHub-OIDC":oidc} if oidc else {"X-Collector-Token":TOKEN}
    req = request.Request(INGEST_URL,method="POST",data=body,headers={
        "Content-Type":"application/json","User-Agent":AGENT,**auth})
    with request.urlopen(req,timeout=20) as rsp:
        raw=rsp.read(100000).decode("utf-8")
    result=json.loads(raw) if raw else {}
    if req_body["action"]=="run_start":
        if not result.get("id"):raise RuntimeError("The intake endpoint did not create a run")
        return [{"id":result["id"]}]
    if req_body["action"].startswith(("collection_","geo_","candidates")):
        return result
    return []


def eligible_domain(domain):
    domain = (domain or "").lower().rstrip(".")
    return bool(domain and "." in domain and not any(domain == d or domain.endswith("." + d) for d in DENIED)
                and not domain.endswith((".local", ".internal", ".test")))

def public_web_url(url):
    try:
        u = parse.urlsplit(url)
        if u.scheme != "https" or u.username or u.password or u.port or not eligible_domain(u.hostname):
            return None
        if not re.fullmatch(r"[a-z0-9.\-]+", u.hostname or ""): return None
        addresses = socket.getaddrinfo(u.hostname, 443, proto=socket.IPPROTO_TCP)
        if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
            return None
        return "https://" + u.hostname
    except (ValueError, OSError, TypeError):
        return None

class MailtoParser(HTMLParser):
    """Read published generic addresses and same-domain contact navigation."""
    def __init__(self,site_hostname=""):
        super().__init__()
        self.site_hostname=site_hostname.lower().removeprefix("www.")
        self.emails=set()
        self.cnpjs=set()
        self.evidence=[]  # (email, method)
        self.links=set()
        self._ignore=0
        self._ldjson=False
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag in ("style","script","noscript"):
            self._ignore+=1
            if tag=="script" and attrs.get("type","").lower()=="application/ld+json":
                self._ldjson=True
        if tag=="a":
            href=unescape(str(attrs.get("href") or ""))
            if href.lower().startswith("mailto:"):
                for match in EMAIL_LINK_RE.finditer(href):
                    self.add(match.group(1),"mailto")
            elif href:
                self.links.add(href)
    def handle_endtag(self,tag):
        if tag in ("style","script","noscript"):
            self._ignore=max(0,self._ignore-1)
            if tag=="script":self._ldjson=False
    def handle_data(self,data):
        if not data:return
        if self._ldjson:
            for m in PUBLIC_EMAIL_RE.finditer(unescape(data)):
                self.add(m.group(0),"schema")
        elif self._ignore==0:
            for m in PUBLIC_EMAIL_RE.finditer(unescape(data)):
                self.add(m.group(0),"visible")
            for cnpj in extract_cnpjs(unescape(data)):
                if len(self.cnpjs)<4:self.cnpjs.add(cnpj)
    def add(self,email,method):
        email=email.lower().strip().strip(".,;:")
        # A first-party email published on the practice's own site is a
        # business contact even if it is not an "info@" role address.
        # Third-party free-mail contacts still require a published role address.
        domain=email.rsplit("@",1)[-1].lower()
        first_party=bool(self.site_hostname and domain==self.site_hostname)
        forbidden=email.split("@",1)[0] in {"noreply","no-reply","donotreply","test","example"}
        if EMAIL_RE.fullmatch(email) and not forbidden and (ROLE_RE.match(email) or first_party):
            self.emails.add(email)
            self.evidence.append((email,method))

PUBLIC_EMAIL_RE=re.compile(r"(?<![a-zA-Z0-9._%+\-])[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}(?![a-zA-Z0-9])",re.I)
COMMON_PAGES=("/contact","/contact-us","/contato","/fale-conosco","/about",
              "/sobre","/equipe","/team","/providers","/locations","/appointments")
CONTACT_HINTS=("contact","contato","fale-conosco","sobre","equipe","about",
               "team","provider","staff","location","appointment","our-practice","get-in-touch")
MAX_CRAWL_PAGES=7

def contact_page_score(path):
    lower=path.lower()
    if "contact" in lower or "get-in-touch" in lower:return 6
    if lower in ("","/"):return 1
    if "privacy" in lower:return -5
    return 3

def email_score(email,method,url,site):
    host=parse.urlsplit(site).hostname or ""
    domain=email.rsplit("@",1)[1]
    belongs=domain==host or domain==host.removeprefix("www.") or host.endswith("."+domain)
    base={"mailto":91,"schema":82,"visible":75}[method]
    return max(0,min(100,base+contact_page_score(parse.urlsplit(url).path)-
                        (0 if belongs else 18)))

def scanner_status(site,found,pages,eligible,blocked):
    if found:return "found"
    if pages:return "not_found"
    return "blocked" if blocked or not eligible else "error"

def find_public_contact(website):
    """Bounded seven-page crawl with public DNS, robots, same-host URLs and no redirects."""
    site=public_web_url(website)
    evidence={"email":"","source_url":"","source_type":"","confidence":0,
        "pages_scanned":0,"status":"no_official_site" if not site else "not_found",
        "last_crawled_at":dt.datetime.now(dt.timezone.utc).isoformat()}
    if not site:return evidence
    class NoRedirect(request.HTTPRedirectHandler):
        def redirect_request(self,req,fp,code,msg,headers,newurl):
            return None
    opener=request.build_opener(request.HTTPHandler(),request.HTTPSHandler(),NoRedirect)
    rules=robotparser.RobotFileParser()
    rules.set_url(site+"/robots.txt")
    try:
        req=request.Request(site+"/robots.txt",headers={"User-Agent":AGENT})
        with opener.open(req,timeout=7) as res:
            if int(res.headers.get("Content-Length","0"))>200000:return {**evidence,"status":"blocked"}
            robots=res.read(200000).decode("utf-8","replace").splitlines()
        rules.parse(robots)
    except error.HTTPError as exc:
        if exc.code==404:rules.parse([])
        else:return {**evidence,"status":"blocked"}
    except (OSError,ValueError):
        return {**evidence,"status":"blocked"}
    host=parse.urlsplit(site).hostname
    queue=deque([site+"/"])
    queued=set(queue)
    found=[]
    candidate_cnpjs=set()
    blocked=0
    eligible=0
    while queue and evidence["pages_scanned"]<MAX_CRAWL_PAGES:
        url=queue.popleft()
        if not rules.can_fetch(AGENT,url):
            blocked+=1
            continue
        eligible+=1
        if not public_web_url(url):
            blocked+=1
            continue
        try:
            req=request.Request(url,headers={"User-Agent":AGENT,"Accept":"text/html"},method="GET")
            with opener.open(req,timeout=9) as res:
                final=parse.urlsplit(res.geturl())
                if final.scheme!="https" or final.hostname!=host:continue
                if "text/html" not in res.headers.get("Content-Type",""):continue
                if int(res.headers.get("Content-Length","0"))>350000:continue
                html=res.read(350000).decode("utf-8","replace")
            evidence["pages_scanned"]+=1
            parser=MailtoParser(host or "")
            parser.feed(html)
            if url==site+"/" or "/contato" in url or "/contact" in url:
                candidate_cnpjs.update(parser.cnpjs)
            for email,method in parser.evidence:
                confidence=email_score(email,method,url,site)
                if confidence>=65:
                    found.append((confidence,method,email,url))
            for href in sorted(parser.links):
                if len(queued)>=18:break
                candidate=parse.urljoin(site+"/",href)
                parsed=parse.urlsplit(candidate)
                if parsed.scheme!="https" or parsed.hostname!=host or parsed.query:
                    continue
                path=parsed.path.rstrip("/") or "/"
                if path=="/" or not any(hint in path.lower() for hint in CONTACT_HINTS):
                    continue
                canonical=site+path
                if canonical not in queued:
                    queued.add(canonical)
                    queue.append(canonical)
            if evidence["pages_scanned"]==1:
                for p in COMMON_PAGES:
                    if len(queued)>=18:break
                    canonical=site+p
                    if canonical not in queued:queued.add(canonical);queue.append(canonical)
        except (OSError,ValueError,error.HTTPError,UnicodeError):
            pass
        time.sleep(DELAY)
    if not found and os.getenv("DISCOVERY_COUNTRY","US")=="BR":
        state=os.getenv("DISCOVERY_STATES","").split(",")[0]
        city=os.getenv("DISCOVERY_CITY","").strip()
        for cnpj in list(sorted(candidate_cnpjs))[:2]:
            registry=public_company_email(cnpj,host or "",state,city)
            if registry:
                found.append((registry["confidence"],"registry",
                              registry["email"],registry["source_url"]))
                evidence["public_cnpj"]=cnpj
                break
    if found:
        best=max(found,key=lambda t:(t[0],t[1]=="mailto"))
        evidence.update({"email":best[2],"confidence":best[0],
          "source_type":best[1],"source_url":best[3]})
    evidence["status"]=scanner_status(site,bool(found),evidence["pages_scanned"],eligible,blocked)
    return evidence

def find_public_email(website):
    """Compatibility wrapper for existing approved site-enrichment flows."""
    result=find_public_contact(website)
    return result["email"],result["source_url"]


IGNORE_WORDS={"the","and","for","of","medical","clinic","group","center","centre",
 "health","healthcare","dental","dermatology","practice","associates","llc","inc","pc","pa",
 "care","specialist","specialists","home","advanced","family","pediatric","community",
 "hospital","providers","services","service","health","urgent","association","ave","avenue"}
def possible_official_site(name, result):
    """A matching page title alone is not evidence of ownership.
    Require a distinctive name token both in the title and in the website's own hostname,
    rejecting unrelated chain clinics and third-party business directories.
    """
    title=str(result.get("title") or "").lower()
    domain=str(result.get("url") or "")
    try:
        hostname=parse.urlsplit(domain).hostname or ""
        label=hostname.lower().removeprefix("www.").split(".")[0]
    except ValueError:
        return ""
    tokens=set(re.findall(r"[a-z0-9]{3,}",name.lower()))-IGNORE_WORDS
    meaningful=[w for w in tokens if len(w)>=4 and not w.isdigit()]
    if not meaningful:return ""
    if not any(token in title and token in label for token in meaningful):
        return ""
    return public_web_url(domain) or ""

def tavily_site_details(name,city,state):
    key=os.getenv("TAVILY_API_KEY","")
    if not key:return "", {}
    query='"'+name[:90]+'" '+city[:50]+' '+state[:2]+' official clinic website'
    result=fetch_json("https://api.tavily.com/search",{
       "query":query,"search_depth":"basic","max_results":5,"topic":"general",
       "include_answer":False,"include_raw_content":False
    },{"Authorization":"Bearer "+key})
    for item in result.get("results",[]):
        site=possible_official_site(name,item)
        if site:
            evidence=find_public_contact(site)
            return site,evidence
    return "", {}

STATE_SEARCH_CITIES={
 "AL":"Birmingham","AK":"Anchorage","AZ":"Phoenix","AR":"Little Rock",
 "CA":"Los Angeles","CO":"Denver","CT":"Hartford","DE":"Wilmington",
 "FL":"Miami","GA":"Atlanta","HI":"Honolulu","ID":"Boise",
 "IL":"Chicago","IN":"Indianapolis","IA":"Des Moines","KS":"Wichita",
 "KY":"Louisville","LA":"New Orleans","ME":"Portland","MD":"Baltimore",
 "MA":"Boston","MI":"Detroit","MN":"Minneapolis","MS":"Jackson",
 "MO":"St Louis","MT":"Billings","NE":"Omaha","NV":"Las Vegas",
 "NH":"Manchester","NJ":"Newark","NM":"Albuquerque","NY":"New York",
 "NC":"Charlotte","ND":"Fargo","OH":"Columbus","OK":"Oklahoma City",
 "OR":"Portland","PA":"Philadelphia","RI":"Providence","SC":"Charleston",
 "SD":"Sioux Falls","TN":"Nashville","TX":"Houston","UT":"Salt Lake City",
 "VT":"Burlington","VA":"Richmond","WA":"Seattle","WV":"Charleston",
 "WI":"Milwaukee","WY":"Cheyenne"
}
def clinic_search_query(state,keyword,variant=0):
    city=os.getenv("DISCOVERY_CITY","").strip() or STATE_SEARCH_CITIES.get(state,"")
    country=os.getenv("DISCOVERY_COUNTRY","US").strip().upper()
    specialty=keyword.replace("_"," ")
    index=int(os.getenv("DISCOVERY_SPECIALTY_INDEX","-1"))
    if 0<=index<TOTAL_SPECIALTIES:
        query=search_phrases(country,index)[variant%2]
    elif country=="BR":
        query=f"{specialty} médicos clínicas consultórios site oficial contato email"
    else:
        query=f"{specialty} physician clinics medical practice official website contact"
    return query+" "+city+" "+state+(" Brasil" if country=="BR" else " United States")

def public_site_candidates(items,city,state,country,specialty):
    """Validate independently published clinic sites; ignore search snippets as email evidence."""
    rows=[]
    seen=set()
    for item in items:
        title=str(item.get("title") or "").strip()
        parts=[name.strip() for name in re.split(r"\s+[|–—-]\s+",title)]
        generic={"contact","contact us","home","about","about us","locations","services","appointments"}
        title_main=next((name for name in parts if name.casefold() not in generic and 5<=len(name)<=150),"")
        if len(title_main)<5 or len(title_main)>150:continue
        # Reject directories even if a future URL-normalization helper is relaxed.
        if not eligible_domain(parse.urlsplit(str(item.get("url") or "")).hostname):continue
        site=possible_official_site(title,item)
        if not site or site in seen:continue
        # A directory or unrelated commercial page is not an official practice.
        context=(title+" "+str(item.get("content") or "")[:350]).lower()
        if not any(word in context for word in ("doctor","physician","clinic","dermatol",
          "cardiol","hospital","medical","health","patient","practice","pediatric",
          "neurolog","orthop","medicine","psychiatr","obstetric",
          "clínica","clinica","médic","medic","consultório","consultorio","saúde","saude",
          "ginecolog","odontolog","pediatr","nutrition","dietitian","nutritionist",
          "therap","psycholog","dentist","urolog","endocrin","gastroenter",
          "nutric","psicolog","terapia","fisioterap","laborator","imagem","sonografia",
          "cirurgia","chirurg","reabilita","hospitalar","intervencion")):
            continue
        seen.add(site)
        evidence=find_public_contact(site)
        rows.append({
          "source_name":"website",
          "source_key":parse.urlsplit(site).hostname[:145],
          "company_name":title_main[:160],
          "contact_name":"","phone":"","website":site,
          "business_email":evidence.get("email",""),
          "city":city,"state":state,"country_code":country,"specialty":specialty[:100],
          "source_url":site+"/",
          "site_confidence":75,
          "email_confidence":evidence.get("confidence",0),
          "email_source_url":evidence.get("source_url",""),
          "email_source_type":evidence.get("source_type",""),
          "crawl_status":evidence.get("status","not_found"),
          "pages_scanned":evidence.get("pages_scanned",0),
          "last_crawled_at":evidence.get("last_crawled_at"),
          "note":("Empresa pesquisada em site oficial. CNPJ público confirmado: "+evidence["public_cnpj"]+". "
                  if evidence.get("public_cnpj") else "")+
                 "Confirme a identidade e o contato comercial antes de importar ao CRM."
        })
    return rows

def tavily_clinic_sites(state,keyword,limit=20,variant=0):
    key=os.getenv("TAVILY_API_KEY","")
    if not key:return []
    city=os.getenv("DISCOVERY_CITY","").strip() or STATE_SEARCH_CITIES.get(state,"")
    country=os.getenv("DISCOVERY_COUNTRY","US").strip().upper()
    query=clinic_search_query(state,keyword,variant)
    result=fetch_json("https://api.tavily.com/search",{
       "query":query,"search_depth":"basic","max_results":min(limit,20),
       "topic":"general","include_answer":False,"include_raw_content":False
    },{"Authorization":"Bearer "+key})
    return public_site_candidates(result.get("results",[]),city,state,country,keyword.replace("_"," "))

def tavily_site_for(name,city,state):
    """Legacy two-value helper retained for manually enriching staged leads."""
    site,evidence=tavily_site_details(name,city,state)
    return site,evidence.get("email","")

def nppes_records(state, keyword, limit=50):
    specialties = {
        "dental":"Dentist", "dermatology":"Dermatology",
        "medical":"Clinic/Center", "orthopedic":"Orthopaedic Surgery",
        "pediatrics":"Pediatrics", "cardiology":"Cardiovascular Disease",
        "hospital":"General Acute Care Hospital"
    }
    specialty = specialties.get(keyword.lower(), keyword)
    args = parse.urlencode({"version":"2.1","enumeration_type":"NPI-2",
        "taxonomy_description":specialty+"*","state":state,
        **({"city":os.getenv("DISCOVERY_CITY","").strip()} if os.getenv("DISCOVERY_CITY") else {}),
        "limit":min(limit,100)})
    result = fetch_json("https://npiregistry.cms.hhs.gov/api/?" + args)
    for item in result.get("results", []):
        info = item.get("basic") or {}
        name = str(info.get("organization_name") or "").strip()
        if not name: continue
        # Filter enterprises unlikely to need a clinic website or medical marketing.
        if re.search(r"\b(PHARMACY|PHARMACEUTICAL|BILLING|DISTRIBUTOR|SUPPLIES|MEDICAL EQUIPMENT|WAREHOUSE)\b",name,re.I):
            continue
        addresses = item.get("addresses") or []
        location = next((x for x in addresses if x.get("address_purpose")=="LOCATION"), addresses[0] if addresses else {})
        npi = str(item.get("number") or "")
        if not npi.isdigit(): continue
        yield {
            "source_name":"nppes","source_key":npi,"company_name":name[:160],
            "contact_name":"","business_email":"","website":"",
            "city":str(location.get("city") or "")[:100],
            "state":str(location.get("state") or state)[:10],
            "specialty":specialty[:100],
            "source_url":"https://npiregistry.cms.hhs.gov/provider-view/"+npi,
            "note":"CMS NPPES organization (NPI-2); no marketing email or opt-in supplied."
        }

def nppes_physicians(state, keyword, limit=60):
    """NPI-1 licensed physician search. Collect practice city/state only, never private data."""
    taxonomy={
        "dermatology":"Dermatology", "cardiology":"Cardiovascular Disease",
        "neurology":"Neurology", "pediatrics":"Pediatrics",
        "orthopedic":"Orthopaedic Surgery", "family_medicine":"Family Medicine",
        "internal_medicine":"Internal Medicine", "psychiatry":"Psychiatry",
        "obstetrics":"Obstetrics & Gynecology", "general_surgery":"Surgery"
    }.get(keyword.lower(),keyword.replace("_"," "))
    qs=parse.urlencode({"version":"2.1","enumeration_type":"NPI-1",
        "taxonomy_description":taxonomy+"*","state":state,
        **({"city":os.getenv("DISCOVERY_CITY","").strip()} if os.getenv("DISCOVERY_CITY") else {}),
        "limit":min(limit,100)})
    result=fetch_json("https://npiregistry.cms.hhs.gov/api/?"+qs)
    for item in result.get("results",[]):
        basic=item.get("basic") or {}
        credential=str(basic.get("credential") or "").upper()
        types=item.get("taxonomies") or []
        # Physician taxonomy 207/208; do not collect allied professionals or nurse practitioners.
        if not any(str(t.get("code","")).startswith(("207","208")) for t in types):
            continue
        if str(basic.get("status","A")) not in ("A",""):continue
        first=str(basic.get("first_name") or "").strip()
        last=str(basic.get("last_name") or "").strip()
        if not first or not last:continue
        address=next((x for x in item.get("addresses",[])
          if x.get("address_purpose")=="LOCATION" and x.get("city") and x.get("state")),None)
        if not address:continue
        npi=str(item.get("number") or "")
        if not npi.isdigit():continue
        name="Dr. "+first.title()+" "+last.title()
        yield {
            "source_name":"nppes","source_key":npi,"company_name":name[:160],
            "contact_name":name[:120],"business_email":"","website":"",
            "city":str(address["city"])[:100],"state":str(address["state"])[:10],
            "specialty":taxonomy[:100],
            "source_url":"https://npiregistry.cms.hhs.gov/provider-view/"+npi,
            "note":"NPI-1 public physician listing; practice city/state only. No personal email or marketing permission."
        }

def apollo_records(state, limit=50):
    key = os.getenv("APOLLO_API_KEY","")
    if not key or os.getenv("DISCOVERY_ENABLE_APOLLO","false").lower()!="true":
        return
    # Organization search is billed at 1 Apollo credit per page; opt-in only.
    payload = {"organization_locations[]":[state],
        "organization_industries[]":["hospital & health care"],"page":1,"per_page":min(limit,100)}
    result=fetch_json("https://api.apollo.io/api/v1/mixed_companies/search",
                      payload, {"X-Api-Key":key})
    for item in result.get("organizations",[]):
        identity = str(item.get("id") or "").strip()
        company = str(item.get("name") or "").strip()
        if not company or not identity: continue
        domain = str(item.get("primary_domain") or item.get("website_url") or "").strip()
        if domain.startswith("http"): website=domain
        elif eligible_domain(domain): website="https://"+domain
        else: website=""
        # Find only role mailboxes published on the practice's own site.
        email, source = find_public_email(website) if website else ("","")
        yield {
            "source_name":"apollo","source_key":identity[:150],"company_name":company[:160],
            "contact_name":"","business_email":email,"website":website[:450],
            "city":str(item.get("city") or "")[:100],"state":str(item.get("state") or state)[:10],
            "specialty":"healthcare","source_url":source or "https://app.apollo.io/",
            "note":"Apollo organization record + role mailbox from public official site. Not consent."
        }

def persist(row):
    """Only save actionable businesses with a verified published role mailbox."""
    email = str(row.get("business_email") or "").strip().lower()
    if not email or not EMAIL_RE.fullmatch(email):
        return False
    if not row.get("email_source_url") or int(row.get("email_confidence") or 0) < 65:
        return False
    row["business_email"] = email
    row["last_seen_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    result=pg("discovered_leads?on_conflict=source_name,source_key",row,
              prefer="resolution=ignore-duplicates,return=representation")
    return int(result.get("accepted",0))==1

def run():
    today=dt.date.today()
    state=STATES[today.toordinal()%len(STATES)] if STATES else "NY"
    kw=KEYWORDS[today.toordinal()%len(KEYWORDS)] if KEYWORDS else "dental"
    country=os.getenv("DISCOVERY_COUNTRY","US").strip().upper()
    city=os.getenv("DISCOVERY_CITY","").strip()
    target=os.getenv("DISCOVERY_TARGET","physicians").lower()
    count=0
    searched=0
    websites_found=0
    emails_found=0
    search_limit=min(max(int(os.getenv("DISCOVERY_MAX_SEARCHES","2")),0),10 if brave_available() else 3)
    record=pg("discovery_runs",{"source_name":"nppes/apollo","status":"running",
        "notes":"Geographic research: "+country+" / "+state+" / "+city+" / "+kw})
    job=record[0]["id"]
    try:
        # Use the documented Brave web API if configured, otherwise Tavily.
        # Brave can traverse up to ten API pages, not scraped Google Maps.
        if brave_available():
            query=clinic_search_query(state,kw,0)
            max_pages=min(10,search_limit)
            for page in range(max_pages):
                results,more=brave_page(query,country,page)
                searched+=1
                for website_row in public_site_candidates(results,city,state,country,kw.replace("_"," ")):
                    if persist(website_row):
                        count+=1
                        websites_found+=1
                        emails_found+=1
                    if count>=MAX_LEADS:break
                    time.sleep(DELAY)
                if not more or count>=MAX_LEADS:break
        elif os.getenv("TAVILY_API_KEY"):
            for variant in range(min(search_limit,2)):
                searched+=1
                try:
                    for website_row in tavily_clinic_sites(state,kw,limit=20,variant=variant):
                        if persist(website_row):
                            count+=1
                            websites_found+=1
                            emails_found+=1
                        if count>=MAX_LEADS:break
                        time.sleep(DELAY)
                except Exception as exc:
                    raise RuntimeError("Official site search unavailable: "+type(exc).__name__) from exc
                if count>=MAX_LEADS:break
        else:
            raise RuntimeError("Configure BRAVE_SEARCH_API_KEY or TAVILY_API_KEY for web discovery.")
        apollo_enabled = bool(os.getenv("APOLLO_API_KEY")) and os.getenv("DISCOVERY_ENABLE_APOLLO","false").lower()=="true"
        # Email-first: limit NPPES records with no website/email when official-site
        # research is enabled. Spend discovery effort on verifiable practice sites.
        nppes_budget=(max(2,min(10,MAX_LEADS//4)) if os.getenv("TAVILY_API_KEY")
                      else max(1,MAX_LEADS//2) if apollo_enabled else MAX_LEADS)
        individual_searches=0
        for source in (("nppes","apollo") if country=="US" and
                       os.getenv("DISCOVERY_ENABLE_NPPES","false").lower()=="true" else ()):
            stream=(nppes_physicians(state,kw,min(nppes_budget,80)) if target=="physicians"
                    else nppes_records(state,kw,min(nppes_budget,80))) if source=="nppes" else apollo_records(state,min(MAX_LEADS-nppes_budget,50))
            for row in stream:
                if (row["source_name"]=="nppes" and os.getenv("TAVILY_API_KEY")
                    and searched<search_limit and individual_searches<2):
                    searched+=1
                    individual_searches+=1
                    try:
                        official,evidence=tavily_site_details(row["company_name"],row["city"],row["state"])
                        if official:
                            websites_found+=1
                            row["website"]=official
                            row["site_confidence"]=88
                            row["business_email"]=evidence.get("email","")
                            # Count only after a candidate with an email is persisted.
                            row["email_confidence"]=evidence.get("confidence",0)
                            row["email_source_url"]=evidence.get("source_url","")
                            row["email_source_type"]=evidence.get("source_type","")
                            row["crawl_status"]=evidence.get("status","not_found")
                            row["pages_scanned"]=evidence.get("pages_scanned",0)
                            row["last_crawled_at"]=evidence.get("last_crawled_at")
                            row["note"]+=" Website candidate from Tavily; manual company identity verification required."
                        else:
                            row["crawl_status"]="no_official_site"
                    except Exception as e:
                        print("Optional site search failed:",type(e).__name__,file=sys.stderr)
                if persist(row):
                    count += 1
                    if row.get("business_email"): emails_found+=1
                if count >= MAX_LEADS: break
                time.sleep(DELAY)
            if count >= MAX_LEADS: break
        pg("discovery_runs?id=eq."+job,{"ended_at":dt.datetime.now(dt.timezone.utc).isoformat(),
            "status":"completed","collected":count,"enriched":websites_found,
            "notes":f"Official practice sites: {websites_found}; published role emails: {emails_found}"},method="PATCH")
    except Exception as exc:
        pg("discovery_runs?id=eq."+job,{"ended_at":dt.datetime.now(dt.timezone.utc).isoformat(),
            "status":"failed","collected":count,"notes":str(exc)[:300]},method="PATCH")
        raise
    print(json.dumps({"country":country,"city":city,"state":state,"keyword":kw,"saved":count,"websites_found":websites_found,"emails_found":emails_found,"site_search_queries":searched,"api_calls":session_calls}))

if __name__=="__main__":
    if not INGEST_URL or not (TOKEN or os.getenv("ACTIONS_ID_TOKEN_REQUEST_TOKEN")):
        sys.exit("Missing intake URL and signed Actions identity")
    run()
