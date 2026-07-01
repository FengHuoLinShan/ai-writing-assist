"""Compatibility exports for world map services.

The concrete implementations live in focused internal modules.  Keep importing
from this module for existing API routes and tests that depend on the historic
`modules.world.services.map_service` path.
"""

from __future__ import annotations

from modules.world.services.map_config_service import MapConfigService
from modules.world.services.map_dynamic_service import MapDynamicFactService
from modules.world.services.map_location_binding_service import MapLocationBindingService
from modules.world.services.map_marker_service import MapMarkerService
from modules.world.services.map_templates import (
    _generate_blank_tiles,
    _generate_continent_tiles,
    _generate_islands_tiles,
    generate_detail_tiles,
    generate_template_tiles,
)
from modules.world.services.map_territory_service import MapTerritoryService
from modules.world.services.map_tile_service import MapTileService

__all__ = [
    "MapConfigService",
    "MapTileService",
    "MapLocationBindingService",
    "MapMarkerService",
    "MapTerritoryService",
    "MapDynamicFactService",
    "generate_template_tiles",
    "generate_detail_tiles",
    "_generate_blank_tiles",
    "_generate_continent_tiles",
    "_generate_islands_tiles",
]
