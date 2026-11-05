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

STATES=("AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN "
        "MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY").split()
SPECIALTIES=("dental","dermatology","medical","orthopedic","pediatrics","cardiology")
MAX_MINUTES=max(10,min(340,int(os.environ.get("MAX_RUNTIME_MINUTES","340"))))
MAX_TOTAL=max(25,min(12000,int(os.environ.get("MAX_DAILY_CANDIDATES","3000"))))
MAX_ROUND=max(10,min(100,int(os.environ.get("DISCOVERY_ROUND_CANDIDATES","80"))))
SEARCHES=max(0,min(15,int(os.environ.get("DISCOVERY_DAILY_SEARCH_CREDITS","15"))))
SCRIPT=Path(__file__).parent/"daily_lead_discovery.py"

def main():
    start=time.monotonic()
    deadline=start+MAX_MINUTES*60
    seed=dt.datetime.now(dt.timezone.utc).date().toordinal()
    tasks=list(itertools.product(STATES,SPECIALTIES))
    # Rotate combinations each day to cover the US over successive runs.
    tasks=tasks[seed%len(tasks):]+tasks[:seed%len(tasks)]
    count=0
    rounds=0
    searched=0
    errors=0
    for state,specialty in tasks:
        if time.monotonic()>deadline-45 or count>=MAX_TOTAL:
            break
        env=os.environ.copy()
        env.update({
            "DISCOVERY_STATES":state,
            "DISCOVERY_KEYWORDS":specialty,
            "DISCOVERY_MAX_LEADS":str(min(MAX_ROUND,MAX_TOTAL-count)),
            "DISCOVERY_MAX_SEARCHES":str(max(0,SEARCHES-searched)),
            "DISCOVERY_ENABLE_APOLLO": "true" if rounds==0 and
                os.environ.get("DISCOVERY_ENABLE_APOLLO","false").lower()=="true" else "false"
        })
        remaining=max(40,int(deadline-time.monotonic()-10))
        try:
            result=subprocess.run([sys.executable,str(SCRIPT)],env=env,timeout=remaining,
                capture_output=True,text=True)
        except subprocess.TimeoutExpired:
            print("Batch timeout; candidates already persisted; ending safely.",flush=True)
            break
        if result.returncode!=0:
            errors+=1
            print("Source query failed for",state,specialty,result.stderr[-450:],flush=True)
            # Stop instead of retrying repeatedly against a failing provider.
            if errors>=3:break
            time.sleep(10)
            continue
        try:
            payload=json.loads(result.stdout.strip().splitlines()[-1])
        except (ValueError,IndexError):
            errors+=1
            if errors>=3:break
            continue
        collected=max(0,int(payload.get("saved",0)))
        counted=max(0,int(payload.get("site_search_queries",0)))
        count+=collected
        searched+=counted
        rounds+=1
        print(json.dumps({"round":rounds,"state":state,"specialty":specialty,
              "candidates_total":count,"searches_total":searched,
              "elapsed_min":round((time.monotonic()-start)/60,1)}),flush=True)
        # Small pause between sources; each individual source call is also rate limited.
        time.sleep(5)
    print(json.dumps({"complete":True,"rounds":rounds,"candidates":count,
          "site_searches":searched,"errors":errors,
          "elapsed_min":round((time.monotonic()-start)/60,1)}),flush=True)

if __name__=="__main__":
    if not os.getenv("ONCREATE_INGEST_TOKEN") or not os.getenv("ONCREATE_INGEST_URL"):
        sys.exit("ONCREATE_INGEST_TOKEN and ONCREATE_INGEST_URL must be configured as Actions secrets / variables.")
    main()
