#!/usr/bin/env python3
import sys
import httpx

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

repo = "MohanPrabu018-K/Faculty-Patent-Collection-and-Verification-Portal"
commits = ["44549a9", "94385b4", "ec26c62", "8515c70", "45a2036", "88386b5", "8503fe5"]

for c in commits:
    url = f"https://api.github.com/repos/{repo}/commits/{c}/check-runs"
    r = httpx.get(url, headers={"User-Agent": "Mozilla/5.0"})
    if r.status_code == 200:
        data = r.json()
        cf_runs = [cr for cr in data.get("check_runs", []) if cr.get("app", {}).get("name") == "Cloudflare Workers and Pages"]
        for cr in cf_runs:
            print(f"Commit {c}:")
            out = cr.get("output", {})
            summary = out.get("summary", "")
            lines = [l.strip() for l in summary.split("\n") if l.strip()]
            for l in lines:
                print("  ", l)
            print()
