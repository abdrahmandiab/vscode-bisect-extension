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
        with urllib.request.urlopen(req, timeout=30) as r:
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
        
# Helper to get upstream VS Code metadata (borrowed from generate_vscode_history.py logic)
def fetch_upstream_timestamp(commit_sha):
    url = f"https://update.code.visualstudio.com/api/versions/commit:{commit_sha}/darwin/insider"
    max_retries = 3
    for attempt in range(max_retries):
        try:
            data = fetch_json(url)
            if data and 'timestamp' in data:
                return data['timestamp'] # Returns millisecond timestamp (number)
        except Exception:
            pass
        time.sleep(0.5)
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
            vscodium_date_str = r.get('published_at') or r.get('created_at')
            
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
                    
                    if "reh" in name:
                        continue

                    if name.endswith(".zip") or name.endswith(".tar.gz"):
                         if "darwin-arm64" in name and name.endswith(".zip"):
                             assets_map["darwin_arm64"] = url
                         elif "darwin-x64" in name and name.endswith(".zip"):
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
                    continue

                # 3. Fetch Upstream Date (Critical for accurate bisect)
                print(f"    Fetching upstream date for {vscode_hash[:7]}...")
                upstream_ts = fetch_upstream_timestamp(vscode_hash)
                
                # Use upstream timestamp if available, else fallback to VSCodium release date
                # Note: Upstream is ms-since-epoch (int), VSCodium is ISO string.
                # src/builds.ts handles both types.
                final_date = upstream_ts if upstream_ts else vscodium_date_str

                entry = {
                    "version": tag_name,
                    "commit": vscode_hash,
                    "date": final_date,
                    "vscodium_src": True,
                    "assets": assets_map
                }
                history.append(entry)
                seen_commits.add(vscode_hash)
                
                # Rate limit politeness
                time.sleep(0.1)
        
        print(f"  Page {page} done. Total unique: {len(history)}")
        time.sleep(1)

    print(f"Total found: {len(history)}")
    
    if not history:
        print("Error: No history found. Aborting save to avoid overwriting existing data.")
        return

    with open(HISTORY_FILE, 'w') as f:
        json.dump(history, f, indent=2)
    print(f"Saved to {HISTORY_FILE}")

if __name__ == "__main__":
    main()
