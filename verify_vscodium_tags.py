import urllib.request
import urllib.error
import sys

# Tags from VSCodium (hardcoded for now to test)
tags = [
    "1.107.18537-insider",
    "1.107.18536-insider",
    "1.107.18532-insider",
    "1.107.18481-insider",
    "1.107.08447-insider"
]

BASE_URL = "https://update.code.visualstudio.com/api/versions"
PLATFORM = "darwin"
QUALITY = "insider"

def check(version):
    url = f"{BASE_URL}/{version}/{PLATFORM}/{QUALITY}"
    try:
        req = urllib.request.Request(url, method='HEAD')
        with urllib.request.urlopen(req, timeout=2) as response:
            if response.status == 200:
                print(f"[SUCCESS] {version} -> Found!")
                return True
    except urllib.error.HTTPError as e:
        print(f"[FAIL] {version} -> {e.code}")
    except Exception as e:
        print(f"[ERR] {version} -> {e}")
    return False

print("--- Testing VSCodium Tags as-is ---")
for t in tags:
    check(t)

print("\n--- Testing VSCodium Tags without '-insider' ---")
for t in tags:
    clean = t.replace("-insider", "")
    check(clean)
