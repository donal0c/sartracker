# -*- coding: utf-8 -*-
"""
Lost Person Behavior Statistics Module

Statistical data for search planning based on subject categories.
Data sources: "Lost Person Behavior" by Robert Koester, NASAR guidelines.

This module provides distance statistics for different lost person categories,
used to generate probability-based search areas and range rings.
"""


class LPBStatistics:
    """Lost Person Behavior statistical data for search planning."""

    # Statistical distances in meters
    # Format: {category: {percentile: distance_in_meters}}
    STATISTICS = {
        'child_1_3': {
            'name': 'Child (1-3 years)',
            25: 100,    # 25% found within 100m
            50: 300,    # 50% found within 300m
            75: 700,    # 75% found within 700m
            95: 1900,   # 95% found within 1.9km
        },
        'child_4_6': {
            'name': 'Child (4-6 years)',
            25: 200,
            50: 500,
            75: 1100,
            95: 2400,
        },
        'child_7_12': {
            'name': 'Child (7-12 years)',
            25: 500,
            50: 1300,
            75: 2500,
            95: 3800,
        },
        'hiker': {
            'name': 'Hiker',
            25: 800,
            50: 2000,
            75: 4000,
            95: 8000,
        },
        'hunter': {
            'name': 'Hunter',
            25: 1200,
            50: 3000,
            75: 5500,
            95: 10000,
        },
        'elderly': {
            'name': 'Elderly',
            25: 200,
            50: 500,
            75: 1200,
            95: 2500,
        },
        'dementia': {
            'name': 'Dementia Patient',
            25: 100,
            50: 300,
            75: 800,
            95: 2000,
        },
        'despondent': {
            'name': 'Despondent',
            25: 200,
            50: 500,
            75: 1500,
            95: 3000,
        },
        'autistic': {
            'name': 'Autistic',
            25: 200,
            50: 600,
            75: 1200,
            95: 2000,
        },
    }

    @classmethod
    def get_distances(cls, category_key, percentiles=None):
        """
        Get distances for a subject category.

        Args:
            category_key: String key (e.g., 'child_1_3', 'hiker')
            percentiles: List of percentiles to retrieve (default: [25, 50, 75, 95])

        Returns:
            Dict mapping percentile to distance in meters, or None if category invalid
        """
        if percentiles is None:
            percentiles = [25, 50, 75, 95]

        if category_key not in cls.STATISTICS:
            return None

        stats = cls.STATISTICS[category_key]
        return {p: stats[p] for p in percentiles if p in stats}

    @classmethod
    def get_category_from_display_name(cls, display_name):
        """
        Convert display name to category key.

        Args:
            display_name: Display name (e.g., "Child (1-3 years)")

        Returns:
            Category key (e.g., 'child_1_3') or None if not found
        """
        for key, data in cls.STATISTICS.items():
            if data['name'] == display_name:
                return key
        return None

    @classmethod
    def get_all_categories(cls):
        """
        Get list of all category display names.

        Returns:
            List of display names (e.g., ["Child (1-3 years)", "Hiker", ...])
        """
        return [data['name'] for data in cls.STATISTICS.values()]

    @classmethod
    def get_category_info(cls, category_key):
        """
        Get complete information for a category.

        Args:
            category_key: String key (e.g., 'child_1_3')

        Returns:
            Dict with 'name' and percentile distances, or None if invalid
        """
        return cls.STATISTICS.get(category_key)
