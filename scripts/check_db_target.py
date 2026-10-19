#!/usr/bin/env python3
"""Safely inspect database targets without printing credentials."""
import os
from urllib.parse import urlsplit

for env_file in ["backend/.env", ".env"]:
    if os.path.exists(env_file):
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("DATABASE_URL="):
                    val = line.split("=", 1)[1].strip("\"'")
                    p = urlsplit(val)
                    print(f"File: {env_file}")
                    print(f"  Scheme:   {p.scheme}")
                    print(f"  Host:     {p.hostname}")
                    print(f"  Port:     {p.port}")
                    print(f"  Database: {p.path.lstrip('/')}")
                    print()
