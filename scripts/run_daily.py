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

# Exact six specialty passes per Census place / IBGE municipality.
# A city is green only after all 6 passes have completed successfully.
US_SPECIALTIES=(
 "dermatology","cardiology","pediatrics","neurology","obstetrics","internal_medicine"
)
BR_SPECIALTIES=(
 "dermatologia","cardiologia","pediatria","neurologia","ginecologia","clinica_medica"
)
MAX_MINUTES=max(10,min(340,int(os.environ.get("MAX_RUNTIME_MINUTES","180"))))
MAX_TOTAL=max(25,min(12000,int(os.environ.get("MAX_DAILY_CANDIDATES","3000"))))
MAX_ROUND=max(10,min(100,int(os.environ.get("DISCOVERY_ROUND_CANDIDATES","80"))))
SEARCHES=max(1,min(500,int(os.environ.get("DISCOVERY_DAILY_SEARCH_CREDITS","15"))))
SCRIPT=Path(__file__).parent/"daily_lead_discovery.py"

def region_queue(regions,country_mode):
    """Balanced US/BR state rotation, least researched states first."""
    grouped={}
    for country in ("US","BR"):
        places=[
            r for r in regions if r["country_code"]==country and
            int(r["completed_cities"])<int(r["total_cities"])
        ]
        places.sort(key=lambda r:(
            int(r["searched_specialties"]),int(r["visited_cities"]),r["state_code"]
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
    max_minutes=min(MAX_MINUTES,int(job.get("max_runtime_minutes") or MAX_MINUTES))
    start=time.monotonic()
    deadline=start+max_minutes*60
    count=0;rounds=0;searched=0;errors=0
    status="completed";notes=""
    current_region=""

    def progress(final=False):
        payload={
            "action":"collection_complete" if final else "collection_progress",
            "id":job_id,"candidates_found":count,"rounds_completed":rounds,
            "search_queries":searched,"error_count":errors,
            "notes":notes,"status":status
        }
        result=intake("collection_control",payload)
        if not result.get("ok"):
            raise RuntimeError("Collection heartbeat was not accepted")

    try:
        if not os.getenv("TAVILY_API_KEY"):
            raise RuntimeError("A busca geográfica requer TAVILY_API_KEY no GitHub Actions para localizar sites oficiais.")
        regions=intake("collection_control",{"action":"geo_regions"})["regions"]
        regions=region_queue(regions,country_mode)
        if not regions:
            raise RuntimeError("Nenhuma cidade pendente no catálogo. Confira a importação geográfica.")
        region_index=0
        consecutive_failures=0
        while regions and time.monotonic()<deadline-55 and count<MAX_TOTAL and searched<SEARCHES:
            region=regions[region_index%len(regions)]
            country=region["country_code"]
            state=region["state_code"]
            candidate=intake("collection_control",{
                "action":"geo_next","job_id":job_id,"country_code":country,"state_code":state
            }).get("city")
            if not candidate:
                regions.pop(region_index%len(regions))
                if not regions:break
                region_index%=len(regions)
                continue
            city=candidate["city_name"]
            cursor=int(candidate["specialty_cursor"])
            specialties=BR_SPECIALTIES if country=="BR" else US_SPECIALTIES
            if cursor>=len(specialties):
                raise RuntimeError("Invalid geographic checkpoint cursor")
            specialty=specialties[cursor]
            current_region=country+" / "+state+" / "+city+" / "+specialty
            env=os.environ.copy()
            env.update({
                "DISCOVERY_COUNTRY":country,"DISCOVERY_CITY":city,
                "DISCOVERY_STATES":state,"DISCOVERY_KEYWORDS":specialty,
                "DISCOVERY_TARGET":"physicians" if country=="US" else "organizations",
                "DISCOVERY_MAX_LEADS":str(min(MAX_ROUND,MAX_TOTAL-count)),
                "DISCOVERY_MAX_SEARCHES":str(max(1,SEARCHES-searched)),
                "DISCOVERY_ENABLE_APOLLO":"false"
            })
            remaining=max(40,int(deadline-time.monotonic()-15))
            try:
                result=subprocess.run([sys.executable,str(SCRIPT)],
                    env=env,timeout=remaining,capture_output=True,text=True)
                if result.returncode!=0:
                    raise RuntimeError("Provider error: "+result.stderr[-220:])
                payload=json.loads(result.stdout.strip().splitlines()[-1])
                queries=int(payload.get("site_search_queries") or 0)
                if queries<1:
                    raise RuntimeError("No official-website search was actually performed")
                found=max(0,int(payload.get("saved",0)))
                mark=intake("collection_control",{
                    "action":"geo_mark","job_id":job_id,"city_id":candidate["id"],
                    "expected_cursor":cursor,"succeeded":True,
                    "found_emails":found
                })
                if not mark.get("ok"):
                    raise RuntimeError("City checkpoint could not be saved")
                count+=found;searched+=queries;rounds+=1
                consecutive_failures=0
                notes=(current_region+" • "+str(found)+" e-mails comerciais • "+
                       str(cursor+1)+"/6 especialidades").strip()[:350]
                progress()
                print(json.dumps({
                    "country":country,"state":state,"city":city,"specialty":specialty,
                    "city_completed":cursor+1>=6,"emails_saved":found,
                    "queries_total":searched,"elapsed_min":round((time.monotonic()-start)/60,1)
                }),flush=True)
            except subprocess.TimeoutExpired:
                notes="Tempo máximo atingido; consulta incompleta em "+current_region
                break
            except Exception as exc:
                errors+=1;consecutive_failures+=1
                msg=str(exc)[:230]
                notes="Falha em "+current_region+": "+msg
                try:
                    intake("collection_control",{
                        "action":"geo_mark","job_id":job_id,"city_id":candidate["id"],
                        "expected_cursor":cursor,"succeeded":False,"error":msg
                    })
                except Exception as mark_error:
                    raise RuntimeError("Failed to record city retry: "+str(mark_error)) from exc
                progress()
                if consecutive_failures>=3:
                    raise RuntimeError("Três consultas com falha; confira a configuração do provedor.")
            region_index+=1
            time.sleep(4)
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
        "candidates":count,"site_searches":searched,"errors":errors,
        "elapsed_min":round((time.monotonic()-start)/60,1)
    }),flush=True)
    if status=="failed":raise RuntimeError(notes)

if __name__=="__main__":
    if not os.getenv("ONCREATE_INGEST_URL") or not (
        os.getenv("ACTIONS_ID_TOKEN_REQUEST_TOKEN") or os.getenv("ONCREATE_INGEST_TOKEN")):
        sys.exit("A valid ingest URL and Actions OIDC identity (or private shared intake token) are required.")
    main()
