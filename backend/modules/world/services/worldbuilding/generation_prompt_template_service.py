"""Generation Center prompt template persistence and validation."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import NotFoundError, ValidationError
from infrastructure.llm.token_estimation import estimate_token_count
from modules.world.models import (
    GenerationPromptTemplate,
    GenerationPromptTemplateRevision,
)
from modules.world.schemas import (
    GenerationPromptTemplateCreate,
    GenerationPromptTemplateListResponse,
    GenerationPromptTemplateResponse,
    GenerationPromptTemplateRevisionResponse,
    GenerationPromptTemplateUpdate,
    ObjectDraftTemplate,
    PromptTemplateCopyRequest,
    PromptTemplateIssue,
    PromptTemplatePreviewRequest,
    PromptTemplatePreviewResponse,
    PromptTemplateValidateRequest,
    PromptTemplateValidateResponse,
    PromptTemplateVariable,
)
from modules.world.services.common import parse_uuid

TARGET_KIND = "world_object"
SUPPORTED_OBJECT_TEMPLATES = {
    "none",
    "character",
    "event",
    "item",
    "location",
    "faction",
    "rule",
    "custom",
}
TEMPLATE_ENTITY_TYPES = {
    "none": "concept",
    "character": "character",
    "event": "event",
    "item": "item",
    "location": "location",
    "faction": "faction",
    "rule": "rule",
    "custom": "concept",
}

_PLACEHOLDER_RE = re.compile(r"{{\s*([A-Za-z_][A-Za-z0-9_]*)\s*}}")
_ANY_PLACEHOLDER_RE = re.compile(r"{{(.*?)}}")
_VARIABLE_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

BUILTIN_GENERATION_TEMPLATES: dict[str, dict[str, Any]] = {
    "none": {
        "name": "不带模板",
        "description": "自由构思，先作为概念建议收束，采用前可调整类型。",
        "object_template": "none",
        "prompt_text": (
            "不预设固定创作框架。围绕作者真正想创造或解决的内容，"
            "找出这个对象最核心的概念、辨识度，以及它与现有世界和故事的关系。"
            "允许对象暂时跨越多个类别或尚未完成分类，不要套用人物、事件、"
            "物品等模板的固定维度。最终先收束为概念建议，作者可在采用前调整类型。"
        ),
        "variables_json": [],
    },
    "character": {
        "name": "人物",
        "description": "具有欲望、选择与关系的人物。",
        "object_template": "character",
        "prompt_text": (
            "把人物设计成一个会作出选择、影响他人并改变局势的人，而不是属性集合。"
            "优先理解这个人物在当前故事中追求什么、受到什么阻力、如何作出选择，"
            "以及其行为逻辑和重要关系。外貌、能力、恐惧、秘密、声音风格、过去经历等，"
            "只发展对当前人物真正有帮助的部分。不要强制人物拥有悲惨过去、隐藏身份、"
            "反转或完整人物卡，也不要用性格标签代替具体的行为逻辑。"
        ),
        "variables_json": [],
    },
    "event": {
        "name": "事件",
        "description": "改变局势或维持秩序的发生过程。",
        "object_template": "event",
        "prompt_text": (
            "把事件设计成一次具有因果关系的状态变化，而不是静态事件说明。"
            "优先理解事件发生前后的差异、推动变化的力量、参与者作出的关键选择，"
            "以及它对相关人物和世界产生的实际影响。起因、过程、结果、公开解释、"
            "隐藏原因和后续影响只按当前事件需要发展。事件可以失败、中断、持续发酵或仅仅巩固现状；"
            "不要强制加入阴谋、隐藏真相、反转或后续钩子。"
        ),
        "variables_json": [],
    },
    "item": {
        "name": "物品",
        "description": "被使用、争夺、保存或传承的物品。",
        "object_template": "item",
        "prompt_text": (
            "把物品设计成会被使用、保存、争夺、交换或传承的世界组成部分。"
            "优先理解人们为什么在意它、它能够或不能做什么、使用和持有它会带来什么，"
            "以及它与人物、地点、组织或历史的关系。外观、来源、能力、限制、代价、"
            "秘密和风险只按当前物品需要发展。不要默认物品具有超自然能力、诅咒、秘密来源或失控风险。"
        ),
        "variables_json": [],
    },
    "location": {
        "name": "地点",
        "description": "承载行动与生活的空间。",
        "object_template": "location",
        "prompt_text": (
            "把地点设计成会塑造行动、生活和关系的空间，而不是景观资料表。"
            "优先理解空间如何组织、人在其中如何行动和感受、谁能够进入或控制它，"
            "以及它为什么在当前世界中存在。历史、资源、危险、势力归属、"
            "秘密区域和进入条件只按当前地点需要发展。不要强制每个地点都有危险、秘密区域、"
            "特殊资源或剧情任务。"
        ),
        "variables_json": [],
    },
    "faction": {
        "name": "组织",
        "description": "能够持续行动与决策的集体。",
        "object_template": "faction",
        "prompt_text": (
            "把组织设计成能够持续作出决策和采取行动的集体，而不是组织架构图。"
            "优先理解它为什么存在、如何获得资源和合法性、谁能够影响决策、"
            "内部如何合作或分裂，以及它实际能够做什么、不能做什么。"
            "成员、层级、公开形象、隐藏目标和外部关系只按当前组织需要发展。"
            "不要强制组织拥有秘密目标、宿敌、阴谋或完整层级体系。"
        ),
        "variables_json": [],
    },
    "rule": {
        "name": "规则设定",
        "description": "约束世界运行与选择后果的机制。",
        "object_template": "rule",
        "prompt_text": (
            "把规则设计成稳定影响世界运行、人物选择和行为后果的机制，"
            "而不是术语密集的说明书。优先理解它约束什么、角色如何认识或验证它、"
            "违反或利用它会发生什么，以及它如何改变真实的选择空间。"
            "适用范围、限制、代价、边界情况、例外和普遍误解只按当前规则需要发展。"
            "不要为了制造戏剧性而强行增加漏洞、例外、代价或伪科学解释；"
            "规则应当足够一致，但不要求解释超出故事实际需要的细节。"
        ),
        "variables_json": [],
    },
}


class TemplateVersionConflictError(Exception):
    def __init__(self, *, expected: int, actual: int) -> None:
        self.expected = expected
        self.actual = actual
        super().__init__("template_version_conflict")


@dataclass(frozen=True)
class ResolvedGenerationTemplate:
    template_id: str | None
    template_version: int | None
    template_hash: str | None
    validation_state: str
    validation_issues: list[PromptTemplateIssue]
    object_template: str
    label: str
    prompt_text: str
    rendered_prompt: str
    is_builtin: bool


class GenerationPromptTemplateService:
    async def list(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        include_archived: bool = False,
        target_kind: str = TARGET_KIND,
    ) -> GenerationPromptTemplateListResponse:
        nid = parse_uuid(novel_id, "novel_id")
        items = [self._builtin_response(key, novel_id) for key in _builtin_keys()]
        conditions = [
            GenerationPromptTemplate.novel_id == nid,
            GenerationPromptTemplate.target_kind == target_kind,
        ]
        if not include_archived:
            conditions.append(GenerationPromptTemplate.status != "archived")
        result = await db.execute(
            select(GenerationPromptTemplate)
            .where(*conditions)
            .order_by(GenerationPromptTemplate.updated_at.desc())
        )
        items.extend(self._response(row) for row in result.scalars().all())
        return GenerationPromptTemplateListResponse(items=items, total=len(items))

    async def get(
        self,
        db: AsyncSession,
        novel_id: str,
        template_id: str,
    ) -> GenerationPromptTemplateResponse:
        if _is_builtin_id(template_id):
            return self._builtin_response(_builtin_key_from_id(template_id), novel_id)
        row = await self._get_row(db, novel_id, template_id)
        return self._response(row)

    async def create(
        self,
        db: AsyncSession,
        data: GenerationPromptTemplateCreate,
    ) -> GenerationPromptTemplateResponse:
        nid = parse_uuid(data.novel_id, "novel_id")
        prompt_text = data.prompt_text.strip()
        variables = [item.model_dump() for item in data.variables_json]
        issues = validate_template(
            prompt_text=prompt_text,
            object_template=data.object_template,
            variables_json=variables,
        )
        state = validation_state(issues)
        row = GenerationPromptTemplate(
            novel_id=nid,
            target_kind=data.target_kind,
            template_key=f"custom-{uuid.uuid4().hex[:12]}",
            name=data.name.strip(),
            description=(data.description or "").strip() or None,
            object_template=data.object_template,
            prompt_text=prompt_text,
            variables_json=variables,
            validation_state=state,
            validation_issues_json=[issue.model_dump() for issue in issues],
            version_number=1,
            content_hash=template_content_hash(prompt_text, variables),
            status="active",
            created_by=data.created_by,
            updated_by=data.created_by,
        )
        db.add(row)
        await db.flush()
        await self._add_revision(db, row, reason="created")
        await db.flush()
        return self._response(row)

    async def update(
        self,
        db: AsyncSession,
        novel_id: str,
        template_id: str,
        data: GenerationPromptTemplateUpdate,
    ) -> GenerationPromptTemplateResponse:
        if _is_builtin_id(template_id):
            raise ValidationError("built-in templates are read-only; copy first")
        row = await self._get_row(db, novel_id, template_id)
        if (
            data.template_version is not None
            and data.template_version != row.version_number
        ):
            raise TemplateVersionConflictError(
                expected=data.template_version,
                actual=row.version_number,
            )
        if data.name is not None:
            row.name = data.name.strip()
        if data.description is not None:
            row.description = data.description.strip() or None
        if data.object_template is not None:
            row.object_template = data.object_template
        if data.prompt_text is not None:
            row.prompt_text = data.prompt_text.strip()
        if data.variables_json is not None:
            row.variables_json = [item.model_dump() for item in data.variables_json]
        if data.status is not None:
            row.status = data.status
        row.updated_by = data.updated_by
        row.version_number += 1
        issues = validate_template(
            prompt_text=row.prompt_text,
            object_template=row.object_template,
            variables_json=row.variables_json,
        )
        row.validation_state = validation_state(issues)
        row.validation_issues_json = [issue.model_dump() for issue in issues]
        row.content_hash = template_content_hash(row.prompt_text, row.variables_json)
        await self._add_revision(db, row, reason="updated")
        await db.flush()
        return self._response(row)

    async def archive(
        self,
        db: AsyncSession,
        novel_id: str,
        template_id: str,
    ) -> None:
        if _is_builtin_id(template_id):
            raise ValidationError("built-in templates cannot be archived")
        row = await self._get_row(db, novel_id, template_id)
        row.status = "archived"
        row.version_number += 1
        await self._add_revision(db, row, reason="archived")
        await db.flush()

    async def copy_builtin(
        self,
        db: AsyncSession,
        template_id: str,
        data: PromptTemplateCopyRequest,
    ) -> GenerationPromptTemplateResponse:
        if not _is_builtin_id(template_id):
            raise ValidationError("only built-in templates can be copied")
        builtin = self._builtin_response(_builtin_key_from_id(template_id), data.novel_id)
        return await self.create(
            db,
            GenerationPromptTemplateCreate(
                novel_id=data.novel_id,
                target_kind="world_object",
                name=data.name or builtin.name,
                description=builtin.description,
                object_template=builtin.object_template,
                prompt_text=builtin.prompt_text,
                variables_json=builtin.variables_json,
                created_by=data.created_by,
            ),
        )

    async def revisions(
        self,
        db: AsyncSession,
        novel_id: str,
        template_id: str,
    ) -> list[GenerationPromptTemplateRevisionResponse]:
        row = await self._get_row(db, novel_id, template_id)
        result = await db.execute(
            select(GenerationPromptTemplateRevision)
            .where(
                GenerationPromptTemplateRevision.novel_id == row.novel_id,
                GenerationPromptTemplateRevision.template_id == row.id,
            )
            .order_by(GenerationPromptTemplateRevision.version_number.desc())
        )
        return [self._revision_response(item) for item in result.scalars().all()]

    def validate(
        self,
        data: PromptTemplateValidateRequest,
    ) -> PromptTemplateValidateResponse:
        variables = [item.model_dump() for item in data.variables_json]
        issues = validate_template(
            prompt_text=data.prompt_text,
            object_template=data.object_template,
            variables_json=variables,
            template_variables=data.template_variables,
        )
        return PromptTemplateValidateResponse(
            validation_state=validation_state(issues),
            issues=issues,
            content_hash=template_content_hash(data.prompt_text, variables),
        )

    async def preview(
        self,
        db: AsyncSession,
        data: PromptTemplatePreviewRequest,
    ) -> PromptTemplatePreviewResponse:
        if data.template_id:
            response = await self.get(db, data.novel_id, data.template_id)
            if (
                data.template_version is not None
                and data.template_version != response.version_number
            ):
                raise TemplateVersionConflictError(
                    expected=data.template_version,
                    actual=response.version_number,
                )
            prompt_text = response.prompt_text
            variables = [item.model_dump() for item in response.variables_json]
            issues = validate_template(
                prompt_text=prompt_text,
                object_template=response.object_template,
                variables_json=variables,
                template_variables=data.template_variables,
            )
            rendered = render_template(
                prompt_text,
                variables,
                data.template_variables,
                value_limit=240,
            )
            content_hash = response.content_hash
            version = response.version_number
        else:
            prompt_text = (data.prompt_text or "").strip()
            variables = [item.model_dump() for item in data.variables_json]
            issues = validate_template(
                prompt_text=prompt_text,
                object_template=data.object_template,
                variables_json=variables,
                template_variables=data.template_variables,
            )
            rendered = render_template(
                prompt_text,
                variables,
                data.template_variables,
                value_limit=240,
            )
            content_hash = template_content_hash(prompt_text, variables)
            version = None
        return PromptTemplatePreviewResponse(
            rendered_template=rendered[:4000],
            rendered_template_summary=_summary(rendered),
            missing_variables=missing_required_variables(
                variables,
                data.template_variables,
            ),
            token_estimate=estimate_token_count(rendered),
            validation_state=validation_state(issues),
            issues=issues,
            content_hash=content_hash,
            template_version=version,
        )

    async def resolve_for_generation(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        template_id: str | None,
        template_version: int | None,
        template_variables: dict[str, Any],
        object_template: ObjectDraftTemplate | None = None,
        template_name: str | None = None,
        template_prompt: str | None = None,
    ) -> ResolvedGenerationTemplate:
        if template_id:
            if _is_builtin_id(template_id):
                response = self._builtin_response(
                    _builtin_key_from_id(template_id),
                    novel_id,
                )
            else:
                response = self._response(await self._get_row(db, novel_id, template_id))
            if (
                template_version is not None
                and template_version != response.version_number
            ):
                raise TemplateVersionConflictError(
                    expected=template_version,
                    actual=response.version_number,
                )
            variables = [item.model_dump() for item in response.variables_json]
            rendered = render_template(
                response.prompt_text,
                variables,
                template_variables,
            )
            issues = validate_template(
                prompt_text=response.prompt_text,
                object_template=response.object_template,
                variables_json=variables,
                template_variables=template_variables,
            )
            _raise_if_blocking(issues)
            return ResolvedGenerationTemplate(
                template_id=response.id,
                template_version=response.version_number,
                template_hash=response.content_hash,
                validation_state=validation_state(issues),
                validation_issues=issues,
                object_template=response.object_template,
                label=response.name,
                prompt_text=response.prompt_text,
                rendered_prompt=rendered,
                is_builtin=response.is_builtin,
            )

        if object_template is None:
            raise ValidationError("object_template is required without template_id")
        label = (
            template_name.strip()[:80]
            if object_template == "custom" and template_name
            else template_label(object_template)
        )
        prompt = (
            template_prompt.strip()
            if template_prompt and template_prompt.strip()
            else default_template_prompt(object_template)
        )
        issues = validate_template(
            prompt_text=prompt,
            object_template=object_template,
            variables_json=[],
            template_variables={},
        )
        _raise_if_blocking(issues)
        return ResolvedGenerationTemplate(
            template_id=None,
            template_version=None,
            template_hash=None,
            validation_state=validation_state(issues),
            validation_issues=issues,
            object_template=object_template,
            label=label,
            prompt_text=prompt,
            rendered_prompt=prompt,
            is_builtin=False,
        )

    async def _get_row(
        self,
        db: AsyncSession,
        novel_id: str,
        template_id: str,
        *,
        include_archived: bool = False,
    ) -> GenerationPromptTemplate:
        tid = parse_uuid(template_id, "template_id")
        nid = parse_uuid(novel_id, "novel_id")
        conditions = [
            GenerationPromptTemplate.id == tid,
            GenerationPromptTemplate.novel_id == nid,
        ]
        if not include_archived:
            conditions.append(GenerationPromptTemplate.status != "archived")
        result = await db.execute(select(GenerationPromptTemplate).where(*conditions))
        row = result.scalar_one_or_none()
        if row is None:
            raise NotFoundError(f"Template {template_id} not found")
        return row

    async def _add_revision(
        self,
        db: AsyncSession,
        row: GenerationPromptTemplate,
        *,
        reason: str,
    ) -> None:
        db.add(
            GenerationPromptTemplateRevision(
                novel_id=row.novel_id,
                template_id=row.id,
                version_number=row.version_number,
                name=row.name,
                description=row.description,
                object_template=row.object_template,
                prompt_text=row.prompt_text,
                variables_json=row.variables_json,
                validation_state=row.validation_state,
                validation_issues_json=row.validation_issues_json,
                content_hash=row.content_hash,
                snapshot_meta_json={"reason": reason},
            )
        )

    def _builtin_response(
        self,
        key: str,
        novel_id: str | None,
    ) -> GenerationPromptTemplateResponse:
        if key not in BUILTIN_GENERATION_TEMPLATES:
            raise NotFoundError(f"Template builtin:{key} not found")
        raw = BUILTIN_GENERATION_TEMPLATES[key]
        variables = [
            PromptTemplateVariable.model_validate(item)
            for item in raw.get("variables_json", [])
        ]
        prompt_text = str(raw["prompt_text"])
        issues = validate_template(
            prompt_text=prompt_text,
            object_template=str(raw["object_template"]),
            variables_json=[item.model_dump() for item in variables],
        )
        return GenerationPromptTemplateResponse(
            id=f"builtin:{key}",
            novel_id=novel_id,
            target_kind=TARGET_KIND,
            template_key=f"builtin:{key}",
            name=str(raw["name"]),
            description=raw.get("description"),
            object_template=raw["object_template"],
            prompt_text=prompt_text,
            variables_json=variables,
            status="active",
            is_builtin=True,
            version_number=1,
            content_hash=template_content_hash(
                prompt_text,
                [item.model_dump() for item in variables],
            ),
            validation_state=validation_state(issues),
            validation_issues=issues,
        )

    @staticmethod
    def _response(row: GenerationPromptTemplate) -> GenerationPromptTemplateResponse:
        variables = [
            PromptTemplateVariable.model_validate(item)
            for item in (row.variables_json or [])
        ]
        issues = [
            PromptTemplateIssue.model_validate(item)
            for item in (row.validation_issues_json or [])
        ]
        return GenerationPromptTemplateResponse(
            id=str(row.id),
            novel_id=str(row.novel_id),
            target_kind=row.target_kind,
            template_key=row.template_key,
            name=row.name,
            description=row.description,
            object_template=row.object_template,
            prompt_text=row.prompt_text,
            variables_json=variables,
            status=row.status,
            is_builtin=False,
            version_number=row.version_number,
            content_hash=row.content_hash,
            validation_state=row.validation_state,
            validation_issues=issues,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    @staticmethod
    def _revision_response(
        row: GenerationPromptTemplateRevision,
    ) -> GenerationPromptTemplateRevisionResponse:
        return GenerationPromptTemplateRevisionResponse(
            id=str(row.id),
            template_id=str(row.template_id),
            novel_id=str(row.novel_id),
            version_number=row.version_number,
            name=row.name,
            description=row.description,
            object_template=row.object_template,
            prompt_text=row.prompt_text,
            variables_json=[
                PromptTemplateVariable.model_validate(item)
                for item in (row.variables_json or [])
            ],
            validation_state=row.validation_state,
            validation_issues=[
                PromptTemplateIssue.model_validate(item)
                for item in (row.validation_issues_json or [])
            ],
            content_hash=row.content_hash,
            created_at=row.created_at,
        )


def template_label(object_template: str) -> str:
    return {
        "none": "不带模板",
        "character": "人物",
        "event": "事件",
        "item": "物品",
        "location": "地点",
        "faction": "组织",
        "rule": "规则设定",
        "custom": "自定义模板",
    }.get(object_template, "自定义模板")


def default_template_prompt(object_template: str) -> str:
    raw = BUILTIN_GENERATION_TEMPLATES.get(object_template)
    if raw:
        return str(raw["prompt_text"])
    return "按用户提供的自定义提示词生成对象草稿。"


def template_content_hash(prompt_text: str, variables_json: list[dict[str, Any]]) -> str:
    payload = json.dumps(
        {
            "prompt_text": prompt_text,
            "variables_json": variables_json,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def validate_template(
    *,
    prompt_text: str,
    object_template: str,
    variables_json: list[dict[str, Any]],
    template_variables: dict[str, Any] | None = None,
) -> list[PromptTemplateIssue]:
    issues: list[PromptTemplateIssue] = []
    text = (prompt_text or "").strip()
    if len(text) < 12:
        issues.append(_issue("P1", "prompt.too_short", "模板提示词过短。", "prompt_text"))
    if len(text) > 8000:
        issues.append(
            _issue("P1", "prompt.too_long", "模板提示词超过 8000 字。", "prompt_text")
        )
    if object_template not in SUPPORTED_OBJECT_TEMPLATES:
        issues.append(
            _issue(
                "P1",
                "template.unsupported_type",
                "不支持的对象模板类型。",
                "object_template",
            )
        )

    declared = _declared_variables(variables_json, issues)
    placeholders = _placeholders(text, issues)
    for name in sorted(placeholders - set(declared)):
        issues.append(
            _issue("P1", "variable.unknown", "模板使用了未声明变量。", f"{{{{{name}}}}}")
        )

    values = template_variables or {}
    for name, variable in declared.items():
        if variable.get("required") and not _variable_value(name, variable, values):
            issues.append(
                _issue("P1", "variable.required_missing", "必填变量缺失。", name)
            )

    lower = text.lower()
    forbidden_fields = {
        "id": "不要让模板控制 id 字段。",
        "status": "不要让模板控制 status 字段。",
        "approved_by": "不要让模板控制 approved_by 字段。",
        "novel_id": "不要让模板控制 novel_id。",
    }
    for field, message in forbidden_fields.items():
        if re.search(rf"\b{re.escape(field)}\b", lower):
            issues.append(_issue("P1", "prompt.forbidden_field", message, "prompt_text"))

    unsafe_checks = [
        ("api key", "不要要求输出或泄露 API key。"),
        ("apikey", "不要要求输出或泄露 API key。"),
        ("secret key", "不要要求输出或泄露密钥。"),
        ("sql", "模板不得要求输出或执行 SQL。"),
        ("select *", "模板不得包含数据库读取指令。"),
        ("insert into", "模板不得包含数据库写入指令。"),
        ("update ", "模板不得包含数据库写入指令。"),
        ("drop table", "模板不得包含数据库破坏性指令。"),
        ("delete from", "模板不得包含数据库破坏性指令。"),
        ("db write", "模板不得要求直接写数据库。"),
        ("database write", "模板不得要求直接写数据库。"),
        ("tool_call", "模板不得要求调用工具。"),
        ("function_call", "模板不得要求调用工具。"),
        ("tools", "模板不得要求调用工具。"),
        ("callable", "模板不得要求执行 callable。"),
        ("shell", "模板不得要求执行 shell。"),
        ("bash", "模板不得要求执行 shell。"),
        ("python callable", "模板不得要求执行 callable。"),
        ("system prompt", "模板不得覆盖系统提示或 guardrails。"),
        ("guardrail", "模板不得覆盖系统提示或 guardrails。"),
        ("output schema", "模板不得覆盖结构化输出契约。"),
        ("json schema", "模板不得覆盖结构化输出契约。"),
        ("promote", "模板不得绕过草稿确认。"),
        ("canonicalize", "模板不得绕过草稿确认。"),
        ("approve", "模板不得绕过草稿确认。"),
        ("hard delete", "模板不得要求删除或废弃对象。"),
        ("delete object", "模板不得要求删除或废弃对象。"),
        ("delete entity", "模板不得要求删除或废弃对象。"),
        ("eval(", "模板不得要求执行代码。"),
        ("exec(", "模板不得要求执行代码。"),
        ("系统提示", "模板不得覆盖系统提示或 guardrails。"),
        ("系统规则", "模板不得覆盖系统提示或 guardrails。"),
        ("输出 schema", "模板不得覆盖结构化输出契约。"),
        ("忽略 schema", "模板不得覆盖结构化输出契约。"),
        ("不要输出 json", "模板不得覆盖结构化输出契约。"),
        ("调用工具", "模板不得要求调用工具。"),
        ("执行 shell", "模板不得要求执行 shell。"),
        ("执行 bash", "模板不得要求执行 shell。"),
        ("执行 callable", "模板不得要求执行 callable。"),
        ("执行 sql", "模板不得要求输出或执行 SQL。"),
        ("写入数据库", "模板不得要求直接写数据库。"),
        ("数据库写入", "模板不得要求直接写数据库。"),
        ("直接写入正史", "模板不得绕过建议采用边界。"),
        ("提升为正史", "模板不得绕过建议采用边界。"),
        ("自动确认", "模板不得绕过建议采用边界。"),
        ("自动批准", "模板不得绕过建议采用边界。"),
        ("绕过审核", "模板不得绕过建议采用边界。"),
        ("直接删除", "模板不得要求删除或废弃对象。"),
        ("删除对象", "模板不得要求删除或废弃对象。"),
        ("废弃对象", "模板不得要求删除或废弃对象。"),
        ("输出密钥", "不要要求输出或泄露密钥。"),
    ]
    for needle, message in unsafe_checks:
        if needle in lower:
            issues.append(
                _issue("P1", "prompt.unsafe_instruction", message, "prompt_text")
            )
    if "正史" in text and ("直接" in text or "自动" in text):
        issues.append(
            _issue(
                "P1",
                "prompt.canonical_bypass",
                "模板不得要求直接或自动写入已采用资产。",
                "prompt_text",
            )
        )
    if "全文" in text or "完整正文" in text:
        issues.append(
            _issue(
                "P2",
                "prompt.full_body_requested",
                "模板不应要求返回完整正文。",
                "prompt_text",
            )
        )
    return _dedupe_issues(issues)


def validation_state(issues: list[PromptTemplateIssue]) -> str:
    if any(issue.severity == "P1" for issue in issues):
        return "invalid"
    if issues:
        return "warning"
    return "valid"


def render_template(
    prompt_text: str,
    variables_json: list[dict[str, Any]],
    values: dict[str, Any],
    *,
    value_limit: int | None = None,
) -> str:
    declared = {item.get("name"): item for item in variables_json if item.get("name")}

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        variable = declared.get(name, {})
        value = _variable_value(name, variable, values)
        rendered = str(value or "")
        if value_limit is not None and len(rendered) > value_limit:
            return f"{rendered[:value_limit]}...[已截断]"
        return rendered

    return _PLACEHOLDER_RE.sub(replace, prompt_text).strip()


def missing_required_variables(
    variables_json: list[dict[str, Any]],
    values: dict[str, Any],
) -> list[str]:
    return [
        str(item["name"])
        for item in variables_json
        if item.get("name")
        and item.get("required")
        and not _variable_value(
            str(item["name"]),
            item,
            values,
        )
    ]


def _raise_if_blocking(issues: list[PromptTemplateIssue]) -> None:
    blocking = [issue for issue in issues if issue.severity == "P1"]
    if blocking:
        raise ValidationError(blocking[0].message)


def _declared_variables(
    variables_json: list[dict[str, Any]],
    issues: list[PromptTemplateIssue],
) -> dict[str, dict[str, Any]]:
    declared: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(variables_json):
        name = str(item.get("name") or "").strip()
        if not name or not _VARIABLE_NAME_RE.match(name):
            issues.append(
                _issue(
                    "P1",
                    "variable.invalid_name",
                    "变量名只支持英文、数字和下划线，且不能以数字开头。",
                    f"variables_json.{index}.name",
                )
            )
            continue
        if name in declared:
            issues.append(
                _issue(
                    "P1",
                    "variable.duplicate",
                    "变量名重复。",
                    f"variables_json.{index}.name",
                )
            )
        declared[name] = item
    return declared


def _placeholders(prompt_text: str, issues: list[PromptTemplateIssue]) -> set[str]:
    names = set(_PLACEHOLDER_RE.findall(prompt_text or ""))
    for raw in _ANY_PLACEHOLDER_RE.findall(prompt_text or ""):
        if not _VARIABLE_NAME_RE.match(raw.strip()):
            issues.append(
                _issue(
                    "P1",
                    "variable.invalid_placeholder",
                    "占位符格式无效。",
                    f"{{{{{raw}}}}}",
                )
            )
    return names


def _variable_value(
    name: str,
    variable: dict[str, Any],
    values: dict[str, Any],
) -> Any:
    value = values.get(name)
    if value is None or value == "":
        value = variable.get("default")
    return value


def _issue(severity: str, code: str, message: str, path: str) -> PromptTemplateIssue:
    return PromptTemplateIssue(
        severity=severity,  # type: ignore[arg-type]
        code=code,
        message=message,
        path=path,
    )


def _dedupe_issues(issues: list[PromptTemplateIssue]) -> list[PromptTemplateIssue]:
    seen: set[tuple[str, str | None]] = set()
    deduped: list[PromptTemplateIssue] = []
    for issue in issues:
        key = (issue.code, issue.path)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(issue)
    return deduped


def _summary(text: str, limit: int = 360) -> str:
    compact = " ".join((text or "").split())
    return compact[:limit]


def _builtin_keys() -> list[str]:
    return list(BUILTIN_GENERATION_TEMPLATES)


def _is_builtin_id(template_id: str) -> bool:
    return template_id.startswith("builtin:")


def _builtin_key_from_id(template_id: str) -> str:
    return template_id.split(":", 1)[1] if ":" in template_id else template_id
