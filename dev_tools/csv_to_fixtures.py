"""
Convert Glenagenty.csv to Traccar API-compatible fixture JSON files.

This script processes the CSV export from Eamon and generates:
- devices.json - List of tracked devices
- routes.json - Full position history

These files are used by the mock Traccar server for development.
"""

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Optional


ISO_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def _parse_iso(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace('Z', '+00:00')).astimezone(timezone.utc)


def _format_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime(ISO_FORMAT)


def _shift_routes(routes: List[Dict], target_start: datetime):
    if not routes:
        return

    original_start = _parse_iso(routes[0]['fixTime'])
    delta = target_start - original_start

    for route in routes:
        for key in ('fixTime', 'serverTime'):
            original_dt = _parse_iso(route[key])
            route[key] = _format_iso(original_dt + delta)


def parse_csv_to_fixtures(csv_path,
                          output_dir,
                          shift_start: Optional[datetime] = None,
                          align_last_to_now: bool = False):
    """
    Parse Glenagenty.csv and create fixture JSON files.

    Args:
        csv_path: Path to Glenagenty.csv
        output_dir: Directory to write fixture files
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(exist_ok=True)

    routes: List[Dict] = []

    with open(csv_path, 'r', encoding='utf-8') as f:
        raw_reader = csv.reader(f)

        # Skip preamble rows until we reach the header that starts with "Valid"
        header = None
        for row in raw_reader:
            if not row or not any(cell.strip() for cell in row):
                continue
            if row[0].strip().lower() == 'valid':
                header = [cell.strip() for cell in row]
                break

        if not header:
            raise ValueError("Could not find header row starting with 'Valid' in CSV")

        reader = csv.DictReader(f, fieldnames=header)

        for row in reader:
            valid_value = (row.get('Valid') or '').strip().upper()
            if valid_value not in ('TRUE', '1'):
                continue

            timestamp = (row.get('Time') or '').strip()
            if not timestamp:
                continue

            try:
                lat = float(row['Latitude'])
                lon = float(row['Longitude'])

                # Extract altitude (remove ' m' suffix)
                altitude_str = row.get('Altitude', '0 m').replace(' m', '').strip()
                altitude = float(altitude_str) if altitude_str else 0.0

                # Extract speed (remove ' kn' suffix)
                speed_str = row.get('Speed', '0 kn').replace(' kn', '').strip()
                speed = float(speed_str) if speed_str else 0.0

                # Parse attributes (batteryLevel, distance, motion, etc.)
                attributes_str = row.get('Attributes', '')
                attributes = {}

                if attributes_str:
                    # Parse "key=value  key=value" format
                    for pair in attributes_str.split('  '):
                        if '=' in pair:
                            key, value = pair.split('=', 1)
                            key = key.strip()
                            value = value.strip()

                            # Convert numeric values
                            try:
                                if '.' in value:
                                    attributes[key] = float(value)
                                else:
                                    attributes[key] = int(value)
                            except ValueError:
                                attributes[key] = value

                # Device is from "Device:" row at top (use "eoc" as default)
                device_id = 1
                device_name = "eoc"

                # Create Traccar-compatible route entry
                route_entry = {
                    'id': len(routes) + 1,
                    'deviceId': device_id,
                    'fixTime': timestamp.replace(' ', 'T') + 'Z',  # Convert to ISO 8601
                    'serverTime': timestamp.replace(' ', 'T') + 'Z',
                    'latitude': lat,
                    'longitude': lon,
                    'altitude': altitude,
                    'speed': speed,
                    'valid': True,
                    'attributes': attributes
                }

                routes.append(route_entry)

            except (ValueError, KeyError) as e:
                # Skip malformed rows
                continue

    if shift_start:
        _shift_routes(routes, shift_start)
    elif align_last_to_now and routes:
        original_last = _parse_iso(routes[-1]['fixTime'])
        now_utc = datetime.now(timezone.utc)
        delta = now_utc - original_last
        target_start = _parse_iso(routes[0]['fixTime']) + delta
        _shift_routes(routes, target_start)

    # Create devices fixture
    devices_fixture = [
        {
            'id': 1,
            'name': 'eoc',
            'uniqueId': 'glenagenty_device_001',
            'status': 'online',
            'lastUpdate': routes[-1]['fixTime'] if routes else None,
            'category': 'person'
        }
    ]

    # Write fixtures
    with open(output_dir / 'devices.json', 'w', encoding='utf-8') as f:
        json.dump(devices_fixture, f, indent=2)

    with open(output_dir / 'routes.json', 'w', encoding='utf-8') as f:
        json.dump(routes, f, indent=2)

    print(f"✓ Created {len(devices_fixture)} devices")
    print(f"✓ Created {len(routes)} route points")
    if routes:
        print(f"✓ Time range: {routes[0]['fixTime']} to {routes[-1]['fixTime']}")
    else:
        print("⚠ No valid route points found in CSV (check 'Valid' column filtering).")
    print(f"✓ Fixtures written to {output_dir}")


def _parse_args():
    parser = argparse.ArgumentParser(description="Convert Glenagenty CSV to Traccar fixtures.")
    default_csv = Path(__file__).parent.parent / 'From_Eamon' / 'Glenagenty.csv'
    default_output = Path(__file__).parent.parent / 'fixtures'

    parser.add_argument('--csv', type=Path, default=default_csv, help="Path to source CSV (default: From_Eamon/Glenagenty.csv)")
    parser.add_argument('--output', type=Path, default=default_output, help="Output directory for fixtures (default: fixtures/)")
    parser.add_argument('--shift-to-now', action='store_true',
                        help="Shift timestamps so the last point aligns with current UTC time")
    parser.add_argument('--start-time',
                        help="Explicit ISO8601 start time (UTC) for the first point, overrides --shift-to-now")

    return parser.parse_args()


if __name__ == '__main__':
    args = _parse_args()

    shift_target = None
    if args.start_time:
        try:
            shift_target = _parse_iso(args.start_time)
        except ValueError as exc:
            raise SystemExit(f"Invalid --start-time '{args.start_time}': {exc}") from exc

    parse_csv_to_fixtures(
        csv_path=args.csv,
        output_dir=args.output,
        shift_start=shift_target,
        align_last_to_now=args.shift_to_now and not shift_target
    )
