"""
Updates IBAN→BIC information contained in this module using public sources.

100310001EIS Einlagensicherungsbank                                10178Berlin                             EIS Bank
Berlin                 EIEGDEB1XXX09056711U000000000

"""

import json
import requests
from bs4 import BeautifulSoup

map = {}

# Germany
page = requests.get(
    "https://www.bundesbank.de/en/tasks/payment-systems/services/bank-sort-codes/download-bank-sort-codes-626218"
)
doc = BeautifulSoup(page.text, "lxml")

url = doc.select("a[href*='/blz-aktuell-txt-data.txt']")[0].attrs["href"]
data = requests.get(url).text

for line in data.split("\n"):
    if not line or line[8] != "1" or line[139] == " ":
        continue
    map[f"DEXX{line[0:8]}"] = line[139:150]


# Write file
d = json.dumps(map)
with open("pretix_sepadebit/bicdata.py", "w") as f:
    f.write(f"DATA = {d}")
