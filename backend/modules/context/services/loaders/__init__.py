"""所有可用 Loader 注册 — minimal-core 仅导入仍存在的模块 loader"""

from modules.context.services.loaders.project_loader import ProjectLoader
from modules.context.services.loaders.world_entities_loader import WorldEntitiesLoader
from modules.context.services.loaders.characters_loader import CharactersLoader
from modules.context.services.loaders.events_loader import EventsLoader
from modules.context.services.loaders.rag_chunks_loader import RagChunksLoader

# geo/memory/outline 模块暂时切分，对应 loader 不可用
# GeoLocationsLoader, MemoryRecordsLoader, PlotThreadsLoader,
# OutlineArcLoader, ChapterCardLoader, GeoReachabilityFilter

_AVAILABLE_LOADERS: dict[str, bool] = {
    "project": True,
    "world_entities": True,
    "characters": True,
    "geo_locations": False,
    "memory_records": False,
    "events": True,
    "plot_threads": False,
    "outline_arc": False,
    "chapter_card": False,
    "rag_chunks": True,
}


def is_loader_available(name: str) -> bool:
    return _AVAILABLE_LOADERS.get(name, False)


__all__ = [
    "ProjectLoader",
    "WorldEntitiesLoader",
    "CharactersLoader",
    "EventsLoader",
    "RagChunksLoader",
    "is_loader_available",
]
