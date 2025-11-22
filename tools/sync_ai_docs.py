#!/usr/bin/env python3
"""
Synchronize critical sections between AGENTS.md and CLAUDE.md

This script ensures that safety-critical information remains consistent
across both AI documentation files while preserving tool-specific content.
"""

import re
import sys
from pathlib import Path
from datetime import datetime
from typing import Tuple, Optional

class AIDocSynchronizer:
    """Synchronize AI documentation files."""

    def __init__(self, project_root: Path = None):
        """Initialize synchronizer.

        Args:
            project_root: Project root directory (defaults to script parent.parent)
        """
        if project_root is None:
            project_root = Path(__file__).parent.parent

        self.project_root = project_root
        self.claude_md = project_root / "CLAUDE.md"
        self.agents_md = project_root / "AGENTS.md"

        # Sections to synchronize
        self.sync_sections = [
            "CRITICAL SAFETY CONTEXT",
            "PROJECT OVERVIEW",
            "Version"
        ]

    def extract_section(self, content: str, section_name: str) -> Optional[str]:
        """Extract a section from markdown content.

        Args:
            content: Markdown content
            section_name: Name of section to extract

        Returns:
            Section content or None if not found
        """
        # Try different header patterns
        patterns = [
            rf'##\s*🚨?\s*{re.escape(section_name)}.*?(?=\n##|\n---|\Z)',
            rf'##\s*{re.escape(section_name)}.*?(?=\n##|\n---|\Z)',
            rf'###\s*{re.escape(section_name)}.*?(?=\n###|\n##|\n---|\Z)'
        ]

        for pattern in patterns:
            match = re.search(pattern, content, re.DOTALL | re.IGNORECASE)
            if match:
                return match.group(0).strip()

        return None

    def extract_version_info(self, content: str) -> Tuple[Optional[str], Optional[str]]:
        """Extract version and date from content.

        Args:
            content: Markdown content

        Returns:
            Tuple of (version, date) or (None, None)
        """
        version_match = re.search(r'\*\*Version:\*\*\s*([\d.]+)', content)
        date_match = re.search(r'\*\*Last Updated:\*\*\s*([\d-]+)', content)

        version = version_match.group(1) if version_match else None
        date = date_match.group(1) if date_match else None

        return version, date

    def update_section(self, content: str, section_name: str, new_content: str) -> str:
        """Update or insert a section in markdown content.

        Args:
            content: Original markdown content
            section_name: Name of section to update
            new_content: New content for section

        Returns:
            Updated markdown content
        """
        # Check if section exists
        existing = self.extract_section(content, section_name)

        if existing:
            # Replace existing section
            patterns = [
                rf'##\s*🚨?\s*{re.escape(section_name)}.*?(?=\n##|\n---|\Z)',
                rf'##\s*{re.escape(section_name)}.*?(?=\n##|\n---|\Z)'
            ]

            for pattern in patterns:
                if re.search(pattern, content, re.DOTALL | re.IGNORECASE):
                    return re.sub(
                        pattern,
                        new_content,
                        content,
                        flags=re.DOTALL | re.IGNORECASE
                    )

        # Insert after first heading if not found
        lines = content.split('\n')
        for i, line in enumerate(lines):
            if line.startswith('# '):
                # Insert after main heading and any immediate description
                insert_pos = i + 1
                while insert_pos < len(lines) and lines[insert_pos].strip() and not lines[insert_pos].startswith('#'):
                    insert_pos += 1

                lines.insert(insert_pos, '')
                lines.insert(insert_pos + 1, new_content)
                return '\n'.join(lines)

        # Fallback: append at end
        return content + '\n\n' + new_content

    def sync_safety_context(self) -> bool:
        """Sync safety context from CLAUDE.md to AGENTS.md.

        Returns:
            True if synchronized, False otherwise
        """
        if not self.claude_md.exists():
            print(f"✗ {self.claude_md} not found")
            return False

        if not self.agents_md.exists():
            print(f"✗ {self.agents_md} not found")
            return False

        claude_content = self.claude_md.read_text()
        agents_content = self.agents_md.read_text()

        # Extract safety section from CLAUDE.md
        safety_section = self.extract_section(claude_content, "CRITICAL SAFETY CONTEXT")

        if not safety_section:
            print("⚠ Safety context not found in CLAUDE.md")
            return False

        # Clean up Claude-specific formatting
        safety_clean = safety_section.replace('🚨 ', '')
        safety_clean = re.sub(r'^##\s*', '## ', safety_clean)

        # Update AGENTS.md
        updated_content = self.update_section(
            agents_content,
            "Critical Safety Context",
            safety_clean
        )

        if updated_content != agents_content:
            self.agents_md.write_text(updated_content)
            print("✓ Safety context synchronized")
            return True
        else:
            print("✓ Safety context already in sync")
            return True

    def sync_version_info(self) -> bool:
        """Sync version information between files.

        Returns:
            True if synchronized, False otherwise
        """
        if not self.claude_md.exists() or not self.agents_md.exists():
            return False

        claude_content = self.claude_md.read_text()
        agents_content = self.agents_md.read_text()

        # Extract version from CLAUDE.md project overview
        claude_version, _ = self.extract_version_info(claude_content)

        if claude_version:
            # Update version in AGENTS.md
            updated = re.sub(
                r'(\*\*Version:\*\*\s*)[\d.]+',
                rf'\g<1>{claude_version}',
                agents_content
            )

            if updated != agents_content:
                self.agents_md.write_text(updated)
                print(f"✓ Version updated to {claude_version}")
                return True

        return True

    def update_timestamps(self) -> None:
        """Update Last Updated timestamp in both files."""
        today = datetime.now().strftime("%Y-%m-%d")

        for file_path in [self.claude_md, self.agents_md]:
            if file_path.exists():
                content = file_path.read_text()
                updated = re.sub(
                    r'(\*\*Last Updated:\*\*\s*)[\d-]+',
                    rf'\g<1>{today}',
                    content
                )
                if updated != content:
                    file_path.write_text(updated)
                    print(f"✓ Updated timestamp in {file_path.name}")

    def validate_cross_references(self) -> bool:
        """Validate that cross-references between files are correct.

        Returns:
            True if all references valid, False otherwise
        """
        valid = True

        # Check AGENTS.md references to CLAUDE.md
        if self.agents_md.exists():
            agents_content = self.agents_md.read_text()

            # Check for CLAUDE.md references
            claude_refs = re.findall(r'\[([^\]]+)\]\(\.\/CLAUDE\.md[^)]*\)', agents_content)

            if not claude_refs:
                print("⚠ AGENTS.md should reference CLAUDE.md")
                valid = False
            elif not self.claude_md.exists():
                print("✗ AGENTS.md references non-existent CLAUDE.md")
                valid = False
            else:
                print(f"✓ Found {len(claude_refs)} references to CLAUDE.md")

        # Check CLAUDE.md references to AGENTS.md
        if self.claude_md.exists():
            claude_content = self.claude_md.read_text()

            # Check for AGENTS.md references
            agents_refs = re.findall(r'\[([^\]]+)\]\(\.\/AGENTS\.md[^)]*\)', claude_content)

            if agents_refs and not self.agents_md.exists():
                print("✗ CLAUDE.md references non-existent AGENTS.md")
                valid = False
            elif agents_refs:
                print(f"✓ Found {len(agents_refs)} references to AGENTS.md")

        return valid

    def generate_report(self) -> str:
        """Generate a synchronization report.

        Returns:
            Report as string
        """
        report = ["AI Documentation Synchronization Report", "=" * 40, ""]

        # Check file existence
        for name, path in [("CLAUDE.md", self.claude_md), ("AGENTS.md", self.agents_md)]:
            if path.exists():
                size = path.stat().st_size
                lines = len(path.read_text().splitlines())
                report.append(f"✓ {name}: {lines} lines ({size:,} bytes)")
            else:
                report.append(f"✗ {name}: Not found")

        report.append("")

        # Check version sync
        if self.claude_md.exists() and self.agents_md.exists():
            claude_version, claude_date = self.extract_version_info(self.claude_md.read_text())
            agents_version, agents_date = self.extract_version_info(self.agents_md.read_text())

            report.append("Version Information:")
            report.append(f"  CLAUDE.md: v{claude_version or 'unknown'} ({claude_date or 'unknown'})")
            report.append(f"  AGENTS.md: v{agents_version or 'unknown'} ({agents_date or 'unknown'})")

            if claude_version == agents_version:
                report.append("  ✓ Versions match")
            else:
                report.append("  ⚠ Version mismatch")

        return "\n".join(report)

    def run(self, auto_fix: bool = False) -> int:
        """Run synchronization.

        Args:
            auto_fix: Automatically fix issues if True

        Returns:
            0 on success, 1 on failure
        """
        print("🔄 Synchronizing AI documentation files...\n")

        # Generate initial report
        print(self.generate_report())
        print()

        if auto_fix:
            print("🔧 Running auto-fix...\n")

            # Sync critical sections
            self.sync_safety_context()
            self.sync_version_info()
            self.update_timestamps()

        # Validate references
        print("\n📋 Validating cross-references...")
        if not self.validate_cross_references():
            print("⚠ Some cross-references need attention")
            return 1

        print("\n✅ Synchronization complete!")
        return 0


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Synchronize AI documentation files (AGENTS.md and CLAUDE.md)"
    )
    parser.add_argument(
        "--auto",
        action="store_true",
        help="Automatically fix synchronization issues"
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="Generate report only, don't modify files"
    )
    parser.add_argument(
        "--path",
        type=Path,
        help="Project root path (defaults to script location)"
    )

    args = parser.parse_args()

    syncer = AIDocSynchronizer(project_root=args.path)

    if args.report:
        print(syncer.generate_report())
        return 0

    return syncer.run(auto_fix=args.auto)


if __name__ == "__main__":
    sys.exit(main())