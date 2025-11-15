#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Traccar HTTP mock server for local SAR Tracker development.

Features:
- Serves /api/devices, /api/positions, and /api/reports/route endpoints expected by the HTTP provider
- Enforces HTTP Basic authentication (defaults: DC/Superb, override via CLI/env)
- Reads fixtures/devices.json and fixtures/routes.json generated from Glenagenty.csv
- Plays back fixture data over time so the map shows movement (configurable speed, looping)

Usage:
    python dev_tools/traccar_stub.py --port 8082

Then in QGIS SAR Tracker:
    1. Set SARTRACKER_ENABLE_TRACCAR_HTTP=1 (or enable flag in QSettings)
    2. Base URL: http://127.0.0.1:8082
    3. Username: DC  Password: Superb (or the values you supplied)
"""

from __future__ import annotations

import argparse
import base64
import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURES_DIR = PROJECT_ROOT / "fixtures"


def _load_json(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _parse_iso(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace('Z', '+00:00')).astimezone(timezone.utc)
    except ValueError:
        return None


def _compute_latest(routes: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    latest: Dict[str, Dict[str, Any]] = {}
    for entry in routes:
        device_id = str(entry.get("deviceId"))
        if not device_id:
            continue
        current = latest.get(device_id)
        if current is None or entry.get("fixTime", "") > current.get("fixTime", ""):
            latest[device_id] = entry
    return latest


def _filter_routes(routes: List[Dict[str, Any]], device_id: str,
                   start_iso: Optional[str], end_iso: Optional[str],
                   max_time: Optional[datetime]) -> List[Dict[str, Any]]:
    filtered = []
    start_dt = _parse_iso(start_iso) if start_iso else None
    end_dt = _parse_iso(end_iso) if end_iso else None
    for entry in routes:
        if str(entry.get("deviceId")) != device_id:
            continue
        ts_str = entry.get("fixTime", "")
        ts = _parse_iso(ts_str)
        if ts is None:
            continue
        if start_dt and ts < start_dt:
            continue
        if end_dt and ts > end_dt:
            continue
        if max_time and ts > max_time:
            continue
        filtered.append(entry)
    return filtered


class TraccarStubHandler(BaseHTTPRequestHandler):
    server_version = "TraccarStub/1.0"

    # Silence default logging to avoid noisy stdout
    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003 - inherited signature
        if os.environ.get("SARTRACKER_STUB_VERBOSE") == "1":
            super().log_message(format, *args)

    def _send_json(self, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _unauthorized(self) -> None:
        self.send_response(HTTPStatus.UNAUTHORIZED)
        self.send_header("WWW-Authenticate", 'Basic realm="Traccar Stub"')
        self.end_headers()

    def _check_auth(self) -> bool:
        header = self.headers.get("Authorization", "")
        if not header.startswith("Basic "):
            return False
        try:
            decoded = base64.b64decode(header.split(" ", 1)[1]).decode("utf-8")
            username, password = decoded.split(":", 1)
        except Exception:
            return False

        return (
            username == self.server.username  # type: ignore[attr-defined]
            and password == self.server.password  # type: ignore[attr-defined]
        )

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        parsed = urlparse(self.path)

        if not self._check_auth():
            self._unauthorized()
            return

        if parsed.path == "/api/devices":
            self._send_json(self.server.devices)  # type: ignore[attr-defined]
            return

        current_track_time = self.server.current_track_time()

        if parsed.path == "/api/positions":
            params = parse_qs(parsed.query)
            device_ids = params.get("deviceId")
            start_iso = params.get("from", [None])[0]
            end_iso = params.get("to", [None])[0]

            if device_ids:
                device_id = device_ids[0]
                data = _filter_routes(
                    self.server.routes,  # type: ignore[attr-defined]
                    device_id,
                    start_iso,
                    end_iso,
                    current_track_time,
                )
                self._send_json(data)
            else:
                data = self.server.latest_positions_snapshot(current_track_time)  # type: ignore[attr-defined]
                self._send_json(data)
            return

        if parsed.path == "/api/reports/route":
            params = parse_qs(parsed.query)
            device_id = params.get("deviceId", [None])[0]
            if not device_id:
                self.send_error(HTTPStatus.BAD_REQUEST, "deviceId query parameter is required")
                return
            start_iso = params.get("from", [None])[0]
            end_iso = params.get("to", [None])[0]
            data = _filter_routes(
                self.server.routes,  # type: ignore[attr-defined]
                device_id,
                start_iso,
                end_iso,
                current_track_time,
            )
            self._send_json(data)
            return

        self.send_error(HTTPStatus.NOT_FOUND, "Endpoint not implemented by stub")


class TraccarStubServer(ThreadingHTTPServer):
    def __init__(self, server_address, RequestHandlerClass, fixtures_dir: Path,
                 username: str, password: str,
                 playback_speed: float = 1.0,
                 loop_playback: bool = False,
                 start_offset: float = 0.0):
        super().__init__(server_address, RequestHandlerClass)
        self.fixtures_dir = fixtures_dir
        self.username = username
        self.password = password
        self.playback_speed = playback_speed if playback_speed > 0 else 1.0
        self.loop_playback = loop_playback
        self.start_offset = max(0.0, start_offset)
        self.playback_start_wall = datetime.now(timezone.utc)
        self.devices = _load_json(self.fixtures_dir / "devices.json", [])
        routes = _load_json(self.fixtures_dir / "routes.json", [])
        # Fallback: try routes.jsonl or routes.ndjson for large fixtures
        if not routes:
            jsonl_path = self.fixtures_dir / "routes.jsonl"
            ndjson_path = self.fixtures_dir / "routes.ndjson"
            for path in (jsonl_path, ndjson_path):
                if path.exists():
                    with path.open("r", encoding="utf-8") as handle:
                        routes = [json.loads(line) for line in handle if line.strip()]
                        break

        # Ensure every route entry has a deviceId; default to first device if missing
        default_device_id = None
        if self.devices:
            raw_first_id = self.devices[0].get("id")
            default_device_id = str(raw_first_id) if raw_first_id is not None else "1"

        normalized_routes = []
        for entry in routes:
            if not isinstance(entry, dict):
                continue
            device_id = entry.get("deviceId")
            if device_id is None and default_device_id is not None:
                entry["deviceId"] = default_device_id
            normalized_routes.append(entry)

        self.routes = normalized_routes
        self.static_latest_positions = _compute_latest(self.routes)

        if not self.devices:
            print(f"⚠ Warning: {self.fixtures_dir / 'devices.json'} is empty or missing.")
        if not self.routes:
            print(f"⚠ Warning: {self.fixtures_dir / 'routes.json'} is empty or missing.")

        self.route_start_dt = _parse_iso(self.routes[0].get("fixTime")) if self.routes else None
        self.route_end_dt = _parse_iso(self.routes[-1].get("fixTime")) if self.routes else None
        if self.route_start_dt and self.route_end_dt:
            self.route_duration = max(0.0, (self.route_end_dt - self.route_start_dt).total_seconds())
            if not self.loop_playback and self.route_duration <= 0:
                self.route_duration = 0.0
            if self.route_duration > 0 and self.start_offset > self.route_duration:
                if self.loop_playback:
                    self.start_offset = self.start_offset % self.route_duration
                else:
                    self.start_offset = self.route_duration
        else:
            self.route_duration = 0.0

    def current_track_time(self) -> Optional[datetime]:
        if not self.route_start_dt:
            return None

        now = datetime.now(timezone.utc)
        elapsed_wall = max(0.0, (now - self.playback_start_wall).total_seconds())
        offset = self.start_offset + elapsed_wall * self.playback_speed

        if self.route_duration > 0:
            if self.loop_playback:
                offset = offset % self.route_duration
            else:
                offset = min(offset, self.route_duration)
        else:
            offset = 0.0

        return self.route_start_dt + timedelta(seconds=offset)

    def latest_positions_snapshot(self, current_time: Optional[datetime]) -> List[Dict[str, Any]]:
        if not current_time:
            return list(self.static_latest_positions.values())

        latest: Dict[str, Dict[str, Any]] = {}
        for entry in self.routes:
            ts = _parse_iso(entry.get("fixTime"))
            if not ts or ts > current_time:
                continue
            device_id = str(entry.get("deviceId"))
            if not device_id:
                continue
            existing = latest.get(device_id)
            if not existing:
                latest[device_id] = entry
            else:
                existing_ts = _parse_iso(existing.get("fixTime"))
                if existing_ts is None or ts > existing_ts:
                    latest[device_id] = entry

        if not latest:
            return []

        return list(latest.values())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a local Traccar HTTP mock server.")
    parser.add_argument("--host", default="127.0.0.1", help="Host/interface to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8082, help="Port to bind (default: 8082)")
    parser.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES_DIR,
                        help="Directory containing devices.json and routes.json fixtures")
    parser.add_argument("--username", default=os.environ.get("SARTRACKER_STUB_USER", "DC"),
                        help="HTTP Basic auth username (default: DC)")
    parser.add_argument("--password", default=os.environ.get("SARTRACKER_STUB_PASS", "Superb"),
                        help="HTTP Basic auth password (default: Superb)")
    parser.add_argument("--playback-speed", type=float,
                        default=float(os.environ.get("SARTRACKER_STUB_SPEED", "30.0")),
                        help="Playback speed multiplier (1.0 = real time, default: 30x)")
    parser.add_argument("--loop", action="store_true", help="Loop back to start after reaching the end")
    parser.add_argument("--start-offset", type=float, default=0.0,
                        help="Start playback this many seconds into the track")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    fixtures_dir = args.fixtures.expanduser().resolve()
    if not fixtures_dir.exists():
        raise SystemExit(f"Fixture directory not found: {fixtures_dir}")

    server = TraccarStubServer(
        (args.host, args.port),
        TraccarStubHandler,
        fixtures_dir=fixtures_dir,
        username=args.username,
        password=args.password,
        playback_speed=args.playback_speed,
        loop_playback=args.loop,
        start_offset=args.start_offset,
    )

    print("=============================================")
    print(" Traccar HTTP Mock Server (development only) ")
    print("=============================================")
    print(f"Listening on http://{args.host}:{args.port}")
    print(f"Using fixtures from: {fixtures_dir}")
    print(f"Devices served: {len(server.devices)} | Route points: {len(server.routes)}")
    if server.route_start_dt and server.route_end_dt:
        print(f"Route time span: {server.route_start_dt.isoformat()} -> {server.route_end_dt.isoformat()}")
    if args.playback_speed != 1.0:
        print(f"Playback speed: {args.playback_speed}x")
    if args.loop:
        print("Looping enabled")
    print(f"Auth credentials -> username: {args.username!r}  password: {args.password!r}")
    print("Press Ctrl+C to stop.\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down mock server...")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

