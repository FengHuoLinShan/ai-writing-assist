"""所有可用 Loader 注册"""

from modules.context.services.loaders.characters_loader import CharactersLoader
from modules.context.services.loaders.events_loader import EventsLoader
from modules.context.services.loaders.memory_records_loader import MemoryRecordsLoader
from modules.context.services.loaders.outline_arc_loader import OutlineArcLoader
from modules.context.services.loaders.plot_threads_loader import PlotThreadsLoader
from modules.context.services.loaders.project_loader import ProjectLoader
from modules.context.services.loaders.rag_chunks_loader import RagChunksLoader
from modules.context.services.loaders.scene_loader import SceneLoader
from modules.context.services.loaders.world_bible_loader import WorldBibleLoader
from modules.context.services.loaders.world_entities_loader import WorldEntitiesLoader

_AVAILABLE_LOADERS: dict[str, bool] = {
    "project": True,
    "world_entities": True,
    "world_bible": True,
    "characters": True,
    "memory_records": True,
    "events": True,
    "rag_chunks": True,
    "plot_threads": True,
    "outline_arc": True,
    "scene": True,
}


def is_loader_available(name: str) -> bool:
    return _AVAILABLE_LOADERS.get(name, False)


__all__ = [
    "PlotThreadsLoader",
    "OutlineArcLoader",
    "ProjectLoader",
    "WorldEntitiesLoader",
    "WorldBibleLoader",
    "CharactersLoader",
    "EventsLoader",
    "RagChunksLoader",
    "MemoryRecordsLoader",
    "SceneLoader",
    "is_loader_available",
]
