"""Low-cost public healthcare website discovery using Anthropic's official web_search.

Each call is bounded to ONE web_search tool use (currently US$0.01 per search)
plus Claude Haiku token costs. No HTML scraping of Google or Google Maps.
Search citations are lead CANDIDATES only: never trust model-generated mailboxes.
Only email addresses independently published on a verified first-party website
may reach the CRM discovery queue, with explicit human review before outreach.
"""
import datetime as dt
import json
import os
import re
import time
import unicodedata
from urllib import error, parse, request

from daily_lead_discovery import (
    eligible_domain, public_web_url, find_public_contact, persist
)
from claude_contact_review import triage_contact
from cnpj_enrichment import valid_cnpj, public_company_email

ENDPOINT="https://api.anthropic.com/v1/messages"
MODEL="claude-haiku-5-5"
MAX_SITES=4
UNTRUSTED_HOSTS={
    "facebook.com","instagram.com","linkedin.com","google.com",
    "youtube.com","tiktok.com","x.com","doctoralia.com.br",
    "zocdoc.com","yelp.com","healthgrades.com","webmd.com",
}
GENERIC={"clinic","clinica","clínica","medico","médico","medical","health",
         "healthcare","center","centre","group","grupo","hospital","doctor",
         "doutor","doutora","dermatologia","dermatology","consultorio",
         "consultório","instituto","institute","oficial","official",
         "home","welcome","site","web","the","and","for","de","da","do"}

def configured():
    return (os.getenv("DISCOVERY_SOURCE_MODE","FREE_ONLY")=="FREE_PLUS"
            and os.getenv("CLAUDE_WEB_SEARCH","false").lower()=="true"
            and bool(os.getenv("ANTHROPIC_API_KEY","").strip()))

def clean(value,cap=100):
    return " ".join(str(value or "").strip().split())[:cap]

def normalized(value):
    text=unicodedata.normalize("NFKD",str(value or ""))
    return "".join(c for c in text if not unicodedata.combining(c)).lower()

def official_candidate(entry):
    """Reject directory/aggregator URLs and names without distinct domain agreement."""
    if not isinstance(entry,dict) or entry.get("type")!="web_search_result":
        return None
    title=clean(entry.get("title"),180)
    url=str(entry.get("url") or "")[:600]
    try:
        u=parse.urlsplit(url)
        host=(u.hostname or "").lower().removeprefix("www.")
        if u.scheme!="https" or u.username or u.password or u.port or not eligible_domain(host):
            return None
        if any(host==x or host.endswith("."+x) for x in UNTRUSTED_HOSTS):
            return None
    except ValueError:
        return None
    tokens={w for w in re.findall(r"[a-z0-9]{4,}",normalized(title)) if w not in GENERIC}
    compact=re.sub(r"[^a-z0-9]","",normalized(host.split(".")[0]))
    matching=[t for t in tokens if t in compact]
    if not matching:
        return None
    # Hardcode no email, no speculative professional name.
    return {"name":title,"url":url,"host":host}

def search_results(country,state,city,specialty):
    if not configured():
        return {"sites":[],"search_requests":0,"input_tokens":0,"output_tokens":0}
    country=clean(country,2).upper()
    state=clean(state,2).upper()
    city=clean(city,75)
    specialty=clean(specialty,85)
    if country not in ("BR","US") or not re.fullmatch(r"[A-Z]{2}",state) or not city or not specialty:
        raise ValueError("Valid country/state/city/specialty required")
    locale="Brazil" if country=="BR" else "United States"
    query=(f"Search the current web for up to 6 official websites of medical clinics or "
           f"healthcare practices specializing in {specialty} in {city}, {state}, {locale}. "
           "Use web search at least once. Do not include directories, social networks, "
           "news sites or personal email addresses. Report only names and their official "
           "website URLs from actual search results. Do not invent anything.")
    payload={
        "model":MODEL,"max_tokens":420,
        "thinking":{"type":"disabled"},
        "output_config":{"effort":"low"},
        "tools":[{"type":"web_search_20250305","name":"web_search","max_uses":1}],
        "messages":[{"role":"user","content":query}],
    }
    req=request.Request(ENDPOINT,method="POST",data=json.dumps(payload).encode("utf-8"),
        headers={"x-api-key":os.environ["ANTHROPIC_API_KEY"],
                 "anthropic-version":"2023-06-01",
                 "content-type":"application/json",
                 "accept":"application/json"})
    try:
        with request.urlopen(req,timeout=38) as response:
            body=json.loads(response.read(350000).decode("utf-8"))
    except error.HTTPError as exc:
        # No secrets or prompt/results in errors and CI output.
        raise RuntimeError("Claude web search HTTP "+str(exc.code)) from None
    except (OSError,TimeoutError,ValueError) as exc:
        raise RuntimeError("Claude web search "+type(exc).__name__) from None
    usage=body.get("usage") or {}
    requests=int((usage.get("server_tool_use") or {}).get("web_search_requests") or 0)
    if requests>1:
        raise RuntimeError("Claude search exceeded per-call tool budget")
    sites=[]
    seen=set()
    for block in body.get("content") or []:
        if block.get("type")!="web_search_tool_result":continue
        results=block.get("content") or []
        if not isinstance(results,list):continue
        for entry in results[:20]:
            candidate=official_candidate(entry)
            if not candidate or candidate["host"] in seen:continue
            seen.add(candidate["host"])
            sites.append(candidate)
            if len(sites)>=MAX_SITES:break
        if len(sites)>=MAX_SITES:break
    return {"sites":sites,"search_requests":requests,
            "input_tokens":max(0,int(usage.get("input_tokens") or 0)),
            "output_tokens":max(0,int(usage.get("output_tokens") or 0))}

def scan_city(country,state,city,specialty):
    result=search_results(country,state,city,specialty)
    checked=0
    saved=0
    for c in result["sites"]:
        website=public_web_url(c["url"])
        if not website:continue
        checked+=1
        evidence=find_public_contact(website)
        if not evidence.get("email") and country=="BR" and valid_cnpj(evidence.get("public_cnpj","")):
            registration=public_company_email(evidence["public_cnpj"],c["host"],state,city)
            if registration:
                evidence.update(registration)
        email=str(evidence.get("email") or "").lower()
        host=(parse.urlsplit(website).hostname or "").removeprefix("www.")
        # Only first-party mailboxes; accountant, free personal and agent domains excluded.
        if email.rsplit("@",1)[-1]!=host or int(evidence.get("confidence") or 0)<75:
            continue
        verdict=triage_contact(c["name"],website,email,
                               evidence.get("source_url",""),evidence.get("source_type",""))
        if verdict=="needs_review":
            continue
        row={
            "source_name":"website",
            "source_key":host[:145],
            "company_name":c["name"][:160],
            "contact_name":"","phone":"",
            "business_email":email,"website":website,
            "city":city,"state":state,"country_code":country,
            "specialty":specialty[:100],
            "source_url":c["url"],"site_confidence":78,
            "email_confidence":int(evidence["confidence"]),
            "email_source_url":evidence["source_url"],
            "email_source_type":evidence["source_type"],
            "crawl_status":evidence.get("status","found"),
            "pages_scanned":int(evidence.get("pages_scanned") or 0),
            "last_crawled_at":evidence.get("last_crawled_at") or dt.datetime.now(dt.timezone.utc).isoformat(),
            "note":"Descoberta pelo Claude web search oficial (US$0.01 por pesquisa + tokens). "
                   "E-mail comercial confirmado diretamente no website. Revisar identidade "
                   "e intenção comercial antes de importar."
        }
        if persist(row):saved+=1
        time.sleep(0.4)
    input_tokens=result["input_tokens"]
    output_tokens=result["output_tokens"]
    billed=result["search_requests"]
    return {"saved":saved,"sites_found":len(result["sites"]),
            "sites_checked":checked,"search_requests":billed,
            "claude_web_input_tokens":input_tokens,
            "claude_web_output_tokens":output_tokens,
            "claude_web_estimated_usd":round(
                billed*.01 + input_tokens*.10/1_000_000 + output_tokens*.50/1_000_000,5),
            "source":"claude_official_web_search"}

def main():
    country=os.getenv("DISCOVERY_COUNTRY","US").strip().upper()
    state=os.getenv("DISCOVERY_STATES","").strip().upper()
    city=os.getenv("DISCOVERY_CITY","").strip()
    specialty=os.getenv("DISCOVERY_KEYWORDS","").strip()
    print(json.dumps(scan_city(country,state,city,specialty)),flush=True)

if __name__=="__main__":
    main()
