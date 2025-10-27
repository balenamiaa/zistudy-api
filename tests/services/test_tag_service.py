from __future__ import annotations

import pytest

from zistudy_api.db.models import StudySet, StudySetTag
from zistudy_api.services.tags import TagService

pytestmark = pytest.mark.asyncio


async def test_tag_service_crud_and_popular(session_maker) -> None:
    async with session_maker() as session:
        service = TagService(session)

        ensured = await service.ensure_tags([" cardio ", "neuro"], commit=True)
        assert [tag.name for tag in ensured] == ["cardio", "neuro"]

        listed = await service.list_tags()
        assert {tag.name for tag in listed} == {"cardio", "neuro"}

        total, results = await service.search_tags("car")
        assert total == 1
        assert results[0].name == "cardio"

        cardio = ensured[0]
        study_set = StudySet(title="Emergency", description="Protocols", is_private=False)
        session.add(study_set)
        await session.flush()
        session.add(StudySetTag(study_set_id=study_set.id, tag_id=cardio.id))
        await session.commit()

        popular = await service.popular_tags(limit=5)
        assert popular[0].tag.name == "cardio"
        assert popular[0].usage_count == 1
