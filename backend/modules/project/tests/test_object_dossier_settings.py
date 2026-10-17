from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from core.errors import ConflictError
from modules.project.object_dossier_settings import (
    ObjectDossierSettingsUpdate,
    read_object_dossier_settings,
    update_object_dossier_settings,
)


class _ProjectSettingsSession:
    def __init__(self, project: SimpleNamespace) -> None:
        self.project = project
        self.flushed = False

    async def scalar(self, _statement):
        return self.project

    async def flush(self) -> None:
        self.flushed = True


@pytest.mark.asyncio
async def test_object_validity_settings_default_off_and_preserve_other_project_settings():
    project_id = "6ca534b9-0a11-46f9-ae43-efb78bf021fb"
    project = SimpleNamespace(id=project_id, settings={"keep": {"value": 1}})
    db = _ProjectSettingsSession(project)

    with patch(
        "modules.project.object_dossier_settings.ProjectService.get_project",
        autospec=True,
    ) as get_project:
        read = await read_object_dossier_settings(db, project_id)
        assert read == {"version": 0, "allow_story_override": False}

        updated = await update_object_dossier_settings(
            db,
            project_id,
            ObjectDossierSettingsUpdate(
                expected_version=0,
                allow_story_override=True,
            ),
        )

    assert updated == {"version": 1, "allow_story_override": True}
    assert project.settings == {
        "keep": {"value": 1},
        "world_object_dossier_v1": updated,
    }
    assert db.flushed is True
    assert get_project.await_count == 2


@pytest.mark.asyncio
async def test_object_validity_settings_reject_stale_version_without_mutating():
    project_id = "6ca534b9-0a11-46f9-ae43-efb78bf021fb"
    saved = {"version": 3, "allow_story_override": True}
    project = SimpleNamespace(settings={"world_object_dossier_v1": saved})
    db = _ProjectSettingsSession(project)

    with patch(
        "modules.project.object_dossier_settings.ProjectService.get_project",
        autospec=True,
    ):
        with pytest.raises(ConflictError):
            await update_object_dossier_settings(
                db,
                project_id,
                ObjectDossierSettingsUpdate(
                    expected_version=2,
                    allow_story_override=False,
                ),
            )

    assert project.settings == {"world_object_dossier_v1": saved}
    assert db.flushed is False
