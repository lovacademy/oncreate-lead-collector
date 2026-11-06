"""Official Brave Search web API adapter (no SERP or Google Maps scraping).

Requires BRAVE_SEARCH_API_KEY as a private GitHub Actions secret.
Current Brave Search API supports up to 20 web hits/page and offsets 0..9.
Use only the provider's permitted API, then independently inspect practice sites.
"""
import json
import os
import urllib.error
import urllib.parse
import urllib.request

BASE="https://api.search.brave.com/res/v1/web/search"

def available():
    return bool(os.getenv("BRAVE_SEARCH_API_KEY","").strip())

def brave_page(query:str,country:str,offset:int=0):
    if not available():
        raise RuntimeError("BRAVE_SEARCH_API_KEY not configured")
    if not 0<=offset<=9:
        raise ValueError("Brave Search supports only pages 1 to 10")
    if country not in ("BR","US"):
        raise ValueError("Country must be BR or US")
    params=urllib.parse.urlencode({
        "q":query[:580],"country":country,
        "search_lang":"pt" if country=="BR" else "en",
        "count":20,"offset":offset,"safesearch":"moderate"
    })
    req=urllib.request.Request(BASE+"?"+params,headers={
        "Accept":"application/json",
        "X-Subscription-Token":os.environ["BRAVE_SEARCH_API_KEY"].strip(),
        "User-Agent":"OnCreate-Lead-Research/1.0 (official Brave web API)"
    })
    try:
        with urllib.request.urlopen(req,timeout=22) as response:
            data=json.loads(response.read(1_400_000).decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # The error body might contain account information; never log it.
        raise RuntimeError("Brave Search API HTTP "+str(exc.code)) from exc
    results=(data.get("web") or {}).get("results") or []
    candidates=[]
    for entry in results:
        if not isinstance(entry,dict):continue
        url=str(entry.get("url") or "")
        title=str(entry.get("title") or "")
        description=str(entry.get("description") or "")
        if url.startswith("https://") and title:
            candidates.append({
                "url":url,"title":title,"content":description
            })
    more=bool((data.get("query") or {}).get("more_results_available"))
    return candidates,more
