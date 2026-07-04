"""RevealPlan Repository"""

from __future__ import annotations

from modules.outline.models import RevealPlan
from modules.outline.repositories import StructurePlanRepository


class RevealPlanRepository(StructurePlanRepository[RevealPlan]):
    model_class = RevealPlan
    order_by = (RevealPlan.created_at,)
