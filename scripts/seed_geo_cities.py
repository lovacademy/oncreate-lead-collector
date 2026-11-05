#!/usr/bin/env python3
"""Idempotently seed official/IBGE-coded cities without resetting coverage.
US: 2026 US Census Gazetteer Places (including CDPs, 50 states + DC).
BR: IBGE municipality codes with community-maintained centroid coordinates.
All DB writes use a short-lived signed GitHub Actions OIDC token.
"""
import csv
import io
import json
import re
import time
import zipfile
from urllib import request
from daily_lead_discovery import pg

US_CENSUS_ZIP=(
    "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/"
    "2026_Gazetteer/2026_Gaz_place_national.zip"
)
BR_CITIES="https://raw.githubusercontent.com/kelvins/municipios-brasileiros/master/csv/municipios.csv"
BR_STATES="https://raw.githubusercontent.com/kelvins/municipios-brasileiros/master/csv/estados.csv"

FIPS={
 "01":"AL","02":"AK","04":"AZ","05":"AR","06":"CA","08":"CO","09":"CT",
 "10":"DE","11":"DC","12":"FL","13":"GA","15":"HI","16":"ID","17":"IL",
 "18":"IN","19":"IA","20":"KS","21":"KY","22":"LA","23":"ME","24":"MD",
 "25":"MA","26":"MI","27":"MN","28":"MS","29":"MO","30":"MT","31":"NE",
 "32":"NV","33":"NH","34":"NJ","35":"NM","36":"NY","37":"NC","38":"ND",
 "39":"OH","40":"OK","41":"OR","42":"PA","44":"RI","45":"SC","46":"SD",
 "47":"TN","48":"TX","49":"UT","50":"VT","51":"VA","53":"WA","54":"WV",
 "55":"WI","56":"WY"
}
def download(url,timeout=65):
    req=request.Request(url,headers={
        "User-Agent":"OnCreate-Geography/1.0 public-source importer",
        "Accept":"application/octet-stream,text/csv,*/*"
    })
    for attempt in range(3):
        try:
            with request.urlopen(req,timeout=timeout) as response:
                return response.read(9_000_000)
        except Exception:
            if attempt==2:raise
            time.sleep(2**attempt)
    return b""

def census_places():
    archive=zipfile.ZipFile(io.BytesIO(download(US_CENSUS_ZIP)))
    txt=next((n for n in archive.namelist() if n.lower().endswith(".txt")),None)
    if not txt:raise RuntimeError("US Census 2026 place file was not found.")
    with archive.open(txt) as f:
        content=f.read().decode("utf-8-sig",errors="replace")
    rows=csv.DictReader(io.StringIO(content),delimiter="|")
    result=[]
    for row in rows:
        row={str(k).strip().upper():str(v or "").strip() for k,v in row.items()}
        geoid=row.get("GEOID","")
        if len(geoid)<7 or geoid[:2] not in FIPS:continue
        lat,lon = row.get("INTPTLAT",""),row.get("INTPTLONG","")
        try:latitude=float(lat);longitude=float(lon)
        except (TypeError,ValueError):continue
        raw_name=row.get("NAME","").strip()
        city=re.sub(r" (city|town|village|CDP|borough|municipality|urbana|urbanized area)$",
            "",raw_name,flags=re.I).strip()
        if not city:continue
        result.append({
            "country_code":"US","state_code":FIPS[geoid[:2]],
            "source_city_id":geoid,"city_name":city[:120],
            "latitude":latitude,"longitude":longitude
        })
    if len(result)<15000:raise RuntimeError("US Census cities incomplete: "+str(len(result)))
    return result

def brazil_municipalities():
    states={row["codigo_uf"]:row["uf"] for row in
            csv.DictReader(io.StringIO(download(BR_STATES).decode("utf-8-sig")))}
    content=download(BR_CITIES).decode("utf-8-sig")
    result=[]
    for row in csv.DictReader(io.StringIO(content)):
        state=states.get(row["codigo_uf"],"")
        if not re.fullmatch(r"[A-Z]{2}",state):continue
        try:latitude=float(row["latitude"]);longitude=float(row["longitude"])
        except (ValueError,TypeError):continue
        result.append({
            "country_code":"BR","state_code":state,
            "source_city_id":row["codigo_ibge"],"city_name":row["nome"][:120],
            "latitude":latitude,"longitude":longitude
        })
    if len(result)<5500:raise RuntimeError("Brazil IBGE city catalog incomplete: "+str(len(result)))
    return result

def seed():
    before=pg("collection_control",{"action":"geo_regions"})
    counts={"US":0,"BR":0}
    for region in before["regions"]:
        country=region["country_code"]
        counts[country]=counts.get(country,0)+int(region["total_cities"])
    for country,cities in (("US",census_places()),("BR",brazil_municipalities())):
        print(json.dumps({"country":country,"listed":len(cities),"stored":counts[country]}),flush=True)
        if counts[country]>=len(cities):
            print("Catalog already complete; existing geographic progress retained.",flush=True)
            continue
        for i in range(0,len(cities),120):
            batch=cities[i:i+120]
            result=pg("collection_control",{"action":"geo_seed","cities":batch})
            if int(result.get("accepted") or 0)!=len(batch):
                raise RuntimeError("Unexpected geographic seed response")
            if (i//120)%20==0:
                print(json.dumps({"country":country,"seeded_at_least":i+len(batch)}),flush=True)
        after=pg("collection_control",{"action":"geo_regions"})
        loaded=sum(int(r["total_cities"]) for r in after["regions"] if r["country_code"]==country)
        if loaded<len(cities):raise RuntimeError("Catalog incomplete for "+country)
        print(json.dumps({"country":country,"verified_cities":loaded}),flush=True)

if __name__=="__main__":
    seed()
