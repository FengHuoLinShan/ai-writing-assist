"""所有 Loader 自动注册"""

from modules.context.services.loaders.chapter_card_loader import ChapterCardLoader
from modules.context.services.loaders.characters_loader import CharactersLoader
from modules.context.services.loaders.geo_filter import GeoReachabilityFilter
from modules.context.services.loaders.geo_locations_loader import GeoLocationsLoader
from modules.context.services.loaders.memory_records_loader import MemoryRecordsLoader
from modules.context.services.loaders.outline_arc_loader import OutlineArcLoader
from modules.context.services.loaders.plot_threads_loader import PlotThreadsLoader
from modules.context.services.loaders.project_loader import ProjectLoader
from modules.context.services.loaders.rag_chunks_loader import RagChunksLoader
from modules.context.services.loaders.events_loader import EventsLoader
from modules.context.services.loaders.world_entities_loader import WorldEntitiesLoader

__all__ = [
    "ProjectLoader",
    "WorldEntitiesLoader",
    "CharactersLoader",
    "GeoLocationsLoader",
    "MemoryRecordsLoader",
    "EventsLoader",
    "PlotThreadsLoader",
    "OutlineArcLoader",
    "ChapterCardLoader",
    "RagChunksLoader",
    "GeoReachabilityFilter",
]
