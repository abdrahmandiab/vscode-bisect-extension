import urllib.request
import json
import time
import sys

# Configuration
PLATFORM = 'darwin'
BASE_URL = 'https://update.code.visualstudio.com'
OUTPUT_FILE = 'vscode_insider_history.json'

def fetch_metadata(version_str):
    url = f"{BASE_URL}/api/versions/{version_str}/{PLATFORM}/insider"
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            if response.status == 200:
                data = json.loads(response.read().decode())
                return data
    except Exception:
        pass
    return None

def scan_patches(major, minor):
    """Scans patches for a given minor version starting from 0 until 404."""
    found_any = False
    patch = 0
    found_builds = []

    while True:
        version_str = f"{major}.{minor}.{patch}-insider"
        print(f"Checking {version_str}...", end='\r')
        
        meta = fetch_metadata(version_str)
        if meta:
            # Found one!
            print(f"FOUND: {version_str} -> {meta['version']}          ")
            found_builds.append({
                'version': version_str, 
                'commit': meta['version'], 
                'date': meta.get('timestamp')
            })
            found_any = True
            patch += 1
        else:
            # Failed to find version.patch
            # If patch is 0, then the whole minor version is likely missing.
            # If patch > 0, we just reached the end of this minor version.
            break
            
    return found_builds

def scan_insiders():
    all_builds = []
    
    # Phase 1: 0.x (Starting 0.10)
    print("--- Scanning 0.x Series ---")
    major = 0
    minor = 10
    failures = 0
    while failures < 5:
        builds = scan_patches(major, minor)
        if builds:
            all_builds.extend(builds)
            failures = 0
        else:
            failures += 1
        minor += 1

    # Phase 2: 1.x
    print("\n--- Scanning 1.x Series ---")
    major = 1
    minor = 0
    failures = 0
    while failures < 10: # Stop after 10 consecutive missing minor versions
        builds = scan_patches(major, minor)
        if builds:
            all_builds.extend(builds)
            failures = 0
        else:
            failures += 1
        minor += 1

    print(f"\nScan complete. Found {len(all_builds)} builds.")
    
    # Save
    with open(OUTPUT_FILE, 'w') as f:
        json.dump(all_builds, f, indent=2)
    print(f"Saved to {OUTPUT_FILE}")

if __name__ == "__main__":
    scan_insiders()
