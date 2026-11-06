#!/usr/bin/env python3
"""Run bounded public API discovery across states while continuously checkpointing to Supabase.

The runner may execute for up to 6h, but the collector stops early when limits or
source coverage are exhausted. No intentional idle compute to fill the time cap.
"""
import datetime as dt
import itertools
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from daily_lead_discovery import pg as intake
from seed_geo_cities import seed as seed_geography

# Versioned bilingual catalog: preserve previous six pass positions for each country.
from specialties import TOTAL_SPECIALTIES,US_SPECIALTIES,BR_SPECIALTIES,specialty_at

MAX_MINUTES=max(10,min(340,int(os.environ.get("MAX_RUNTIME_MINUTES","180"))))
MAX_TOTAL=max(25,min(12000,int(os.environ.get("MAX_DAILY_CANDIDATES","3000"))))
MAX_ROUND=max(10,min(100,int(os.environ.get("DISCOVERY_ROUND_CANDIDATES","80"))))
SEARCHES=max(2,min(500,int(os.environ.get("DISCOVERY_DAILY_SEARCH_CREDITS","80"))))
MONTHLY_SEARCH_BUDGET=max(50,min(1000,int(os.environ.get("DISCOVERY_MONTHLY_SEARCH_CREDITS","900"))))
SCRIPT=Path(__file__).parent/"daily_lead_discovery.py"
OSM_SCRIPT=Path(__file__).parent/"osm_discovery.py"
OSM_CITY_LIMIT=max(1,min(12,int(os.environ.get("DISCOVERY_OSM_CITY_LIMIT","8"))))

PRIORITY_STATES={
    "US":("CA","TX","FL","NY","IL","GA","MA","WA","PA","NC","AZ","CO"),
    "BR":("SP","RJ","MG","PR","RS","DF","SC","PE","BA","CE","GO","AM")
}
def region_queue(regions,country_mode):
    """Prioritize metro medical markets while rotating across states and countries."""
    grouped={}
    for country in ("US","BR"):
        places=[
            r for r in regions if r["country_code"]==country and
            int(r["completed_cities"])<int(r["total_cities"])
        ]
        prioritized=PRIORITY_STATES[country]
        places.sort(key=lambda r:(
            0 if r["state_code"] in prioritized else 1,
            prioritized.index(r["state_code"]) if r["state_code"] in prioritized else 100,
            -int(r["searched_specialties"]),r["state_code"]
        ))
        grouped[country]=places
    if country_mode=="US":
        return grouped["US"]
    if country_mode=="BR":
        return grouped["BR"]
    # Alternation avoids spending all credits in one country.
    result=[]
    for us,br in itertools.zip_longest(grouped["US"],grouped["BR"]):
        if us:result.append(us)
        if br:result.append(br)
    return result

def may_spend_search_credits(source_mode,brave_key,tavily_key):
    """Only an explicit FREE_PLUS job may use any metered search provider."""
    return source_mode=="FREE_PLUS" and bool(brave_key or tavily_key)

def main():
    mode=os.getenv("COLLECTION_MODE","poll").lower()
    if mode not in ("poll","push","scheduled"):
        raise RuntimeError("Unrecognized collection trigger")
    run_id=os.getenv("GITHUB_RUN_ID","")
    repo=os.getenv("GITHUB_REPOSITORY","lovacademy/oncreate-lead-collector")
    run_url=("https://github.com/"+repo+"/actions/runs/"+run_id) if run_id.isdecimal() else ""
    claim=intake("collection_control",{
        "action":"collection_claim","mode":mode,
        "max_runtime_minutes":MAX_MINUTES,"github_run_url":run_url
    })
    job=claim.get("job")
    if not job:
        print(json.dumps({"job":"no_pending_request","busy":claim.get("busy",False)}),flush=True)
        return
    job_id=job["id"]
    country_mode=job.get("country_mode","BOTH")
    source_mode=job.get("source_mode","FREE_ONLY")
    max_minutes=min(MAX_MINUTES,int(job.get("max_runtime_minutes") or MAX_MINUTES))
    start=time.monotonic()
    deadline=start+max_minutes*60
    count=0;rounds=0;searched=0;free_scans=0;errors=0
    status="completed";notes=""
    current_region=""

    def progress(final=False):
        payload={
            "action":"collection_complete" if final else "collection_progress",
            "id":job_id,"candidates_found":count,"rounds_completed":rounds,
            "search_queries":searched,"free_source_scans":free_scans,"error_count":errors,
            "notes":notes,"status":status
        }
        result=intake("collection_control",payload)
        if not result.get("ok"):
            raise RuntimeError("Collection heartbeat was not accepted")

    try:
        use_brave=bool(os.getenv("BRAVE_SEARCH_API_KEY"))
        use_paid=may_spend_search_credits(source_mode,os.getenv("BRAVE_SEARCH_API_KEY"),os.getenv("TAVILY_API_KEY"))
        seed_geography()
        # Independent no-credit geographic discovery through permissively licensed
        # OpenStreetMap data. Do not count OSM scans as 153 specialty checks.
        geo_regions=intake("collection_control",{
            "action":"geo_regions","job_id":job_id
        })["regions"]
        free_regions=region_queue(geo_regions,country_mode)
        source_regions={c:[x for x in free_regions if x["country_code"]==c]
                        for c in ("US","BR")}
        source_countries=["US","BR"] if country_mode=="BOTH" else [country_mode]
        osm_failures=0
        for idx in range(OSM_CITY_LIMIT):
            if time.monotonic()>deadline-180 or not any(source_regions.values()):
                break
            country=source_countries[idx%len(source_countries)]
            options=source_regions[country]
            if not options:continue
            region=options.pop(0)
            options.append(region)
            candidate=intake("collection_control",{
                "action":"geo_osm_next","job_id":job_id,
                "country_code":country,"state_code":region["state_code"]
            }).get("city")
            if not candidate:
                options.pop()
                continue
            current_region=country+" / "+region["state_code"]+" / "+candidate["city_name"]+" / OSM"
            env=os.environ.copy()
            env.update({
                "DISCOVERY_COUNTRY":country,"DISCOVERY_CITY":candidate["city_name"],
                "DISCOVERY_STATES":region["state_code"],
                "DISCOVERY_LATITUDE":str(candidate["latitude"]),
                "DISCOVERY_LONGITUDE":str(candidate["longitude"])
            })
            try:
                result=subprocess.run([sys.executable,str(OSM_SCRIPT)],env=env,
                    timeout=min(190,max(35,int(deadline-time.monotonic()-20))),
                    capture_output=True,text=True)
                if result.returncode!=0:
                    raise RuntimeError(result.stderr[-200:] or "OSM scan failed")
                payload=json.loads(result.stdout.strip().splitlines()[-1])
                found=int(payload.get("saved") or 0)
                ack=intake("collection_control",{
                    "action":"geo_osm_mark","job_id":job_id,
                    "city_id":candidate["id"],"succeeded":True,"found_emails":found
                })
                if not ack.get("ok"):raise RuntimeError("OSM checkpoint rejected")
                free_scans+=1
                count+=found
                notes=("Fonte gratuita OSM • "+current_region+
                      " • "+str(found)+" novos e-mails validados")[:350]
                progress()
                osm_failures=0
            except Exception as exc:
                errors+=1;osm_failures+=1
                msg=str(exc)[:225]
                notes=("Fonte OSM temporariamente indisponível: "+msg)[:350]
                try:
                    intake("collection_control",{
                        "action":"geo_osm_mark","job_id":job_id,
                        "city_id":candidate["id"],"succeeded":False,"error":msg
                    })
                except Exception:
                    raise RuntimeError("Failed to save OSM retry checkpoint") from exc
                progress()
                if osm_failures>=2:break
            time.sleep(3)
        budget=intake("collection_control",{"action":"geo_budget","job_id":job_id})
        available=max(0,MONTHLY_SEARCH_BUDGET-int(budget.get("used_this_month",0)))
        # Do not spend search credits when free open-data discovery was productive.
        search_limit=(min(SEARCHES,available) if use_paid and count<20 else 0)
        required=10 if use_brave else 2
        if not use_brave:search_limit-=(search_limit%2)
        regions=intake("collection_control",{"action":"geo_regions"})["regions"]
        regions=region_queue(regions,country_mode)
        if search_limit<required:
            if not free_scans and not use_paid:notes="Somente fontes gratuitas: nenhuma cidade concluída pelo mapa aberto nesta rodada."
            elif not use_paid:notes="Pesquisa OSM gratuita concluída. Especialidades aguardam provedor web."
            else:notes="Créditos mensais reservados esgotados. Coleta OSM gratuita mantida."
        elif not regions:
            notes="Todas as localidades concluídas ou nenhuma região pendente."
        else:
            country_regions={country:[r for r in regions if r["country_code"]==country]
                             for country in ("US","BR")}
            countries=(["US","BR"] if country_mode=="BOTH" else [country_mode])
            consecutive_failures=0
            country_index=0
            region_visits={"US":0,"BR":0}
            # Each location progresses via its saved specialty cursor; rotate
            # high-yield states after two passes so one state cannot monopolize credits.
            while (time.monotonic()<deadline-55 and count<MAX_TOTAL and
                   searched+required<=search_limit):
                if not any(country_regions.get(c) for c in countries):
                    break
                country=countries[country_index%len(countries)]
                country_index+=1
                if not country_regions.get(country):
                    continue
                region=country_regions[country][0]
                state=region["state_code"]
                candidate=intake("collection_control",{
                    "action":"geo_next","job_id":job_id,
                    "country_code":country,"state_code":state
                }).get("city")
                if not candidate:
                    country_regions[country].pop(0)
                    continue
                city=candidate["city_name"]
                cursor=int(candidate["specialty_cursor"])
                if not 0<=cursor<TOTAL_SPECIALTIES:
                    raise RuntimeError("Specialty checkpoint out of catalog bounds")
                specialty=specialty_at(country,cursor)
                current_region=country+" / "+state+" / "+city+" / "+specialty
                env=os.environ.copy()
                env.update({
                    "DISCOVERY_COUNTRY":country,"DISCOVERY_CITY":city,
                    "DISCOVERY_STATES":state,"DISCOVERY_KEYWORDS":specialty,
                    "DISCOVERY_SPECIALTY_INDEX":str(cursor),
                    "DISCOVERY_TARGET":"organizations",
                    "DISCOVERY_MAX_LEADS":str(min(MAX_ROUND,MAX_TOTAL-count)),
                    "DISCOVERY_MAX_SEARCHES":str(required),
                    "DISCOVERY_ENABLE_NPPES":"false",
                    "DISCOVERY_ENABLE_APOLLO":"false"
                })
                remaining=max(35,int(deadline-time.monotonic()-15))
                try:
                    result=subprocess.run([sys.executable,str(SCRIPT)],env=env,
                                          timeout=remaining,capture_output=True,text=True)
                    if result.returncode!=0:
                        raise RuntimeError("Source query: "+result.stderr[-230:])
                    payload=json.loads(result.stdout.strip().splitlines()[-1])
                    queries=int(payload.get("site_search_queries") or 0)
                    if queries<1 or queries>required:
                        raise RuntimeError("Specialty checkpoint search count is outside its quota")
                    found=max(0,int(payload.get("saved",0)))
                    checked=intake("collection_control",{
                        "action":"geo_mark","job_id":job_id,"city_id":candidate["id"],
                        "expected_cursor":cursor,"succeeded":True,"found_emails":found
                    })
                    if not checked.get("ok"):
                        raise RuntimeError("City checkpoint update not confirmed")
                    count+=found;searched+=queries;rounds+=1
                    consecutive_failures=0
                    notes=(current_region+" • "+str(found)+" novos e-mails • "+
                           str(cursor+1)+"/"+str(TOTAL_SPECIALTIES)+" áreas").strip()[:350]
                    progress()
                    region_visits[country]+=1
                    if region_visits[country]%2==0 and len(country_regions[country])>1:
                        country_regions[country].append(country_regions[country].pop(0))
                    print(json.dumps({
                        "country":country,"state":state,"city":city,
                        "specialty":specialty,"city_completed":cursor+1>=TOTAL_SPECIALTIES,
                        "saved_unique_emails":found,"queries_total":searched,
                        "elapsed_min":round((time.monotonic()-start)/60,1)
                    }),flush=True)
                except subprocess.TimeoutExpired:
                    notes="Tempo máximo atingido em "+current_region+"; pesquisa será retomada."
                    break
                except Exception as exc:
                    errors+=1
                    consecutive_failures+=1
                    msg=str(exc)[:240]
                    notes="Falha em "+current_region+": "+msg
                    try:
                        intake("collection_control",{
                            "action":"geo_mark","job_id":job_id,"city_id":candidate["id"],
                            "expected_cursor":cursor,"succeeded":False,"error":msg
                        })
                    except Exception as mark_error:
                        raise RuntimeError("Could not checkpoint retry: "+str(mark_error)) from exc
                    progress()
                    # Do not let a failing single state block other markets.
                    if len(country_regions[country])>1:
                        country_regions[country].append(country_regions[country].pop(0))
                    if consecutive_failures>=3:
                        raise RuntimeError("Três consultas falharam; confira cota Tavily e conexão.")
                time.sleep(3)
        if not notes:
            notes="Nenhuma pesquisa adicional elegível neste ciclo."
    except Exception as exc:
        status="failed"
        notes=(str(exc)[:300]+" ["+current_region+"]")[:350]
        print("Collection failed:",notes,file=sys.stderr,flush=True)
    finally:
        progress(final=True)
    print(json.dumps({
        "job_id":job_id,"status":status,"rounds":rounds,
        "candidates":count,"site_searches":searched,"free_source_scans":free_scans,"errors":errors,
        "elapsed_min":round((time.monotonic()-start)/60,1)
    }),flush=True)
    if status=="failed":raise RuntimeError(notes)

if __name__=="__main__":
    if not os.getenv("ONCREATE_INGEST_URL") or not (
        os.getenv("ACTIONS_ID_TOKEN_REQUEST_TOKEN") or os.getenv("ONCREATE_INGEST_TOKEN")):
        sys.exit("A valid ingest URL and Actions OIDC identity (or private shared intake token) are required.")
    main()
