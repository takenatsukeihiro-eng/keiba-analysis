# -*- coding: utf-8 -*-
"""Debug test for race search"""
import requests
import re
from bs4 import BeautifulSoup

url = ("https://db.netkeiba.com/race/list/"
       "?pid=race_list"
       "&start_year=2024&end_year=2024"
       "&jyo%5B%5D=06"
       "&kyori_min=2000&kyori_max=2000"
       "&track%5B%5D=1")

print("URL:", url)
resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
resp.encoding = resp.apparent_encoding or "euc-jp"
soup = BeautifulSoup(resp.text, "lxml")

# Check all links
all_links = soup.select("a")
print(f"Total links: {len(all_links)}")

race_links = []
for link in all_links:
    href = link.get("href", "")
    if "/race/" in href:
        rid_m = re.search(r"/race/(\d{10,12})", href)
        if rid_m:
            name = link.get_text().strip()
            if name and len(name) > 1:
                race_links.append((rid_m.group(1), name))

print(f"Race links: {len(race_links)}")
for rid, name in race_links[:15]:
    print(f"  {rid}: {name}")

# Check structure
print(f"\nTables: {len(soup.select('table'))}")
for i, t in enumerate(soup.select("table")[:5]):
    print(f"  Table {i}: class={t.get('class')}, rows={len(t.select('tr'))}")

# Check for pagination or other content
divs_with_class = soup.select("div[class]")
for d in divs_with_class[:10]:
    cls = d.get("class", [])
    text = d.get_text().strip()[:80]
    if text:
        print(f"  div.{cls}: {text}")
