import urllib.request

url = 'http://127.0.0.1:8004/api/v1/pipeline/trust/metrics'
try:
    with urllib.request.urlopen(url, timeout=10) as r:
        print('STATUS', r.status)
        print(r.read().decode())
except Exception as e:
    print('ERROR', repr(e))
