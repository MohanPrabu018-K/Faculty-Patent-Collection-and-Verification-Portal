import urllib.request
import json
import time

base_url = 'https://faculty-patent-portal-api.onrender.com'

# 1. /healthz
t0 = time.time()
with urllib.request.urlopen(f'{base_url}/healthz') as resp:
    h_status = resp.status
    h_body = resp.read().decode()
    h_time = time.time() - t0
print(f'/healthz: status={h_status}, body={h_body.strip()}, time={h_time:.3f}s')

# 2. /readyz
t0 = time.time()
with urllib.request.urlopen(f'{base_url}/readyz') as resp:
    r_status = resp.status
    r_body = resp.read().decode()
    r_headers = dict(resp.headers)
    r_time = time.time() - t0
print(f'/readyz: status={r_status}, body={r_body.strip()}, time={r_time:.3f}s')

# 3. /openapi.json
t0 = time.time()
with urllib.request.urlopen(f'{base_url}/openapi.json') as resp:
    o_status = resp.status
    o_data = json.loads(resp.read().decode())
    o_time = time.time() - t0
info = o_data.get('info', {})
print(f"/openapi.json: status={o_status}, title={info.get('title')}, version={info.get('version')}, time={o_time:.3f}s")

print('Headers of interest from /readyz:')
for k, v in r_headers.items():
    if any(x in k.lower() for x in ['version', 'commit', 'build', 'render', 'server', 'etag', 'date']):
        print(f'  {k}: {v}')
