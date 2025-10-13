# -*- coding: utf-8 -*-
"""
File CSV Provider

Reads tracking data from Traccar CSV exports.
This is a transitional provider for teams currently using CSV workflow.
"""

import os
import csv
import glob
from typing import List, Dict, Optional, Any, Tuple
from datetime import datetime
from .base import Provider, FeatureDict


class FileCSVProvider(Provider):
    """
    CSV provider for transitional period.
    Reads from Traccar CSV exports (team's current workflow).
    
    Expected CSV format (Traccar route export):
    - Header rows with metadata
    - Column headers: Valid, Time, Latitude, Longitude, Altitude, Speed, Address, Attributes
    - Data rows with position information
    """

    def __init__(self, csv_path: str):
        """
        Initialize CSV provider.
        
        Args:
            csv_path: Path to CSV file or folder containing CSV files
        """
        self.csv_path = csv_path
        self.is_folder = os.path.isdir(csv_path)
        
    def _parse_attributes(self, attr_string: str) -> Dict[str, Any]:
        """
        Parse Traccar attributes string.
        
        Example: "batteryLevel=98.0  distance=29038.25  totalDistance=607086.36  motion=true"
        
        Returns:
            Dict with parsed attributes
        """
        attrs = {}
        if not attr_string:
            return attrs
            
        # Split by double spaces or single spaces
        parts = attr_string.strip().split()
        
        for part in parts:
            if '=' in part:
                key, value = part.split('=', 1)
                # Try to convert to appropriate type
                try:
                    if '.' in value:
                        attrs[key] = float(value)
                    elif value.lower() == 'true':
                        attrs[key] = True
                    elif value.lower() == 'false':
                        attrs[key] = False
                    else:
                        attrs[key] = value
                except ValueError:
                    attrs[key] = value
                    
        return attrs
    
    def _parse_csv_file(self, filepath: str) -> Tuple[str, List[FeatureDict]]:
        """
        Parse a single CSV file.
        
        Returns:
            Tuple of (device_name, list of positions)
        """
        device_name = os.path.basename(filepath).replace('.csv', '')
        positions = []
        
        with open(filepath, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            
            # Extract device name from header (line 4: "Device:,eoc,,,,,,")
            for line in lines[:10]:  # Check first 10 lines for device name
                if line.startswith('Device:'):
                    parts = line.strip().split(',')
                    if len(parts) > 1 and parts[1]:
                        device_name = parts[1]
                    break
            
            # Find the header row (contains "Valid,Time,Latitude")
            header_idx = -1
            for i, line in enumerate(lines):
                if 'Valid' in line and 'Time' in line and 'Latitude' in line:
                    header_idx = i
                    break
            
            if header_idx == -1:
                return device_name, []
            
            # Parse CSV data starting after header
            reader = csv.DictReader(lines[header_idx:])
            
            for row in reader:
                # Skip invalid rows
                if row.get('Valid', '').strip().upper() not in ('TRUE', '1'):
                    continue
                
                try:
                    # Parse attributes
                    attrs = self._parse_attributes(row.get('Attributes', ''))
                    
                    # Build position dict
                    position = {
                        'device_id': device_name,
                        'name': device_name,
                        'lat': float(row['Latitude']),
                        'lon': float(row['Longitude']),
                        'ts': row['Time'],  # Keep as string (ISO format)
                        'altitude': float(row['Altitude'].replace(' m', '')) if row.get('Altitude') else None,
                        'speed': float(row['Speed'].replace(' kn', '')) if row.get('Speed') else None,
                        'battery': attrs.get('batteryLevel'),
                        'motion': attrs.get('motion', True),
                        'distance': attrs.get('distance'),
                        'total_distance': attrs.get('totalDistance')
                    }
                    
                    positions.append(position)
                    
                except (ValueError, KeyError) as e:
                    # Skip malformed rows
                    continue
        
        return device_name, positions
    
    def _get_csv_files(self) -> List[str]:
        """Get list of CSV files to process."""
        if self.is_folder:
            return glob.glob(os.path.join(self.csv_path, '*.csv'))
        else:
            return [self.csv_path] if os.path.exists(self.csv_path) else []
    
    def get_current(self) -> List[FeatureDict]:
        """
        Get latest position per device from CSV files.
        
        Returns:
            List of latest positions (one per device)
        """
        current_positions = {}
        
        csv_files = self._get_csv_files()
        
        for csv_file in csv_files:
            device_name, positions = self._parse_csv_file(csv_file)
            
            if positions:
                # Get most recent position (last in list, assuming time-ordered)
                latest = positions[-1]
                current_positions[device_name] = latest
        
        return list(current_positions.values())
    
    def get_breadcrumbs(self, since_iso: Optional[str] = None,
                       mission_id: Optional[int] = None) -> List[FeatureDict]:
        """
        Get all positions from CSV files.
        
        Args:
            since_iso: Optional ISO timestamp to filter from
            mission_id: Ignored for CSV provider
            
        Returns:
            List of all positions, time-ordered
        """
        all_positions = []
        
        csv_files = self._get_csv_files()
        
        for csv_file in csv_files:
            device_name, positions = self._parse_csv_file(csv_file)
            
            # Filter by time if specified
            if since_iso:
                since_dt = datetime.fromisoformat(since_iso.replace('Z', '+00:00'))
                positions = [
                    p for p in positions
                    if datetime.fromisoformat(p['ts'].replace('Z', '+00:00')) >= since_dt
                ]
            
            all_positions.extend(positions)
        
        # Sort by device then time
        all_positions.sort(key=lambda x: (x['device_id'], x['ts']))
        
        return all_positions
    
    def get_devices(self) -> List[Dict[str, Any]]:
        """
        Get list of devices from CSV files.
        
        Returns:
            List of device dicts
        """
        devices = {}
        
        csv_files = self._get_csv_files()
        
        for csv_file in csv_files:
            device_name, positions = self._parse_csv_file(csv_file)
            
            if positions:
                last_position = positions[-1]
                devices[device_name] = {
                    'device_id': device_name,
                    'name': device_name,
                    'status': 'online',  # Assume online for CSV
                    'last_update': last_position['ts']
                }
        
        return list(devices.values())
    
    def save_casualty(self, mission_id: int, name: str,
                     lat: float, lon: float,
                     irish_grid_e: Optional[float] = None,
                     irish_grid_n: Optional[float] = None,
                     description: str = "") -> int:
        """
        CSV provider does not support saving casualties.
        
        Raises:
            NotImplementedError
        """
        raise NotImplementedError("CSV provider does not support saving casualties")
    
    def save_poi(self, mission_id: int, name: str,
                lat: float, lon: float,
                poi_type: str = "",
                irish_grid_e: Optional[float] = None,
                irish_grid_n: Optional[float] = None,
                description: str = "",
                color: str = "#007BFF") -> int:
        """
        CSV provider does not support saving POIs.
        
        Raises:
            NotImplementedError
        """
        raise NotImplementedError("CSV provider does not support saving POIs")
    
    def test_connection(self) -> bool:
        """
        Test if CSV file(s) exist and can be read.
        
        Returns:
            True if CSV files found and readable
        """
        try:
            csv_files = self._get_csv_files()
            return len(csv_files) > 0
        except Exception:
            return False
