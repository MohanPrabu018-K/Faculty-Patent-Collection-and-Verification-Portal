import subprocess
import sys
import os
import time

os.chdir(r'E:\Faculty profile portal\backend')
os.environ['PYTHONPATH'] = r'E:\Faculty profile portal\backend'

# Start server
proc = subprocess.Popen([
    sys.executable, '-m', 'uvicorn', 'app.main:app', 
    '--host', '0.0.0.0', '--port', '8000'
], cwd=r'E:\Faculty profile portal\backend')

print(f"Server started with PID: {proc.pid}")

# Wait for server
for i in range(30):
    try:
        import requests
        r = requests.get('http://localhost:8000/api/v1/auth/csrf', timeout=2)
        if r.status_code == 200:
            print("Server is ready!")
            break
    except:
        pass
    time.sleep(1)
    print(f"Waiting for server... {i+1}/30")
else:
    print("Server failed to start")
    proc.terminate()
    sys.exit(1)

# Keep server running
try:
    proc.wait()
except KeyboardInterrupt:
    proc.terminate()