"""Zero-search-credit local healthcare discovery with OpenStreetMap/Overpass.

This is an independent OSM source, NOT a claim to have scraped Google Maps.
Only one bounded geospatial query per city. OSM data: © OpenStreetMap contributors,
ODbL https://www.openstreetmap.org/copyright. A public business website must be
verified and the website itself must publish a contact email (or a verified
first-party CNPJ email) before the lead can enter the CRM import pipeline.
"""
import datetime as dt
import json
import os
import time
from urllib import request,parse,error

from daily_lead_discovery import (
    eligible_domain,public_web_url,find_public_contact,persist
)
from cnpj_enrichment import valid_cnpj,public_company_email

OSM_API="https://overpass-api.de/api/interpreter"
USER_AGENT="OnCreate-Healthcare-Discovery/1.0 (contact: oncreateagencia@gmail.com)"
MAX_SITES=22

def overpass_query(lat,lon,radius=8500):
    lat=float(lat);lon=float(lon)
    if not (-90<=lat<=90 and -180<=lon<=180):
        raise ValueError("City coordinates invalid")
    radius=max(1800,min(16000,int(radius)))
    center=f"{radius},{lat:.6f},{lon:.6f}"
    return (
      "[out:json][timeout:28];("
      f'nwr(around:{center})["healthcare"];'
      f'nwr(around:{center})["amenity"~"^(doctors|dentist|clinic|hospital)$"];'
      f'nwr(around:{center})["office"~"^(physician|therapist)$"];'
      ");out center 600;"
    )

def overpass_results(latitude,longitude):
    payload=parse.urlencode({"data":overpass_query(latitude,longitude)}).encode()
    req=request.Request(OSM_API,data=payload,method="POST",headers={
        "User-Agent":USER_AGENT,"Accept":"application/json",
        "Content-Type":"application/x-www-form-urlencoded"
    })
    try:
        with request.urlopen(req,timeout=38) as res:
            body=res.read(2800000)
            if len(body)>=2800000:raise RuntimeError("OSM city response too large")
            result=json.loads(body.decode("utf-8"))
    except error.HTTPError as exc:
        raise RuntimeError("Public OSM API unavailable: HTTP "+str(exc.code)) from exc
    if not isinstance(result.get("elements"),list):
        raise RuntimeError("OSM returned no element collection")
    return result["elements"]

def medical_candidates(elements):
    candidates=[]
    seen=set()
    for entry in elements:
        if len(candidates)>=MAX_SITES*3:break
        if not isinstance(entry,dict):continue
        tags=entry.get("tags") or {}
        if not isinstance(tags,dict):continue
        title=str(tags.get("name") or tags.get("name:pt") or "").strip()
        if len(title)<4 or len(title)>160:continue
        url=str(tags.get("contact:website") or tags.get("website") or "").strip()
        if url.startswith("http://"):url="https://"+url[7:]
        if not url.startswith("https://"):continue
        try:
            raw_host=parse.urlsplit(url).hostname
        except ValueError:
            continue
        if not eligible_domain(raw_host):continue
        # Verify public DNS and TLS host before following any external website.
        site=public_web_url(url)
        if not site or site in seen:continue
        seen.add(site)
        ident=entry.get("id")
        osm_type=entry.get("type")
        if not isinstance(ident,int) or osm_type not in ("node","way","relation"):
            continue
        specialty=str(tags.get("healthcare:speciality") or
                      tags.get("healthcare") or tags.get("amenity") or
                      "medical practice")[:100]
        candidates.append({
            "site":site,"name":title,"specialty":specialty,
            "source_url":f"https://www.openstreetmap.org/{osm_type}/{ident}",
            "cnpj":str(tags.get("ref:cnpj") or tags.get("cnpj") or "").strip()
        })
    return candidates

def scan_city(country,state,city,latitude,longitude):
    if country not in ("US","BR"):raise ValueError("Unsupported country")
    if len(state)!=2 or not city:raise ValueError("City and state required")
    elements=overpass_results(latitude,longitude)
    candidates=medical_candidates(elements)
    saved=0;checked=0
    for c in candidates[:MAX_SITES]:
        checked+=1
        evidence=find_public_contact(c["site"])
        if country=="BR" and not evidence.get("email") and valid_cnpj(c["cnpj"]):
            host=parse.urlsplit(c["site"]).hostname or ""
            registered=public_company_email(c["cnpj"],host,state,city)
            if registered:
                evidence.update(registered)
                evidence["status"]="found"
                evidence["public_cnpj"]=registered["cnpj"]
        if not evidence.get("email") or int(evidence.get("confidence") or 0)<65:
            continue
        row={
            "source_name":"website",
            "source_key":parse.urlsplit(c["site"]).hostname[:145],
            "company_name":c["name"],"contact_name":"","phone":"",
            "website":c["site"],"business_email":evidence["email"],
            "city":city,"state":state,"country_code":country,
            "specialty":c["specialty"],"source_url":c["source_url"],
            "site_confidence":80,
            "email_confidence":evidence["confidence"],
            "email_source_url":evidence["source_url"],
            "email_source_type":evidence["source_type"],
            "crawl_status":evidence.get("status","found"),
            "pages_scanned":evidence.get("pages_scanned",0),
            "last_crawled_at":evidence.get("last_crawled_at"),
            "note":"Empresa localizada em dados abertos OSM (© OpenStreetMap contributors). "
                   "Contato verificado no site oficial; revisão humana obrigatória antes do CRM."
        }
        if persist(row):saved+=1
        time.sleep(0.6)
    return {
        "saved":saved,"sites_found":len(candidates),"sites_checked":checked,
        "free_source_requests":1,"source":"openstreetmap_overpass"
    }

def main():
    country=os.getenv("DISCOVERY_COUNTRY","US").strip().upper()
    state=os.getenv("DISCOVERY_STATES","").strip().upper()
    city=os.getenv("DISCOVERY_CITY","").strip()
    latitude=float(os.environ["DISCOVERY_LATITUDE"])
    longitude=float(os.environ["DISCOVERY_LONGITUDE"])
    print(json.dumps(scan_city(country,state,city,latitude,longitude)),flush=True)

if __name__=="__main__":
    main()
