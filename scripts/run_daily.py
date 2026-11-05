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

STATES=("AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN "
        "MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY").split()
PHYSICIAN_SPECIALTIES=("dermatology","cardiology","internal_medicine","family_medicine","pediatrics","neurology","orthopedic","obstetrics","psychiatry")
ORGANIZATION_SPECIALTIES=("medical","hospital","dermatology","pediatrics")
MAX_MINUTES=max(10,min(340,int(os.environ.get("MAX_RUNTIME_MINUTES","340"))))
MAX_TOTAL=max(25,min(12000,int(os.environ.get("MAX_DAILY_CANDIDATES","3000"))))
MAX_ROUND=max(10,min(100,int(os.environ.get("DISCOVERY_ROUND_CANDIDATES","80"))))
SEARCHES=max(0,min(15,int(os.environ.get("DISCOVERY_DAILY_SEARCH_CREDITS","15"))))
SCRIPT=Path(__file__).parent/"daily_lead_discovery.py"

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
    max_minutes=min(MAX_MINUTES,int(job.get("max_runtime_minutes") or MAX_MINUTES))
    start=time.monotonic()
    deadline=start+max_minutes*60
    count=0;rounds=0;searched=0;errors=0
    state="completed";notes=""

    def progress(final=False):
        payload={
            "action":"collection_complete" if final else "collection_progress",
            "id":job_id,"candidates_found":count,"rounds_completed":rounds,
            "search_queries":searched,"error_count":errors,
            "notes":notes,"status":state
        }
        return intake("collection_control",payload)

    try:
        # Without a provider capable of finding an official website and published email,
        # NPPES alone cannot yield eligible leads. Never waste hours on email-less records.
        if not os.getenv("TAVILY_API_KEY") and not (
            os.getenv("APOLLO_API_KEY") and
            os.getenv("DISCOVERY_ENABLE_APOLLO","false").lower()=="true"
        ):
            raise RuntimeError("Nenhum provedor de sites/e-mails está configurado: adicione TAVILY_API_KEY no GitHub Actions.")
        seed=dt.datetime.now(dt.timezone.utc).date().toordinal()
        tasks=[]
        for state_code in STATES:
            for i,practice in enumerate(PHYSICIAN_SPECIALTIES):
                tasks.append((state_code,practice,"physicians"))
                if i%3==2:
                    clinic=ORGANIZATION_SPECIALTIES[(i//3)%len(ORGANIZATION_SPECIALTIES)]
                    tasks.append((state_code,clinic,"organizations"))
        tasks=tasks[seed%len(tasks):]+tasks[:seed%len(tasks)]

        for state_code,specialty,target in tasks:
            if time.monotonic()>deadline-45 or count>=MAX_TOTAL:
                break
            env=os.environ.copy()
            env.update({
                "DISCOVERY_STATES":state_code,
                "DISCOVERY_KEYWORDS":specialty,
                "DISCOVERY_TARGET":target,
                "DISCOVERY_MAX_LEADS":str(min(MAX_ROUND,MAX_TOTAL-count)),
                "DISCOVERY_MAX_SEARCHES":str(max(0,SEARCHES-searched)),
                "DISCOVERY_ENABLE_APOLLO":"true" if rounds==0 and
                    os.environ.get("DISCOVERY_ENABLE_APOLLO","false").lower()=="true" else "false"
            })
            remaining=max(40,int(deadline-time.monotonic()-10))
            try:
                result=subprocess.run([sys.executable,str(SCRIPT)],env=env,
                    timeout=remaining,capture_output=True,text=True)
            except subprocess.TimeoutExpired:
                notes="Tempo máximo de execução atingido; registros válidos já foram salvos."
                break
            if result.returncode!=0:
                errors+=1
                notes=("Falha de pesquisa em "+state_code+" "+specialty+": "+result.stderr[-220:])[:350]
                print(notes,flush=True)
                progress()
                if errors>=3:raise RuntimeError("Três falhas seguidas do fornecedor: "+notes)
                time.sleep(10)
                continue
            try:
                payload=json.loads(result.stdout.strip().splitlines()[-1])
            except (ValueError,IndexError):
                errors+=1
                if errors>=3:raise RuntimeError("Três respostas inválidas do coletor.")
                progress()
                continue
            collected=max(0,int(payload.get("saved",0)))
            counted=max(0,int(payload.get("site_search_queries",0)))
            count+=collected
            searched+=counted
            rounds+=1
            notes=("Última pesquisa: "+state_code+" / "+specialty+
                   " — "+str(collected)+" novos leads com e-mail.").strip()[:350]
            progress()
            print(json.dumps({
                "job_id":job_id,"round":rounds,"state":state_code,
                "specialty":specialty,"candidates_total":count,
                "searches_total":searched,"elapsed_min":round((time.monotonic()-start)/60,1)
            }),flush=True)
            time.sleep(5)
        if count==0 and not notes:
            notes="Pesquisa concluída sem novos e-mails comerciais verificados."
    except Exception as exc:
        state="failed"
        notes=str(exc)[:350]
        print("Collection failed:",notes,file=sys.stderr,flush=True)
    finally:
        progress(final=True)
    print(json.dumps({
        "job_id":job_id,"status":state,"rounds":rounds,
        "candidates":count,"site_searches":searched,"errors":errors,
        "elapsed_min":round((time.monotonic()-start)/60,1)
    }),flush=True)
    if state=="failed":
        raise RuntimeError(notes)

if __name__=="__main__":
    if not os.getenv("ONCREATE_INGEST_URL") or not (
        os.getenv("ACTIONS_ID_TOKEN_REQUEST_TOKEN") or os.getenv("ONCREATE_INGEST_TOKEN")):
        sys.exit("A valid ingest URL and Actions OIDC identity (or private shared intake token) are required.")
    main()
