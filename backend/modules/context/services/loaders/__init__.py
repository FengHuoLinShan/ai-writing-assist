"""所有可用 Loader 注册"""

from modules.context.services.loaders.outline_arc_loader import OutlineArcLoader
from modules.context.services.loaders.plot_threads_loader import PlotThreadsLoader
from modules.context.services.loaders.project_loader import ProjectLoader
from modules.context.services.loaders.world_entities_loader import WorldEntitiesLoader
from modules.context.services.loaders.characters_loader import CharactersLoader
from modules.context.services.loaders.events_loader import EventsLoader
from modules.context.services.loaders.rag_chunks_loader import RagChunksLoader
from modules.context.services.loaders.memory_records_loader import MemoryRecordsLoader

_AVAILABLE_LOADERS: dict[str, bool] = {
    "project": True,
    "world_entities": True,
    "characters": True,
    "memory_records": True,
    "events": True,
    "rag_chunks": True,
    "plot_threads": True,
    "outline_arc": True,
}


def is_loader_available(name: str) -> bool:
    return _AVAILABLE_LOADERS.get(name, False)


__all__ = [
    "PlotThreadsLoader",
    "OutlineArcLoader",
    "ProjectLoader",
    "WorldEntitiesLoader",
    "CharactersLoader",
    "EventsLoader",
    "RagChunksLoader",
    "MemoryRecordsLoader",
    "is_loader_available",
]
