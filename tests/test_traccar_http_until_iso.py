# -*- coding: utf-8 -*-
"""Unit tests for TraccarHttpProvider until_iso handling."""
import pytest
from unittest.mock import Mock, patch

from sartracker.providers.traccar_http import TraccarHttpProvider
from sartracker.utils.exceptions import ProviderDataError
from sartracker.utils.timeparse import parse_iso


@pytest.fixture
def provider():
    return TraccarHttpProvider(
        base_url="http://test.example.com:8082",
        auth_type="basic",
        username="testuser",
        password="testpass",
        enable_bulk_breadcrumbs=False
    )


def test_until_iso_sets_to_param(provider):
    calls = []

    def capture_calls(endpoint, session=None, params=None, expect_json=True):
        if params and 'deviceId' in params:
            calls.append(params)
        return []

    device_map = {'1': 'Alpha', '2': 'Bravo'}
    until_iso = '2026-01-04T12:00:00Z'

    with patch.object(provider, '_load_devices', return_value=device_map):
        with patch.object(provider.http_client, 'get', side_effect=capture_calls):
            provider.get_breadcrumbs(
                since_iso='2026-01-04T08:00:00Z',
                until_iso=until_iso,
                session=Mock()
            )

    assert len(calls) == 2
    until_dt = parse_iso(until_iso)
    for params in calls:
        assert parse_iso(params['to']) == until_dt


def test_until_iso_before_since_raises(provider):
    with patch.object(provider, '_load_devices', return_value={}):
        with pytest.raises(ProviderDataError):
            provider.get_breadcrumbs(
                since_iso='2026-01-04T10:00:00Z',
                until_iso='2026-01-04T09:00:00Z',
                session=Mock()
            )
