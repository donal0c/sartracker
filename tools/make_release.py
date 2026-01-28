#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SAR Tracker Release Packaging Script

Creates a release ZIP file with version validation and import guards.
"""

import os
import sys
import zipfile
import subprocess
import argparse
from datetime import datetime
from fnmatch import fnmatch
from pathlib import Path


def check_forbidden_imports(plugin_dir):
    """
    Check for direct PyQt5/PyQt6 imports (forbidden).

    Args:
        plugin_dir: Path to plugin directory

    Returns:
        tuple: (has_violations: bool, violations: list)
    """
    print("🔍 Checking for forbidden PyQt5/PyQt6 imports...")

    violations = []
    import re
    pattern = re.compile(r'\bfrom PyQt[56]\b')

    # Walk through all Python files
    for root, dirs, files in os.walk(plugin_dir):
        # Skip hidden directories and __pycache__
        dirs[:] = [d for d in dirs if not d.startswith('.') and d != '__pycache__']

        for file in files:
            if file.endswith('.py'):
                file_path = os.path.join(root, file)
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        for line_num, line in enumerate(f, 1):
                            if pattern.search(line):
                                rel_path = os.path.relpath(file_path, plugin_dir)
                                violations.append(f"{rel_path}:{line_num}: {line.strip()}")
                except:
                    pass  # Skip files that can't be read

    return len(violations) > 0, violations


def get_git_info(plugin_dir):
    """
    Get current git SHA if available.

    Args:
        plugin_dir: Path to plugin directory

    Returns:
        str: Git SHA or "no-git"
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            cwd=plugin_dir,
            text=True
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except:
        pass

    return "no-git"


def create_version_file(plugin_dir, version):
    """
    Create VERSION.txt with build metadata.

    Args:
        plugin_dir: Path to plugin directory
        version: Version string
    """
    git_sha = get_git_info(plugin_dir)
    build_date = datetime.now().isoformat()

    version_content = f"""Version: {version}
Build Date: {build_date}
Git SHA: {git_sha}
"""

    version_path = os.path.join(plugin_dir, "VERSION.txt")
    with open(version_path, 'w') as f:
        f.write(version_content)

    print(f"✓ Created VERSION.txt (Git SHA: {git_sha})")


# The plugin folder name MUST be 'sartracker' for QGIS to load it correctly
PLUGIN_NAME = "sartracker"

EXCLUDED_DIRS = {
    ".git",
    ".github",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".idea",
    ".vscode",
    ".claude",
    ".beads",
    "dist",
    "build",
    "archive",
    "docs",
    "dev_tools",
    "fixtures",
    "From_Eamon",
    "tests",
    "FUTURE_WORK",
    "research",
    "bug_reports_run2",
}

EXCLUDED_FILE_PATTERNS = {
    "*.pyc",
    "*.pyo",
    "*.pyd",
    "*.swp",
    "*.swo",
    "*.tmp",
    "*.log",
    "*.bak",
    ".*.swp",
    "Thumbs.db",
    ".DS_Store",
}

CRITICAL_VENDOR_FILES = [
    Path("vendor/site-packages/certifi/cacert.pem"),
]


def _should_skip_file(filename: str) -> bool:
    return any(fnmatch(filename, pattern) for pattern in EXCLUDED_FILE_PATTERNS)


def create_release_zip(plugin_dir, version, output_dir=None):
    """
    Create release ZIP file.

    Args:
        plugin_dir: Path to plugin directory
        version: Version string
        output_dir: Optional output directory (default: plugin_dir parent)

    Returns:
        str: Path to created ZIP file
    """
    plugin_dir = Path(plugin_dir).resolve()

    if output_dir is None:
        output_dir = plugin_dir.parent
    else:
        output_dir = Path(output_dir).resolve()

    # Create ZIP filename
    date_str = datetime.now().strftime("%Y-%m-%d")
    zip_filename = f"sartracker-v{version}-{date_str}.zip"
    zip_path = output_dir / zip_filename

    print(f"📦 Creating release ZIP: {zip_filename}")
    print(f"   Internal folder name: {PLUGIN_NAME}/")

    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        files_added = 0
        total_size = 0

        for root, dirs, files in os.walk(plugin_dir):
            root_path = Path(root)

            # Filter directories in-place
            dirs[:] = [
                d for d in dirs
                if d not in EXCLUDED_DIRS and not any(fnmatch(d, pattern) for pattern in EXCLUDED_FILE_PATTERNS)
            ]

            for file in files:
                if _should_skip_file(file):
                    continue

                file_path = root_path / file

                # Skip files living in excluded ancestors (defensive check for symlinks)
                rel_parts = file_path.relative_to(plugin_dir).parts
                if any(part in EXCLUDED_DIRS for part in rel_parts[:-1]):
                    continue

                # Always use 'sartracker/' as the archive folder name, regardless of
                # what the source directory is called (fixes sartracker-master issue)
                rel_path_from_plugin = file_path.relative_to(plugin_dir)
                archive_path = Path(PLUGIN_NAME) / rel_path_from_plugin
                zipf.write(str(file_path), str(archive_path))
                files_added += 1
                total_size += file_path.stat().st_size

        # Verify critical vendor assets made it into the source tree (before zipping)
        missing_vendor_assets = [
            str(asset) for asset in CRITICAL_VENDOR_FILES
            if not (plugin_dir / asset).exists()
        ]
        if missing_vendor_assets:
            print("⚠ WARNING: Missing vendor assets:")
            for asset in missing_vendor_assets:
                print(f"   - {asset}")
            print("   The release was created, but SSL/TLS requests may fail without these files.")


        print(f"✓ Added {files_added} files ({total_size / 1024:.1f} KB)")

    return str(zip_path)


def main():
    """Main function."""
    parser = argparse.ArgumentParser(description="Create SAR Tracker release package")
    parser.add_argument("--version", required=True, help="Version number (e.g., 0.3.1)")
    parser.add_argument("--output", help="Output directory (default: parent of plugin dir)")
    parser.add_argument("--force", action="store_true", help="Skip import guard checks")

    args = parser.parse_args()

    # Get plugin directory (parent of tools/)
    plugin_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    print("=" * 70)
    print("SAR TRACKER RELEASE PACKAGER")
    print("=" * 70)
    print(f"Plugin Directory: {plugin_dir}")
    print(f"Version: {args.version}")
    print()

    # Check for forbidden imports (unless --force)
    if not args.force:
        has_violations, violations = check_forbidden_imports(plugin_dir)

        if has_violations:
            print("❌ ERROR: Direct PyQt5/PyQt6 imports found:")
            print()
            for violation in violations:
                print(f"   {violation}")
            print()
            print("⚠️  Use 'from qgis.PyQt' instead!")
            print("   Run with --force to skip this check.")
            return 1
        else:
            print("✓ No forbidden imports found")

    # Create VERSION.txt
    create_version_file(plugin_dir, args.version)

    # Create release ZIP
    try:
        zip_path = create_release_zip(plugin_dir, args.version, args.output)
        print()
        print("=" * 70)
        print("✅ RELEASE PACKAGE CREATED")
        print("=" * 70)
        print(f"File: {zip_path}")
        print(f"Size: {os.path.getsize(zip_path) / 1024 / 1024:.2f} MB")
        print()
        print("Next steps:")
        print("1. Test the ZIP in a clean QGIS installation")
        print("2. Upload to GitHub releases")
        print("3. Update QGIS plugin repository")
        return 0

    except Exception as e:
        print(f"❌ ERROR: Failed to create release package: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
