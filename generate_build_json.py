import urllib.request
import json
import re
import sys

REPO = "microsoft/vscode"
TAGS_URL = f"https://api.github.com/repos/{REPO}/tags"

# Helpers
def fetch_all_tags():
    tags = []
    page = 1
    while True:
        print(f"Fetching page {page}...", end='\r')
        url = f"{TAGS_URL}?per_page=100&page={page}"
        try:
            with urllib.request.urlopen(url) as response:
                if response.status != 200:
                    break
                data = json.loads(response.read().decode())
                if not data:
                    break
                
                for tag in data:
                    tags.append({
                        'name': tag['name'],
                        'commit': tag['commit']['sha']
                    })
                page += 1
        except Exception as e:
            print(f"\nError fetching page {page}: {e}")
            break
    print(f"\nFetched {len(tags)} tags.")
    return tags

def parse_version(tag_name):
    # Regex for SemVer-ish: 1.2.3 or 1.2.3-insider
    # We strip 'v' if present
    clean_name = tag_name.lstrip('v')
    match = re.match(r'^(\d+)\.(\d+)\.(\d+)(?:-([a-zA-Z0-9]+))?$', clean_name)
    if not match:
        return None
    
    major, minor, patch, label = match.groups()
    return {
        'major': int(major),
        'minor': int(minor),
        'patch': int(patch),
        'label': label, # 'insider' or None
        'original': tag_name
    }

def sort_key(item):
    v = item['version_info']
    # Major, Minor, Patch, Label
    # Stable (no label) is > Insider (label) for same version? 
    # Actually usually 1.80.0-insider is BEFORE 1.80.0.
    # So if label exists, it is smaller.
    label_priority = 0 if v['label'] is None else -1 
    return (v['major'], v['minor'], v['patch'], label_priority)

def main():
    print("Fetching tags from GitHub...")
    all_raw_tags = fetch_all_tags()
    
    stable_builds = []
    insider_builds = []

    print("Processing tags...")
    for tag in all_raw_tags:
        info = parse_version(tag['name'])
        if not info:
            continue
            
        build = {
            'version': tag['name'].lstrip('v'), # normalized string
            'commit': tag['commit'],
            'version_info': info
        }

        if info['label'] == 'insider':
            insider_builds.append(build)
        elif info['label'] is None:
            # Stable
            stable_builds.append(build)

    # Sort
    stable_builds.sort(key=sort_key)
    insider_builds.sort(key=sort_key)

    # Clean up (remove version_info helper key if desired, or keep for debugging)
    # Keeping clean list for JSON
    stable_out = [{'version': b['version'], 'commit': b['commit']} for b in stable_builds]
    insider_out = [{'version': b['version'], 'commit': b['commit']} for b in insider_builds]

    print(f"Found {len(stable_out)} stable builds.")
    print(f"Found {len(insider_out)} insider builds.")

    with open('vscode_stable_history.json', 'w') as f:
        json.dump(stable_out, f, indent=2)
    
    with open('vscode_insider_history.json', 'w') as f:
        json.dump(insider_out, f, indent=2)

    print("Saved to vscode_stable_history.json and vscode_insider_history.json")

if __name__ == "__main__":
    main()
