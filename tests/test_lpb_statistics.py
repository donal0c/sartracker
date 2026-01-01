# -*- coding: utf-8 -*-
"""
Tests for Lost Person Behavior Statistics Module.

These tests verify the ACTUAL utils/lpb_statistics.py production code that
provides search planning statistics. Getting these wrong affects SAR
decision-making about search area sizes.

Value: Tests SAR domain logic that directly impacts search planning.
"""

import pytest
from utils.lpb_statistics import LPBStatistics


class TestGetDistances:
    """Tests for distance retrieval by category and percentile."""

    def test_valid_category_returns_all_percentiles(self):
        """Verify hiker category returns expected default percentiles."""
        result = LPBStatistics.get_distances('hiker')

        assert result is not None
        assert 25 in result
        assert 50 in result
        assert 75 in result
        assert 95 in result

    def test_hiker_distances_are_correct(self):
        """Verify hiker statistics match Koester data - critical for search area sizing."""
        result = LPBStatistics.get_distances('hiker')

        # These values directly affect search ring generation
        assert result[25] == 800    # 25% found within 800m
        assert result[50] == 2000   # 50% found within 2km
        assert result[75] == 4000   # 75% found within 4km
        assert result[95] == 8000   # 95% found within 8km

    def test_child_1_3_has_smaller_distances(self):
        """Verify young child statistics are smaller - affects search prioritization."""
        child = LPBStatistics.get_distances('child_1_3')
        hiker = LPBStatistics.get_distances('hiker')

        # Young children don't travel as far - search area should be smaller
        assert child[95] < hiker[95]
        assert child[50] < hiker[50]

    def test_subset_percentiles_returns_only_requested(self):
        """Verify selective percentile retrieval works."""
        result = LPBStatistics.get_distances('hiker', percentiles=[25, 75])

        assert len(result) == 2
        assert 25 in result
        assert 75 in result
        assert 50 not in result

    def test_invalid_category_returns_none(self):
        """Invalid category must return None, not raise or return empty."""
        result = LPBStatistics.get_distances('invalid_category')
        assert result is None

    def test_invalid_percentile_skipped(self):
        """Invalid percentile in list is silently skipped."""
        result = LPBStatistics.get_distances('hiker', percentiles=[25, 99, 50])

        # 99 percentile doesn't exist, should only get 25 and 50
        assert 25 in result
        assert 50 in result
        assert 99 not in result
        assert len(result) == 2


class TestCategoryLookup:
    """Tests for category display name to key conversion."""

    def test_display_name_to_key_succeeds(self):
        """Verify display name lookup returns correct key."""
        result = LPBStatistics.get_category_from_display_name('Hiker')
        assert result == 'hiker'

    def test_display_name_exact_match_required(self):
        """Display name must match exactly - no fuzzy matching."""
        # Missing parentheses
        result = LPBStatistics.get_category_from_display_name('Child 1-3 years')
        assert result is None

    def test_unknown_display_name_returns_none(self):
        """Unknown display name returns None, not raises."""
        result = LPBStatistics.get_category_from_display_name('Unknown Category')
        assert result is None


class TestGetAllCategories:
    """Tests for category list retrieval."""

    def test_returns_all_expected_categories(self):
        """Verify all SAR subject categories are available."""
        categories = LPBStatistics.get_all_categories()

        # Core categories that must be present for SAR operations
        assert 'Hiker' in categories
        assert 'Dementia Patient' in categories
        assert 'Child (1-3 years)' in categories

    def test_returns_display_names_not_keys(self):
        """Category list should be human-readable display names."""
        categories = LPBStatistics.get_all_categories()

        # Should be display names, not internal keys
        assert 'hiker' not in categories  # key
        assert 'Hiker' in categories       # display name


class TestGetCategoryInfo:
    """Tests for complete category information retrieval."""

    def test_valid_category_returns_complete_info(self):
        """Valid category returns all data including name."""
        info = LPBStatistics.get_category_info('dementia')

        assert info is not None
        assert 'name' in info
        assert info['name'] == 'Dementia Patient'
        assert 25 in info
        assert 95 in info

    def test_invalid_category_returns_none(self):
        """Invalid category returns None."""
        info = LPBStatistics.get_category_info('not_a_category')
        assert info is None


class TestDataIntegrity:
    """Tests for overall data integrity - catch data entry errors."""

    def test_all_categories_have_required_percentiles(self):
        """Every category must have the standard percentiles."""
        required_percentiles = [25, 50, 75, 95]

        for key in ['child_1_3', 'child_4_6', 'child_7_12', 'hiker',
                    'hunter', 'elderly', 'dementia', 'despondent', 'autistic']:
            info = LPBStatistics.get_category_info(key)
            assert info is not None, f"Category {key} not found"

            for p in required_percentiles:
                assert p in info, f"Category {key} missing percentile {p}"

    def test_distances_are_monotonically_increasing(self):
        """Higher percentiles must have larger distances."""
        for key in ['hiker', 'dementia', 'child_1_3']:
            info = LPBStatistics.get_category_info(key)

            assert info[25] <= info[50], f"{key}: 25th > 50th percentile"
            assert info[50] <= info[75], f"{key}: 50th > 75th percentile"
            assert info[75] <= info[95], f"{key}: 75th > 95th percentile"

    def test_roundtrip_display_name_to_key(self):
        """Display name → key → info → display name roundtrip works."""
        display_name = 'Dementia Patient'

        key = LPBStatistics.get_category_from_display_name(display_name)
        info = LPBStatistics.get_category_info(key)

        assert info['name'] == display_name
