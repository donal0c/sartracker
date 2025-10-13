"""
Convert Glenagenty.csv to Traccar API-compatible fixture JSON files.

This script processes the CSV export from Eamon and generates:
- devices.json - List of tracked devices
- routes.json - Full position history

These files are used by the mock Traccar server for development.
"""

import csv
import json
from datetime import datetime
from pathlib import Path


def parse_csv_to_fixtures(csv_path, output_dir):
    """
    Parse Glenagenty.csv and create fixture JSON files.

    Args:
        csv_path: Path to Glenagenty.csv
        output_dir: Directory to write fixture files
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(exist_ok=True)

    routes = []
    devices = set()

    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)

        for row in reader:
            # Skip header rows
            if row.get('Valid') not in ['TRUE', '1']:
                continue

            try:
                # Parse CSV row
                timestamp = row['Time']
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
                devices.add(device_name)

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
    with open(output_dir / 'devices.json', 'w') as f:
        json.dump(devices_fixture, f, indent=2)

    with open(output_dir / 'routes.json', 'w') as f:
        json.dump(routes, f, indent=2)

    print(f"✓ Created {len(devices_fixture)} devices")
    print(f"✓ Created {len(routes)} route points")
    print(f"✓ Time range: {routes[0]['fixTime']} to {routes[-1]['fixTime']}")
    print(f"✓ Fixtures written to {output_dir}")


if __name__ == '__main__':
    csv_path = Path(__file__).parent.parent / 'From_Eamon' / 'Glenagenty.csv'
    output_dir = Path(__file__).parent.parent / 'fixtures'

    parse_csv_to_fixtures(csv_path, output_dir)
