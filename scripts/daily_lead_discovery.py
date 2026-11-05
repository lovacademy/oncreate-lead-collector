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
from html import unescape
from html.parser import HTMLParser

DENIED = ("zocdoc.com", "tebra.com", "ama-assn.org", "google.com", "bing.com")
EMAIL_RE = re.compile(r"^[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}$", re.I)
ROLE_RE = re.compile(r"^(info|contact|hello|office|frontdesk|admin|team|reception|appointments|support)@", re.I)
EMAIL_LINK_RE = re.compile(r"mailto:([a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,})", re.I)
AGENT = "OnCreate-Lead-Research/1.0 (public contact page review)"
MAX_LEADS = min(max(int(os.getenv("DISCOVERY_MAX_LEADS", "80")), 1), 250)
DELAY = max(float(os.getenv("DISCOVERY_DELAY_SECONDS", "3")), 2.0)
STATES = [s.strip().upper() for s in os.getenv("DISCOVERY_STATES", "NY,CA,FL,TX,MA").split(",") if re.fullmatch(r"[A-Za-z]{2}", s.strip())]
KEYWORDS = [s.strip() for s in os.getenv("DISCOVERY_KEYWORDS", "dental,dermatology,medical").split(",") if re.fullmatch(r"[A-Za-z ]{3,35}", s.strip())]
INGEST_URL = os.getenv("ONCREATE_INGEST_URL", "").strip()
TOKEN = os.getenv("ONCREATE_INGEST_TOKEN", "").strip()
session_calls = 0

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
    if not INGEST_URL.startswith("https://") or not TOKEN:
        raise RuntimeError("ONCREATE_INGEST_URL and ONCREATE_INGEST_TOKEN are required")
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
    else:
        raise RuntimeError("Collector attempted an unsupported database operation")
    body = json.dumps(req_body).encode("utf-8")
    req = request.Request(INGEST_URL,method="POST",data=body,headers={
        "Content-Type":"application/json","X-Collector-Token":TOKEN,
        "User-Agent":AGENT})
    with request.urlopen(req,timeout=20) as rsp:
        raw=rsp.read(100000).decode("utf-8")
    result=json.loads(raw) if raw else {}
    if req_body["action"]=="run_start":
        if not result.get("id"):raise RuntimeError("The intake endpoint did not create a run")
        return [{"id":result["id"]}]
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
    def __init__(self):
        super().__init__()
        self.emails = set()
    def handle_starttag(self, tag, attrs):
        if tag != "a": return
        href = dict(attrs).get("href", "")
        for m in EMAIL_LINK_RE.finditer(unescape(href)):
            email = m.group(1).lower()
            if EMAIL_RE.fullmatch(email) and ROLE_RE.match(email):
                self.emails.add(email)

def find_public_email(website):
    site = public_web_url(website)
    if not site: return "", ""
    class BlockRedirect(request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None
    opener = request.build_opener(request.HTTPHandler(), request.HTTPSHandler(), BlockRedirect)
    rules = robotparser.RobotFileParser()
    rules.set_url(site + "/robots.txt")
    try:
        req = request.Request(site + "/robots.txt", headers={"User-Agent": AGENT})
        with opener.open(req, timeout=6) as response:
            lines = response.read(250000).decode("utf-8","replace").splitlines()
        rules.parse(lines)
    except error.HTTPError as exc:
        if exc.code == 404:
            rules.parse([])
        else:
            return "", ""
    except Exception:
        return "", ""  # Fail closed if the site's robots rules are unavailable.
    for path in ("/", "/contact", "/contact-us", "/about"):
        url = site + path
        if not rules.can_fetch(AGENT, url): continue
        try:
            req = request.Request(url, headers={"User-Agent": AGENT, "Accept": "text/html"}, method="GET")
            with opener.open(req, timeout=8) as res:
                # Refuse cross-domain redirects and non-HTML.
                final = parse.urlsplit(res.geturl())
                if final.scheme != "https" or final.hostname != parse.urlsplit(site).hostname:
                    continue
                if "text/html" not in res.headers.get("Content-Type", ""): continue
                if int(res.headers.get("Content-Length", "0")) > 350_000: continue
                html = res.read(350_000).decode("utf-8", "replace")
            parser = MailtoParser()
            parser.feed(html)
            if parser.emails:
                return sorted(parser.emails)[0], url
        except (OSError, ValueError, error.HTTPError):
            pass
        time.sleep(DELAY)
    return "", ""


IGNORE_WORDS={"the","and","for","of","medical","clinic","group","center","centre",
 "health","healthcare","dental","dermatology","practice","associates","llc","inc","pc","pa"}
def possible_official_site(name, result):
    title=str(result.get("title") or "")
    words=set(re.findall(r"[a-z]{4,}",name.lower()))-IGNORE_WORDS
    title_words=set(re.findall(r"[a-z]{4,}",title.lower()))
    if not words or len(words & title_words)<min(2,len(words)):
        return ""
    website=str(result.get("url") or "")
    return public_web_url(website) or ""

def tavily_site_for(name, city, state):
    key=os.getenv("TAVILY_API_KEY","")
    if not key:return "", ""
    query='"'+name[:90]+'" '+city[:50]+' '+state[:2]+' official practice website'
    result=fetch_json("https://api.tavily.com/search",{
       "query":query,"search_depth":"basic","max_results":5,"topic":"general",
       "include_answer":False,"include_raw_content":False
    },{"Authorization":"Bearer "+key})
    for item in result.get("results",[]):
        site=possible_official_site(name,item)
        if site:
            email,source=find_public_email(site)
            return site,email
    return "", ""

def nppes_records(state, keyword, limit=50):
    specialties = {
        "dental":"Dentist", "dermatology":"Dermatology",
        "medical":"Clinic/Center", "orthopedic":"Orthopaedic Surgery",
        "pediatrics":"Pediatrics", "cardiology":"Cardiovascular Disease"
    }
    specialty = specialties.get(keyword.lower(), keyword)
    args = parse.urlencode({"version":"2.1","enumeration_type":"NPI-2",
        "taxonomy_description":specialty+"*","state":state,"limit":min(limit,100)})
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
    row["last_seen_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    pg("discovered_leads?on_conflict=source_name,source_key",row,prefer="resolution=merge-duplicates,return=minimal")

def run():
    today=dt.date.today()
    state=STATES[today.toordinal()%len(STATES)] if STATES else "NY"
    kw=KEYWORDS[today.toordinal()%len(KEYWORDS)] if KEYWORDS else "dental"
    count=0
    searched=0
    websites_found=0
    search_limit=min(max(int(os.getenv("DISCOVERY_MAX_SEARCHES","15")),0),20)
    record=pg("discovery_runs",{"source_name":"nppes/apollo","status":"running",
        "notes":"Daily bounded job: "+state+" / "+kw})
    job=record[0]["id"]
    try:
        apollo_enabled = bool(os.getenv("APOLLO_API_KEY")) and os.getenv("DISCOVERY_ENABLE_APOLLO","false").lower()=="true"
        nppes_budget=max(1,MAX_LEADS//2) if apollo_enabled else MAX_LEADS
        for source in ("nppes","apollo"):
            stream=nppes_records(state,kw,min(nppes_budget,80)) if source=="nppes" else apollo_records(state,min(MAX_LEADS-nppes_budget,50))
            for row in stream:
                if (row["source_name"]=="nppes" and os.getenv("TAVILY_API_KEY") and searched<search_limit):
                    searched+=1
                    try:
                        official,email=tavily_site_for(row["company_name"],row["city"],row["state"])
                        if official:
                            websites_found+=1
                            row["website"]=official
                            row["business_email"]=email
                            row["note"]+=" Website candidate from a search API; verify official identity before outreach."
                    except Exception as e:
                        print("Optional site search failed:",type(e).__name__,file=sys.stderr)
                persist(row)
                count += 1
                if count >= MAX_LEADS: break
                time.sleep(DELAY)
            if count >= MAX_LEADS: break
        pg("discovery_runs?id=eq."+job,{"ended_at":dt.datetime.now(dt.timezone.utc).isoformat(),
            "status":"completed","collected":count,"enriched":websites_found},method="PATCH")
    except Exception as exc:
        pg("discovery_runs?id=eq."+job,{"ended_at":dt.datetime.now(dt.timezone.utc).isoformat(),
            "status":"failed","collected":count,"notes":str(exc)[:300]},method="PATCH")
        raise
    print(json.dumps({"state":state,"keyword":kw,"saved":count,"websites_found":websites_found,"site_search_queries":searched,"api_calls":session_calls}))

if __name__=="__main__":
    if not INGEST_URL or not TOKEN: sys.exit("Missing ONCREATE_INGEST_URL or ONCREATE_INGEST_TOKEN")
    run()
