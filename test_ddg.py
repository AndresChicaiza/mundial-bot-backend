import urllib.request
import urllib.parse
import re
import sys

query = "Países Bajos vs Suecia estadio arbitro mundial 2026"
q = urllib.parse.quote(query)
url = f"https://html.duckduckgo.com/html/?q={q}"
headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
try:
    req = urllib.request.Request(url, headers=headers)
    html = urllib.request.urlopen(req).read().decode('utf-8')
    snippets = re.findall(r'<a class="result__snippet[^>]*>(.*?)</a>', html, re.IGNORECASE | re.DOTALL)
    print("SUCCESS")
    for s in snippets[:3]:
        print("-", re.sub(r'<[^>]+>', '', s).strip())
except Exception as e:
    print("ERROR:", e)
