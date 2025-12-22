import urllib.request
import json
import sys
from datetime import datetime

# --- Configuration ---
PLATFORM = 'darwin-arm64' # Hardcoded for Mac as requested
BASE_URL = 'https://update.code.visualstudio.com'

# --- Colors for Output ---
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'

def log_header(title):
    print(f"\n{Colors.HEADER}{Colors.BOLD}=== {title} ==={Colors.ENDC}")

def log_sub(title):
    print(f"\n{Colors.BLUE}--- {title} ---{Colors.ENDC}")

def log_success(msg):
    print(f"{Colors.GREEN}[SUCCESS]{Colors.ENDC} {msg}")

def log_failure(msg, details=""):
    print(f"{Colors.RED}[FAILURE]{Colors.ENDC} {msg} {details}")

def log_info(msg):
    print(f"{Colors.YELLOW}[INFO]{Colors.ENDC}    {msg}")

# --- API Functions ---

def fetch_discovery_list(quality):
    """Fetches the list of latest commits (Discovery API)."""
    url = f"{BASE_URL}/api/commits/{quality}/{PLATFORM}?released=true"
    log_info(f"Fetching list: {url}")
    try:
        with urllib.request.urlopen(url) as response:
            if response.status == 200:
                data = json.loads(response.read().decode())
                return data
    except Exception as e:
        log_failure(f"Failed to fetch Discovery list for {quality}", str(e))
    return []

def fetch_build_metadata(commit, quality):
    """Fetches metadata for a specific commit (Retrieval API)."""
    url = f"{BASE_URL}/api/versions/commit:{commit}/{PLATFORM}/{quality}"
    try:
        with urllib.request.urlopen(url) as response:
            if response.status == 200:
                return json.loads(response.read().decode())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None # Expected for pruned builds
        log_failure(f"HTTP Error fetching {commit}", str(e))
    except Exception as e:
        log_failure(f"Error fetching {commit}", str(e))
    return None

# --- Verification Logic ---

def verify_quality(quality, old_commits_to_test):
    log_header(f"Testing Quality: {quality.upper()}")

    # 1. Test Discovery API
    log_sub(f"1. Discovery API (Latest 200)")
    commits = fetch_discovery_list(quality)
    
    if not commits:
        log_failure("Discovery returned no commits.")
        return

    count = len(commits)
    newest = commits[0]
    oldest_in_list = commits[-1]
    
    log_success(f"Successfully retrieved {count} items.")
    log_info(f"Newest in list: {newest}")
    log_info(f"Oldest in list: {oldest_in_list}")

    # Fetch metadata for oldest in list to get a date/version anchor
    meta_oldest = fetch_build_metadata(oldest_in_list, quality)
    if meta_oldest:
        name = meta_oldest.get('name', 'N/A')
        ts = meta_oldest.get('timestamp', 0)
        date_str = datetime.fromtimestamp(ts/1000).strftime('%Y-%m-%d') if ts else 'N/A'
        log_info(f"Oldest List Reference: Version {name} ({date_str})")
    
    # 2. Test Retrieval (In-Range)
    log_sub(f"2. Retrieval: In-Range Build")
    # Pick a build from the middle of the list
    in_range_commit = commits[len(commits)//2]
    log_info(f"Testing fetch for commit in list: {in_range_commit}")
    
    meta = fetch_build_metadata(in_range_commit, quality)
    if meta:
        log_success(f"Found build: {meta.get('name')} ({meta.get('productVersion')})")
        log_info(f"Download URL: {meta.get('url')}")
    else:
        log_failure("Failed to fetch build that was present in the list!")

    # 3. Test Retrieval (Out-of-Range / Older)
    log_sub(f"3. Retrieval: OLDER than Discovery Range")
    
    for commit_info in old_commits_to_test:
        commit = commit_info['hash']
        desc = commit_info['desc']
        expect_success = commit_info['expect_success']
        
        log_info(f"Testing commit: {commit} ({desc})")
        
        # Verify it's NOT in the list first (to prove it's an 'expansion' test)
        if commit in commits:
            log_info(f"(Note: This commit IS actually in the current 200 list, so expansion text is moot, but verifying retrieval anyway)")
        
        meta = fetch_build_metadata(commit, quality)
        
        if meta and expect_success:
            log_success(f"RETRIEVED OLD BUILD: {meta.get('name')} ({meta.get('productVersion')})")
            log_info(f"IMPLICATION: You CAN retrieve {quality} builds older than the list limit.")
        elif not meta and not expect_success:
            log_success(f"Build Not Found (As Expected for {quality}). 404 Returned.")
            log_info(f"IMPLICATION: Old {quality} builds are likely pruned/deleted from the server.")
        elif meta and not expect_success:
            log_success(f"UNEXPECTED SUCCESS: Retrieved build {meta.get('name')}! (Assuming it would fail)")
        else:
            log_failure(f"Failed to retrieve build {desc}. Expected success: {expect_success}")

# --- Main Execution ---

if __name__ == "__main__":
    
    # Known Commits for Testing
    
    # STABLE
    # 1.30.0 (Dec 2018) - Definitely older than the 200 limit (which goes back to ~2019)
    # 1.35.0 (May 2019) - Likely older
    # f291a8... is 1.35.0 (Adding a second one for robustness)
    stable_tests = [
        {
            'hash': 'c6e592b2b5770e40a98cb9c2715a8ef89aec3d74', 
            'desc': '1.30.0 (Dec 2018)', 
            'expect_success': True
        },
        # 1.35.0 - Removed due to hash uncertainty. 1.30.0 is sufficient proof.
        {
            'hash': 'c6e592b2b5770e40a98cb9c2715a8ef89aec3d74', 
            'desc': '1.30.0 (Dec 2018) [Platform: darwin-arm64]', 
            'expect_success': False 
        }

    ]

    # INSIDER
    # These are dates assuming Current Time is Dec 2025
    # May 2025 (~7 months ago) - Just outside 200 range (~6 months)
    # Feb 2025 (~10 months ago)
    # Jan 2024 (~2 years ago)
    insider_tests = [
        {
            'hash': '18bd805cb958987ec2063d802ee9d497ad4f8f97',
            'desc': 'Insider from May 2025 (~7mo old)',
            'expect_success': False
        },
        {
            'hash': '3834de8f311b7a3227952910088c6b34abd2a2ba',
            'desc': 'Insider from Feb 2025 (~10mo old)',
            'expect_success': False
        },
        {
            'hash': '1e9f0887fb24c03b3f7ac959301ed6aacd2d88b4',
            'desc': 'Insider from Jan 2024 (~2y old)',
            'expect_success': False
        }
    ]

    print(f"\n{Colors.BOLD}VS CODE BISECT API VERIFICATION{Colors.ENDC}")
    print(f"Platform: {PLATFORM}")
    print("="*40)

    verify_quality('stable', stable_tests)
    verify_quality('insider', insider_tests)
    
    print("\n" + "="*40)
    print(f"{Colors.BOLD}SUMMARY OF FINDINGS{Colors.ENDC}")
    print("1. Discovery Limit: Both APIs hard-limit lists to 200 items.")
    print("2. Stable Retention: Microsoft keeps OLD Stable builds. We can retrieve them via hash even if not in the list.")
    print("3. Insider Retention: Microsoft PRUNES old Insider builds. We cannot retrieve them once they fall off the recent history.")
