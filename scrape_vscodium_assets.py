import urllib.request
import urllib.error
import json
import re
import time
import sys

# VSCodium Insiders Repo
RELEASES_URL = "https://api.github.com/repos/VSCodium/vscodium-insiders/releases?per_page=100&page={}"
HISTORY_FILE = "vscodium_insider_history.json"
MAX_PAGES = 5

def fetch_json(url):
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except Exception as e:
        print(f"Error fetching {url}: {e}")
        return None

def main():
    history = []
    seen_commits = set()
    
    print(f"Scraping VSCodium Assets for Insiders...")
    
    for page in range(1, MAX_PAGES + 1):
        print(f"Fetching page {page}...")
        releases = fetch_json(RELEASES_URL.format(page))
        if not releases:
            break
            
        print(f"  Found {len(releases)} releases. Parsing...")
        
        for r in releases:
            body = r.get('body', '')
            tag_name = r.get('tag_name', 'unknown')
            created_at = r.get('created_at', 'unknown')
            
            # 1. Find Hash
            match = re.search(r"update vscode to (?:\[)?([a-f0-9]{40})", body, re.IGNORECASE)
            if match:
                vscode_hash = match.group(1)
                
                if vscode_hash in seen_commits:
                    continue
                
                # 2. Find Assets
                assets_map = {}
                for asset in r.get('assets', []):
                    name = asset['name']
                    url = asset['browser_download_url']
                    
                    # Store zip/tar.gz assets by platform/arch
                    # Common names:
                    # VSCodium-darwin-arm64-1.107.18537-insider.zip
                    # VSCodium-darwin-x64-...zip
                    # VSCodium-linux-x64-...tar.gz
                    # VSCodium-linux-arm64-...tar.gz
                    # VSCodium-win32-x64-...zip
                    # VSCodium-win32-arm64-...zip
                    
                    if name.endswith(".zip") or name.endswith(".tar.gz"):
                         if "darwin-arm64" in name:
                             assets_map["darwin_arm64"] = url
                         elif "darwin-x64" in name:
                             assets_map["darwin_x64"] = url
                         elif "linux-arm64" in name:
                             assets_map["linux_arm64"] = url
                         elif "linux-x64" in name:
                             assets_map["linux_x64"] = url
                         elif "win32-arm64" in name:
                             assets_map["win32_arm64"] = url
                         elif "win32-x64" in name:
                             assets_map["win32_x64"] = url
                
                if not assets_map:
                    # No downloadable binary assets found? Skip?
                    continue

                entry = {
                    "version": tag_name,
                    "commit": vscode_hash,
                    "date": created_at,
                    "vscodium_src": True,
                    "assets": assets_map
                }
                history.append(entry)
                seen_commits.add(vscode_hash)
        
        print(f"  Page {page} done. Total unique: {len(history)}")
        time.sleep(1)

    print(f"Total found: {len(history)}")
    
    with open(HISTORY_FILE, 'w') as f:
        json.dump(history, f, indent=2)
    print(f"Saved to {HISTORY_FILE}")

if __name__ == "__main__":
    main()
