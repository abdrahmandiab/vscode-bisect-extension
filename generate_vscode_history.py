import urllib.request
import urllib.error
import json
import re
import sys
import os
import time
from datetime import datetime

REPO = "microsoft/vscode"
TAGS_URL = f"https://api.github.com/repos/{REPO}/tags"

# Get Token from Env
TOKEN = os.environ.get("GITHUB_TOKEN")

def get_headers():
    if TOKEN:
        return {"Authorization": f"token {TOKEN}", "User-Agent": "vscode-bisect-script"}
    else:
        print("Warning: No GITHUB_TOKEN set. Rate limits may apply (60/hr).")
        return {"User-Agent": "vscode-bisect-script"}

def fetch_json(url):
    try:
        req = urllib.request.Request(url, headers=get_headers())
        with urllib.request.urlopen(req) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as e:
        if e.code == 403:
            print(f"\nRate limit exceeded fetching {url}. Waiting 60s...")
            time.sleep(60)
            return fetch_json(url) # Retry once
        print(f"\nError fetching {url}: {e}")
        return None
    except Exception as e:
        print(f"\nError fetching {url}: {e}")
        return None

def fetch_all_tags():
    tags = []
    page = 1
    while True:
        print(f"Fetching tags page {page}...", end='\r')
        url = f"{TAGS_URL}?per_page=100&page={page}"
        data = fetch_json(url)
        
        if not data:
            break
        
        for tag in data:
            tags.append({
                'name': tag['name'],
                'commit': tag['commit']['sha'],
                'commit_url': tag['commit']['url']
            })
        
        if len(data) < 100:
            break
        page += 1
    print(f"\nFetched {len(tags)} tags.")
    return tags

def parse_version(tag_name):
    clean_name = tag_name.lstrip('v')
    match = re.match(r'^(\d+)\.(\d+)\.(\d+)(?:-([a-zA-Z0-9]+))?$', clean_name)
    if not match:
        return None
    
    major, minor, patch, label = match.groups()
    major = int(major)
    if major >= 900: # Filter out test tags like 1.999.0
        return None
        
    return {
        'major': major,
        'minor': int(minor),
        'patch': int(patch),
        'label': label,
        'original': tag_name
    }

def sort_key(item):
    v = item['version_info']
    # Stable (None) > Insider (label) priority? 
    # Usually we want Descending time.
    # But here we sort by Version Number.
    # 1.80.0 > 1.80.0-insider.
    label_priority = 0 if v['label'] is None else -1 
    return (v['major'], v['minor'], v['patch'], label_priority)

def get_version_metadata(version, label):
    # Use VS Code Update API to get date
    # /api/versions/{version}/{platform}/{quality}
    # Quality: 'stable' or 'insider'
    # Platform: 'darwin' (generic enough to get the timestamp)
    quality = 'insider' if label == 'insider' else 'stable'
    
    # If version is just "1.80.0", and it's stable, URL is .../1.80.0/darwin/stable
    # If "1.80.0-insider", URL calls .../1.80.0-insider/darwin/insider
    
    # Correction: The Update API expects the full version string sometimes?
    # Let's try passing the tag name directly.
    
    url = f"https://update.code.visualstudio.com/api/versions/{version}/darwin/{quality}"
    
    try:
        # 3s timeout to fail fast
        with urllib.request.urlopen(url, timeout=3) as response:
            if response.status == 200:
                 return json.loads(response.read().decode())
    except Exception:
        pass
    return None

def main():
    print("Fetching tags from GitHub...")
    all_raw_tags = fetch_all_tags()
    
    stable_builds = []
    insider_builds = []

    print("Processing tags and fetching metadata (from Update API)...")
    
    count = 0
    total = len(all_raw_tags)
    
    # We can retry fetching dates via GitHub if Update API fails? 
    # Or just rely on Update API. Update API is usually reliable for released builds.

    for tag in all_raw_tags:
        count += 1
        info = parse_version(tag['name'])
        if not info:
            continue
            
        commit_sha = tag['commit']
        # commit_url = tag['commit_url'] # Unused if we use Update API
        
        version_str = tag['name'].lstrip('v')
        
        print(f"[{count}/{total}] Fetching metadata for {version_str}...", end='\r')
        
        meta = get_version_metadata(version_str, info['label'])
        date_val = None
        
        if meta and 'timestamp' in meta:
            # timestamp is usually a number (epoch ms)? Or ISO?
            # API returns "timestamp": 169099999...
            date_val = meta['timestamp'] 
            # Note: `src/builds.ts` handles number or string.
        
        build = {
            'version': version_str,
            'commit': commit_sha,
            'date': date_val,
            'version_info': info
        }

        if info['label'] == 'insider':
            insider_builds.append(build)
        elif info['label'] is None:
            stable_builds.append(build)
            
        # Be nice to Update API?
        # It's robust but let's not hammer it too hard if unnecessary.
        # It's sequential, so it's fine.

    # Sort
    stable_builds.sort(key=sort_key)
    insider_builds.sort(key=sort_key)

    # Clean Output
    stable_out = [{'version': b['version'], 'commit': b['commit'], 'date': b['date']} for b in stable_builds]
    insider_out = [{'version': b['version'], 'commit': b['commit'], 'date': b['date']} for b in insider_builds]

    print(f"\nFound {len(stable_out)} stable builds.")
    print(f"Found {len(insider_out)} insider builds.")

    with open('vscode_stable_history.json', 'w') as f:
        json.dump(stable_out, f, indent=2)
    
    with open('vscode_insider_history.json', 'w') as f:
        json.dump(insider_out, f, indent=2)

    print("Saved to vscode_stable_history.json and vscode_insider_history.json")

if __name__ == "__main__":
    main()
