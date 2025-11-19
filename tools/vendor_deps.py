"""
Dependency Vendor Tool

Downloads and bundles Python dependencies into the plugin's vendor directory.
This ensures the plugin works on QGIS installations that lack standard libraries
(like requests, charset_normalizer) or have incompatible versions.

Usage:
    python3 tools/vendor_deps.py --refresh

Requirements:
    pip install pip  (usually available)
"""

import os
import sys
import shutil
import subprocess
import json
import hashlib
from pathlib import Path

# Configuration
VENDOR_DIR = Path(__file__).parent.parent / "vendor" / "site-packages"
MANIFEST_FILE = Path(__file__).parent.parent / "vendor" / "manifest.json"
CACHE_DIR = Path(__file__).parent.parent / ".vendor_cache"

# Critical dependencies to bundle
# Pinned versions to ensure stability across all deployments
REQUIREMENTS = [
    "requests==2.31.0",
    "urllib3==2.0.7",
    "charset-normalizer==3.3.2",
    "idna==3.4",
    "certifi==2023.7.22"
]

def clean_vendor_dir():
    """Remove existing vendor directory."""
    if VENDOR_DIR.exists():
        print(f"Cleaning {VENDOR_DIR}...")
        shutil.rmtree(VENDOR_DIR)
    VENDOR_DIR.mkdir(parents=True, exist_ok=True)

def download_wheels():
    """Download wheels to cache directory."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    
    print(f"Downloading dependencies to {CACHE_DIR}...")
    cmd = [
        sys.executable, "-m", "pip", "download",
        "--dest", str(CACHE_DIR),
        "--only-binary", ":all:",  # Prefer wheels
        "--platform", "any",       # Pure python only
        "--no-deps"                # We specify exact deps list
    ] + REQUIREMENTS
    
    subprocess.check_call(cmd)

def install_deps():
    """Install dependencies into vendor directory."""
    print(f"Installing dependencies to {VENDOR_DIR}...")
    
    # We use pip install --target to extract into the folder
    cmd = [
        sys.executable, "-m", "pip", "install",
        "--target", str(VENDOR_DIR),
        "--no-deps",
        "--upgrade",
        "--no-compile"  # Don't generate .pyc files (saves space/issues)
    ] + REQUIREMENTS
    
    subprocess.check_call(cmd)
    
    # Cleanup useless metadata directories to save space
    # (Keep .dist-info for version checks if needed, but remove others)
    for item in VENDOR_DIR.glob("*.dist-info"):
        # specific cleanup if strictly necessary, but dist-info is useful for pkg_resources
        pass
        
    for item in VENDOR_DIR.glob("__pycache__"):
        shutil.rmtree(item)

def generate_manifest():
    """Generate a manifest of bundled dependencies."""
    manifest = {
        "generated_at": subprocess.check_output(["date", "-u", "+%Y-%m-%dT%H:%M:%SZ"]).decode().strip(),
        "packages": {}
    }
    
    for req in REQUIREMENTS:
        name, version = req.split("==")
        manifest["packages"][name] = version
        
    with open(MANIFEST_FILE, "w") as f:
        json.dump(manifest, f, indent=2)
        
    print(f"Manifest written to {MANIFEST_FILE}")

def main():
    if "--refresh" not in sys.argv:
        print(__doc__)
        print("Run with --refresh to bundle dependencies.")
        return

    try:
        clean_vendor_dir()
        # download_wheels() # Optional: caching step
        install_deps()
        generate_manifest()
        print("\nSUCCESS: Dependencies bundled in vendor/site-packages/")
        print(f"Don't forget to commit 'vendor/'")
        
    except subprocess.CalledProcessError as e:
        print(f"\nERROR: Command failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\nERROR: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()

