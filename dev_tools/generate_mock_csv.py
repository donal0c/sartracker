#!/usr/bin/env python3
"""
Generate mock Traccar CSV files for testing

Creates realistic search team tracking data with multiple devices
"""

import random
from datetime import datetime, timedelta
import math


def generate_search_pattern(start_lat, start_lon, num_points=50, pattern="grid"):
    """
    Generate a realistic search pattern.
    
    Args:
        start_lat: Starting latitude
        start_lon: Starting longitude
        num_points: Number of GPS points to generate
        pattern: Search pattern type ("grid", "spiral", "linear")
    
    Returns:
        List of (lat, lon, altitude) tuples
    """
    points = []
    lat = start_lat
    lon = start_lon
    
    # Approximate degrees per meter at this latitude
    lat_per_m = 1 / 111000
    lon_per_m = 1 / (111000 * math.cos(math.radians(start_lat)))
    
    if pattern == "grid":
        # Grid search pattern
        leg_length = 200  # meters
        num_legs = int(math.sqrt(num_points))
        
        for i in range(num_points):
            leg = i // num_legs
            if leg % 2 == 0:
                # Move east
                lon = start_lon + (i % num_legs) * leg_length * lon_per_m
            else:
                # Move west
                lon = start_lon + (num_legs - 1 - (i % num_legs)) * leg_length * lon_per_m
            
            lat = start_lat + leg * leg_length * lat_per_m
            altitude = 150 + random.uniform(-20, 30)
            points.append((lat, lon, altitude))
            
    elif pattern == "spiral":
        # Spiral search pattern
        angle = 0
        radius = 0
        
        for i in range(num_points):
            radius = i * 5  # Expanding spiral
            angle += 0.3
            
            lat = start_lat + radius * lat_per_m * math.sin(angle)
            lon = start_lon + radius * lon_per_m * math.cos(angle)
            altitude = 160 + random.uniform(-15, 25)
            points.append((lat, lon, altitude))
            
    elif pattern == "linear":
        # Linear search along a ridge
        for i in range(num_points):
            lat = start_lat + i * 20 * lat_per_m
            lon = start_lon + random.uniform(-10, 10) * lon_per_m
            altitude = 170 + random.uniform(-10, 20)
            points.append((lat, lon, altitude))
    
    return points


def write_traccar_csv(filename, device_name, points, start_time):
    """
    Write points to Traccar CSV format.
    
    Args:
        filename: Output CSV filename
        device_name: Device identifier
        points: List of (lat, lon, altitude) tuples
        start_time: Starting datetime
    """
    with open(filename, 'w') as f:
        # Write header
        f.write("Position\n")
        f.write("\n")
        f.write("\n")
        f.write(f"Device:,{device_name},,,,,,\n")
        f.write("\n")
        f.write("Valid,Time,Latitude,Longitude,Altitude,Speed,Address,Attributes\n")
        
        # Write data points
        current_time = start_time
        battery = 100.0
        total_distance = 500000.0
        
        for i, (lat, lon, altitude) in enumerate(points):
            # Simulate realistic movement
            speed = random.uniform(0.5, 3.5)  # knots, walking speed
            distance = random.uniform(10, 40)  # meters between points
            total_distance += distance
            
            # Battery drain
            battery -= random.uniform(0.1, 0.3)
            battery = max(battery, 20)
            
            # Time progression (1-3 minutes between points)
            current_time += timedelta(minutes=random.uniform(1, 3))
            
            # Format timestamp
            time_str = current_time.strftime("%Y-%m-%d %H:%M:%S")
            
            # Motion status
            motion = "true" if speed > 0.5 else "false"
            
            # Attributes string
            attrs = f"batteryLevel={battery:.1f}  distance={distance:.2f}  totalDistance={total_distance:.2f}  motion={motion}"
            
            # Write row
            f.write(f"true,{time_str},{lat:.6f},{lon:.6f},{altitude:.1f} m,{speed:.1f} kn,,{attrs}\n")


def main():
    """Generate mock CSV files for 3 search teams"""
    
    # Base location (near Glenagenty)
    base_lat = 52.2704
    base_lon = -9.5456
    
    # Start time
    start_time = datetime(2025, 10, 12, 10, 0, 0)
    
    # Team 1: Grid search
    print("Generating Team Alpha (grid search)...")
    points1 = generate_search_pattern(
        base_lat, base_lon - 0.01,
        num_points=60,
        pattern="grid"
    )
    write_traccar_csv(
        "From_Eamon/mock_team_alpha.csv",
        "team-alpha",
        points1,
        start_time
    )
    
    # Team 2: Spiral search
    print("Generating Team Bravo (spiral search)...")
    points2 = generate_search_pattern(
        base_lat + 0.005, base_lon + 0.005,
        num_points=70,
        pattern="spiral"
    )
    write_traccar_csv(
        "From_Eamon/mock_team_bravo.csv",
        "team-bravo",
        points2,
        start_time + timedelta(minutes=15)
    )
    
    # Team 3: Linear search
    print("Generating Team Charlie (linear search)...")
    points3 = generate_search_pattern(
        base_lat - 0.005, base_lon,
        num_points=50,
        pattern="linear"
    )
    write_traccar_csv(
        "From_Eamon/mock_team_charlie.csv",
        "team-charlie",
        points3,
        start_time + timedelta(minutes=30)
    )
    
    print("\n✓ Generated 3 mock CSV files in From_Eamon/")
    print("  - mock_team_alpha.csv (60 points, grid pattern)")
    print("  - mock_team_bravo.csv (70 points, spiral pattern)")
    print("  - mock_team_charlie.csv (50 points, linear pattern)")


if __name__ == "__main__":
    main()
