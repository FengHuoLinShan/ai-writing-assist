/**
 * worldEntityOps — world 实体/候选操作（对应 vanilla worldView 的公开操作面）。
 *
 * vanilla 里这些方法挂在 worldView 单例上、直接读写 this._entities/_candidates；
 * Vue 化后列表数据是 island load() 下发的 props（只读），因此本模块维护一个
 * 列表注册表（syncWorldListRegistry 由各 tab 在 props 变化时同步），操作函数
 * 经注册表查找目标。模态全部走全局 showModalHtml（Vue 树外），表单读取与
 * referencePicker 挂载保持 vanilla 原样。
 *
 * 刷新语义：vanilla 的 router.refresh()/navigate/_reloadWorldLists 统一等价于
 * getRouter().refresh()（island 重挂载 = onEnter 全量重取）。模态操作由全局
 * modal/router 守卫项目导航；无模态的异步操作在回写 UI 前校验启动时作用域。
 */
import { getApi, getAppState, getCloseModal, getConfirm, getConfirmAction, getEsc, getRouter, getShowModalHtml, getToast } from "../../../bridge/index.js"
import { createReferencePicker } from "../../../../shared/referencePicker.js"
import { buildMapUrl } from "../../../../views/mapRouteContext.js"
import {
  candidateAction,
  candidateMeta,
  candidateTargetId,
  candidateTargetName,
  createConflictDetail,
  entityId,
  entityReferenceItem,
  entityReviewContent,
  formatSimilarEntities,
  fusionSuggestionKey,
  isAliasTargetEntity,
  isMergeTargetEntity,
  isSuggestionShadow,
  suggestionId,
} from "./worldEntityHelpers.js"
import { CUSTOM_ENTITY_TYPE_SENTINEL, REVIEW_ALIAS_TYPE_FALLBACK } from "./worldQuery.js"
import { clearBulkSelection, getBulkSelection, runBulkAction, bulkResultMessage, selectedItemsFrom } from "./worldBulkSelection.js"

// ============================================================
// 列表注册表（tab 在 props 变化时同步当前可见列表）
// ============================================================

const worldListRegistry = {
  entities: [],
  candidates: [],
  entityTypes: [],
  reviewTypeCatalog: { alias_types: REVIEW_ALIAS_TYPE_FALLBACK },
}

export function syncWorldListRegistry(partial = {}) {
  if (Array.isArray(partial.entities)) worldListRegistry.entities = partial.entities
  if (Array.isArray(partial.candidates)) worldListRegistry.candidates = partial.candidates
  if (Array.isArray(partial.entityTypes)) worldListRegistry.entityTypes = partial.entityTypes
  if (partial.reviewTypeCatalog) worldListRegistry.reviewTypeCatalog = partial.reviewTypeCatalog
}

/** 对应 vanilla _findEntity。 */
export function findEntity(id) {
  return [...worldListRegistry.entities, ...worldListRegistry.candidates]
    .find((entity) => entityId(entity) === id) || null
}

function findCandidate(id) {
  return worldListRegistry.candidates.find((item) => entityId(item) === id) || null
}

/** 候选乐观更新钩子：review tab 注册（props 只读，乐观移除走本地镜像）。 */
export const candidateListHooks = {
  removeOptimistically: null, // async (id) => snapshot
  restoreSnapshot: null, // async (snapshot) => void
}

export function registerCandidateListHooks(hooks = {}) {
  candidateListHooks.removeOptimistically = hooks.removeOptimistically || null
  candidateListHooks.restoreSnapshot = hooks.restoreSnapshot || null
}

// ============================================================
// referencePicker（模态内，Vue 树外，保持 vanilla 原样）
// ============================================================

let referencePickers = []

export function destroyWorldEntityPickers() {
  for (const picker of referencePickers) picker?.destroy?.()
  referencePickers = []
}

/** 对应 vanilla _mountEntityReferencePicker。 */
function mountEntityReferencePicker({
  rootId,
  inputId,
  sourceId = "",
  selectedId = "",
  selectedName = "",
  canonicalOnly = false,
}) {
  const root = document.getElementById(rootId)
  const input = document.getElementById(inputId)
  if (!root || !input) return null
  destroyWorldEntityPickers()
  const api = getApi()
  const projectId = getAppState()?.currentProjectId
  const eligible = canonicalOnly ? isMergeTargetEntity : isAliasTargetEntity
  const source = {
    kind: "entity",
    label: "世界对象",
    search: async (query, { projectId: pid, limit }) => {
      const data = await api.world.listEntities({
        novel_id: pid,
        q: query || undefined,
        ...(canonicalOnly ? { display_state: "active" } : {}),
        skip: 0,
        limit,
      })
      return (data?.items || data || [])
        .filter((item) => entityId(item) !== sourceId)
        .filter(eligible)
        .map((item) => entityReferenceItem(item))
    },
    resolve: async (ids, { projectId: pid }) => Promise.all(ids.map(async (id) => {
      try {
        const entity = await api.world.getEntity(id, pid)
        if (entityId(entity) === sourceId || !eligible(entity)) {
          return { kind: "entity", id, label: entity?.name || "不可用引用", unavailable: true }
        }
        return entityReferenceItem(entity)
      } catch {
        return { kind: "entity", id, label: "不可用引用", unavailable: true }
      }
    })),
  }
  const selectedEntity = selectedId ? findEntity(selectedId) : null
  const initialItems = selectedId && selectedEntity && eligible(selectedEntity)
    ? [entityReferenceItem(selectedEntity)]
    : selectedId && selectedName
      ? [{ kind: "entity", id: selectedId, label: selectedName, description: "已选目标" }]
      : []
  const picker = createReferencePicker({
    root,
    projectId,
    sources: [source],
    initialItems,
    placeholder: "按名称或别名搜索目标对象",
    onChange: (_items, refs) => {
      input.value = refs[0]?.id || ""
      input.dataset.referenceLabel = _items[0]?.label || ""
    },
  })
  if (selectedId && !initialItems.length) picker.resolve([{ kind: "entity", id: selectedId }])
  referencePickers.push(picker)
  return picker
}

/** review 决策模态复用同一 picker 挂载（useWorldReview 的别名入口）。 */
export function mountEntityReferencePickerForReview(options) {
  return mountEntityReferencePicker(options)
}

// ============================================================
// 类型选择控件（对应 vanilla _entityTypeControlHtml 系列）
// ============================================================

function entityTypesWithCurrent(currentType = "") {
  const items = [...worldListRegistry.entityTypes]
  if (currentType && !items.some((item) => item.value === currentType)) {
    items.push({ value: currentType, label: currentType, kind: "custom" })
  }
  return items
}

function entityTypeControlHtml(prefix, currentType = "") {
  const esc = getEsc()
  const items = entityTypesWithCurrent(currentType)
  const renderOptions = (kind) => items
    .filter((item) => (item.kind || "system") === kind)
    .map((item) => `<option value="${esc(item.value)}" ${item.value === currentType ? "selected" : ""}>${esc(item.label)}</option>`)
    .join("")
  const systemOptions = renderOptions("system")
  const customOptions = renderOptions("custom")
  return `
    <select class="form-select" id="${prefix}-entity-type">
      <optgroup label="系统类型">${systemOptions}</optgroup>
      ${customOptions ? `<optgroup label="项目自定义类型">${customOptions}</optgroup>` : ""}
      <option value="${CUSTOM_ENTITY_TYPE_SENTINEL}">＋ 新建自定义类型…</option>
    </select>
    <div id="${prefix}-custom-type-wrap" hidden>
      <input class="form-input" id="${prefix}-custom-entity-type" maxlength="64" placeholder="例如：宗教/神祇" />
      <small>自定义类型使用通用对象档案，不自动获得地图、人物或事件等系统类型能力。</small>
    </div>
  `
}

function bindEntityTypeControl(prefix) {
  const select = document.getElementById(`${prefix}-entity-type`)
  const wrap = document.getElementById(`${prefix}-custom-type-wrap`)
  if (!select || !wrap) return
  const sync = () => { wrap.hidden = select.value !== CUSTOM_ENTITY_TYPE_SENTINEL }
  select.addEventListener("change", sync)
  sync()
}

function readEntityType(prefix) {
  const selected = document.getElementById(`${prefix}-entity-type`)?.value || ""
  if (selected !== CUSTOM_ENTITY_TYPE_SENTINEL) return selected
  return document.getElementById(`${prefix}-custom-entity-type`)?.value?.trim() || ""
}

/** 对应 vanilla _showEntityTypeBlocker。 */
function showEntityTypeBlocker(err, targetId) {
  if (err?.body?.error !== "entity_type_change_blocked") return false
  const blockers = Array.isArray(err.body?.context?.blockers) ? err.body.context.blockers : []
  const detail = blockers.map((item) => `${item.kind}（${item.count}）`).join("、")
  const target = document.getElementById(targetId)
  if (target) {
    target.textContent = `类型变更被阻止：${detail || err.body.detail || "仍有专属依赖"}`
    target.hidden = false
  }
  return true
}

// ============================================================
// 通用助手
// ============================================================

function captureWorldOperationScope() {
  const state = getAppState()
  return {
    projectId: state?.currentProjectId || null,
    view: state?.currentView || null,
    subView: state?.currentSubView || null,
  }
}

function ownsWorldOperationScope(scope) {
  const state = getAppState()
  return Boolean(
    scope
    && state
    && (state.currentProjectId || null) === scope.projectId
    && (state?.currentView || null) === scope.view
    && (state?.currentSubView || null) === scope.subView,
  )
}

/** 对应 vanilla _finishEntityMutation；调用方为受全局 modal/router 管理的模态操作。 */
async function finishEntityMutation(successMessage) {
  const toast = getToast()
  try {
    const refreshed = await getRouter()?.refresh?.()
    if (refreshed === false) throw new Error("当前页面未完成刷新")
  } catch (err) {
    toast(`${successMessage}，但列表刷新失败：${err.message || "未知错误"}`, "warning")
    return true
  }
  toast(successMessage, "success")
  return true
}

/** 对应 vanilla _adoptEntity。 */
export async function adoptEntity(entity) {
  const api = getApi()
  const projectId = getAppState()?.currentProjectId
  const sid = suggestionId(entity)
  if (sid) return api.world.confirmSuggestion(sid, projectId)
  return api.world.promoteEntity(entityId(entity), projectId)
}

/** 对应 vanilla _ignoreEntity。 */
export async function ignoreEntity(entity) {
  const api = getApi()
  const projectId = getAppState()?.currentProjectId
  const sid = suggestionId(entity)
  if (sid) return api.world.rejectSuggestion(sid, projectId)
  return api.world.updateEntity(entityId(entity), { status: "ignored" }, projectId)
}

/** 对应 vanilla _ignoreOrDeleteEntity。 */
async function ignoreOrDeleteEntity(entity) {
  const api = getApi()
  const projectId = getAppState()?.currentProjectId
  const sid = suggestionId(entity)
  if (sid) return api.world.rejectSuggestion(sid, projectId)
  return api.world.deleteEntity(entityId(entity), projectId)
}

/** 对应 vanilla _aliasTypeOptionsHtml。 */
function aliasTypeOptionsHtml(selected = "alias") {
  const esc = getEsc()
  const types = [...(worldListRegistry.reviewTypeCatalog.alias_types || REVIEW_ALIAS_TYPE_FALLBACK)]
  if (selected && !types.some((item) => item.value === selected)) {
    types.unshift({ value: selected, label: `保留原类型：${selected}`, category: "自定义" })
  }
  return types
    .map((item) => `<option value="${esc(item.value)}" ${selected === item.value ? "selected" : ""}>${esc(item.label)}${item.category === "自定义" ? "" : ` (${esc(item.value)})`}</option>`)
    .join("")
}

/** 对应 vanilla _aliasEvidenceHtml。 */
function aliasEvidenceHtml(item = {}) {
  const esc = getEsc()
  const evidence = [
    ["来源", item.source === "deep_import" ? "深度导入" : item.source],
    ["处理批次", item.workflow_id],
    ["章节", item.source_chapter_index],
    ["场景", item.scene_id || item.scene_index],
    ["置信度", item.confidence != null ? `${(Number(item.confidence) * 100).toFixed(0)}%` : ""],
    ["引用", item.quote],
  ].filter(([, value]) => value != null && String(value).trim() !== "")
  if (!evidence.length) return ""
  return `
    <div class="form-group">
      <label>证据</label>
      <div style="border:1px solid var(--border);border-radius:var(--radius-sm);padding:8px;color:var(--text-muted);font-size:12px;">
        ${evidence.map(([label, value]) => `<div><strong>${esc(label)}：</strong>${esc(value)}</div>`).join("")}
      </div>
    </div>
  `
}

// ============================================================
// 新建 / 编辑 / 删除 / 采用
// ============================================================

/** 对应 vanilla _showCreateForm。 */
export function showEntityCreateForm(initial = {}) {
  const esc = getEsc()
  const toast = getToast()
  const showModalHtml = getShowModalHtml()
  const confirmAction = getConfirmAction()
  let submissionPending = false
  const formHtml = `
    <div class="form-group">
      <label>名称 *</label>
      <input class="form-input" id="create-entity-name" placeholder="对象名称" value="${esc(initial.name || "")}" />
    </div>
    <div class="form-group">
      <label>类型</label>
      ${entityTypeControlHtml("create", initial.entity_type || "character")}
    </div>
    <div class="form-group">
      <label>概要</label>
      <textarea class="form-textarea" id="create-entity-summary" rows="3" placeholder="简要描述">${esc(initial.summary || "")}</textarea>
    </div>
  `

  showModalHtml("新建世界对象", formHtml, [
    {
      text: "创建",
      class: "btn-primary",
      handler: async () => {
        if (submissionPending) return false
        const projectId = getAppState()?.currentProjectId
        const name = document.getElementById("create-entity-name")?.value
        if (!name) {
          toast("请输入名称", "warning")
          return false
        }
        const payload = {
          name,
          entity_type: readEntityType("create"),
          summary: document.getElementById("create-entity-summary")?.value || "",
        }
        if (!payload.entity_type) {
          toast("请输入自定义类型名称", "warning")
          return false
        }
        submissionPending = true
        try {
          await getApi().world.createEntity(payload, projectId)
        } catch (err) {
          const detail = createConflictDetail(err)
          if (detail?.requires_confirmation) {
            const similar = formatSimilarEntities(detail.similar_entities)
            let forceSubmissionPending = false
            // 交给二次确认弹窗后，原表单不再占有提交锁。用户取消确认时
            // 仍可修改名称并重试；强制创建自身仍有独立的防重锁。
            submissionPending = false
            confirmAction(
              `发现相似对象：${similar || "已有对象"}。是否仍要创建？`,
              async () => {
                if (forceSubmissionPending) return false
                forceSubmissionPending = true
                try {
                  await getApi().world.createEntity({ ...payload, force_create: true }, projectId)
                } catch (err2) {
                  forceSubmissionPending = false
                  toast(`创建失败：${err2.message}`, "error")
                  return false
                }
                return finishEntityMutation(`对象 "${name}" 已创建`)
              },
              "强制创建",
              () => showEntityCreateForm(payload),
            )
            return false
          }
          submissionPending = false
          toast(`创建失败：${err.message}`, "error")
          return false
        }
        return finishEntityMutation(`对象 "${name}" 已创建`)
      },
    },
  ])
  bindEntityTypeControl("create")
}

/** 对应 vanilla editEntity。 */
export function editEntity(id) {
  const esc = getEsc()
  const toast = getToast()
  const showModalHtml = getShowModalHtml()
  const entity = findEntity(id)
  if (!entity) return
  const sid = suggestionId(entity)
  const isPending = ["draft", "candidate"].includes(entity.status)
  let submissionPending = false

  const formHtml = `
    <div class="form-group">
      <label>名称</label>
      <input class="form-input" id="edit-entity-name" value="${esc(entity.name)}" />
    </div>
    <div class="form-group">
      <label>类型</label>
      ${entityTypeControlHtml("edit", entity.entity_type)}
    </div>
    <div class="form-group">
      <label>概要</label>
      <textarea class="form-textarea" id="edit-entity-summary" rows="3">${esc(entity.summary || "")}</textarea>
    </div>
    <div id="edit-entity-error" class="alert alert-error" hidden></div>
  `

  showModalHtml(isPending ? "编辑后采用世界对象" : "编辑世界对象", formHtml, [
    {
      text: isPending ? "编辑后采用" : "保存",
      class: "btn-primary",
      handler: async () => {
        if (submissionPending) return false
        const projectId = getAppState()?.currentProjectId
        const payload = {
          name: document.getElementById("edit-entity-name")?.value,
          entity_type: readEntityType("edit"),
          summary: document.getElementById("edit-entity-summary")?.value,
        }
        if (!payload.entity_type) {
          const target = document.getElementById("edit-entity-error")
          if (target) {
            target.textContent = "请输入自定义类型名称"
            target.hidden = false
          }
          return false
        }
        if (!isPending && payload.entity_type !== entity.entity_type) {
          const confirmed = getConfirm()(
            "更改类型会迁移对象档案；若仍有地图、人物或事件等专属依赖，保存将被阻止。是否继续？",
          )
          if (!confirmed) return false
        }
        submissionPending = true
        try {
          if (sid) {
            await getApi().world.editAndConfirmSuggestion(sid, payload, projectId)
          } else if (isPending) {
            await getApi().world.promoteEntity(id, projectId, payload)
          } else {
            await getApi().world.updateEntity(id, payload, projectId)
          }
        } catch (err) {
          submissionPending = false
          if (!showEntityTypeBlocker(err, "edit-entity-error")) {
            const target = document.getElementById("edit-entity-error")
            if (target) {
              target.textContent = `保存失败：${err.message || "未知错误"}`
              target.hidden = false
            }
          }
          return false
        }
        return finishEntityMutation(isPending ? "已编辑并采用" : "已保存")
      },
    },
  ])
  bindEntityTypeControl("edit")
}

/** 对应 vanilla deleteEntity。 */
export function deleteEntity(id) {
  const esc = getEsc()
  const toast = getToast()
  const entity = findEntity(id)
  const suggestionShadow = isSuggestionShadow(entity)
  const message = suggestionShadow
    ? `确定忽略待处理项“${esc(entity?.name || id)}”吗？`
    : "确定要删除此世界对象吗？此操作不可撤销。"
  getConfirmAction()(message, async () => {
    try {
      await ignoreOrDeleteEntity(entity || { id })
      toast(suggestionShadow ? "已忽略" : "已删除", "success")
      getRouter()?.refresh?.()
    } catch (err) {
      toast(`删除失败：${err.message}`, "error")
    }
  }, "确认删除")
}

/** 对应 vanilla promoteEntity。 */
export function promoteEntity(id) {
  const esc = getEsc()
  const toast = getToast()
  const entity = findEntity(id)
  if (!entity) return
  getConfirmAction()(
    `确定采用“${esc(entity.name)}”吗？采用后将作为当前有效世界设定参与后续创作。`,
    async () => {
      try {
        await adoptEntity(entity)
        toast("世界对象已采用", "success")
        getRouter()?.refresh?.()
      } catch (err) {
        toast(`采用失败：${err.message}`, "error")
      }
    },
    "确认采用",
  )
}

/** 对应 vanilla _markEntityReviewed。 */
export async function markEntityReviewed(id) {
  const api = getApi()
  const toast = getToast()
  const scope = captureWorldOperationScope()
  const projectId = scope.projectId
  let entity = findEntity(id)
  try {
    const fetched = await api.world.getEntity(id, projectId)
    if (fetched) entity = fetched
  } catch {
    // 列表数据足够完成检查标记；详情读取失败不阻断单项操作。
  }
  if (!entity) {
    if (ownsWorldOperationScope(scope)) toast("未找到目标世界对象", "error")
    return false
  }
  try {
    await api.world.updateEntity(id, {
      content_json: entityReviewContent(entity, true, "world_objects"),
    }, projectId)
    if (ownsWorldOperationScope(scope)) {
      toast("世界对象已标记为已检查", "success")
      getRouter()?.refresh?.()
    }
    return true
  } catch (err) {
    if (ownsWorldOperationScope(scope)) {
      toast(`世界对象检查状态更新失败：${err.message || "未知错误"}`, "error")
    }
    return false
  }
}

/** 对应 vanilla _markEntityUnreviewed。 */
export async function markEntityUnreviewed(id) {
  const api = getApi()
  const toast = getToast()
  const scope = captureWorldOperationScope()
  const projectId = scope.projectId
  let entity = findEntity(id)
  try {
    const fetched = await api.world.getEntity(id, projectId)
    if (fetched) entity = fetched
  } catch {
    // 列表数据足够完成检查标记；详情读取失败不阻断单项操作。
  }
  if (!entity) {
    if (ownsWorldOperationScope(scope)) toast("未找到目标世界对象", "error")
    return false
  }
  try {
    await api.world.updateEntity(id, {
      content_json: entityReviewContent(entity, false, "world_objects"),
    }, projectId)
    if (ownsWorldOperationScope(scope)) {
      toast("世界对象已标记为需要人工检查", "success")
      getRouter()?.refresh?.()
    }
    return true
  } catch (err) {
    if (ownsWorldOperationScope(scope)) {
      toast(`世界对象检查状态更新失败：${err.message || "未知错误"}`, "error")
    }
    return false
  }
}

// ============================================================
// 候选采用 / 忽略 / 设为别名
// ============================================================

/** 对应 vanilla acceptCandidate（乐观移除经 candidateListHooks，由 review tab 注册）。 */
export async function acceptCandidate(id) {
  const esc = getEsc()
  const toast = getToast()
  const candidate = findCandidate(id)
  if (!candidate) return
  return getConfirmAction()(
    `确定采用“${esc(candidate.name)}”吗？`,
    async () => {
      const snapshot = candidateListHooks.removeOptimistically
        ? await candidateListHooks.removeOptimistically(id)
        : null
      try {
        await adoptEntity(candidate)
        toast(`“${candidate.name}”已采用`, "success")
        await getRouter()?.refresh?.()
      } catch (err) {
        if (snapshot && candidateListHooks.restoreSnapshot) {
          await candidateListHooks.restoreSnapshot(snapshot)
        }
        toast(`处理失败：${err.message}`, "error")
      }
    },
    "确认采用",
  )
}

/** 对应 vanilla ignoreCandidate。 */
export async function ignoreCandidate(id) {
  const esc = getEsc()
  const toast = getToast()
  const candidate = findCandidate(id)
  const isTemporary = candidateAction(candidate) === "temporary_only"
  return getConfirmAction()(
    isTemporary
      ? `将“${candidate?.name || id}”标记为临时并从待处理中移除？`
      : `确定忽略待处理项“${candidate?.name || id}”？`,
    async () => {
      const snapshot = candidateListHooks.removeOptimistically
        ? await candidateListHooks.removeOptimistically(id)
        : null
      try {
        await ignoreEntity(candidate)
        toast(isTemporary ? "已设为临时" : "已忽略", "success")
        await getRouter()?.refresh?.()
      } catch (err) {
        if (snapshot && candidateListHooks.restoreSnapshot) {
          await candidateListHooks.restoreSnapshot(snapshot)
        }
        toast(`操作失败：${err.message}`, "error")
      }
    },
    isTemporary ? "设为临时" : "忽略",
  )
}

/** 对应 vanilla showResolveAliasForm。 */
export function showResolveAliasForm(candidateId) {
  const esc = getEsc()
  const toast = getToast()
  const showModalHtml = getShowModalHtml()
  const candidate = findCandidate(candidateId)
  if (!candidate) {
    toast("未找到目标待处理项", "error")
    return
  }
  const sid = suggestionId(candidate)
  const targetId = candidateTargetId(candidate)
  const targetName = candidateTargetName(candidate)
  const formHtml = `
    <p style="margin-bottom:10px;">将 <strong>${esc(candidate.name || "")}</strong> 登记为已有对象的别名。</p>
    <div class="form-group">
      <label>目标对象 *</label>
      <div id="alias-target-picker"></div>
      <input type="hidden" id="alias-target-id" value="${esc(targetId)}" />
    </div>
    <div class="form-group">
      <label>别名文本 *</label>
      <input class="form-input" id="alias-edit-text" value="${esc(candidate.name || "")}" />
    </div>
    <div class="form-group">
      <label>别名类型</label>
      <select class="form-select" id="alias-edit-type">${aliasTypeOptionsHtml("alias")}</select>
    </div>
    ${aliasEvidenceHtml(candidateMeta(candidate))}
  `
  showModalHtml("设为别名", formHtml, [{
    text: "设为别名",
    class: "btn-primary",
    handler: async () => {
      const selectedTargetId = document.getElementById("alias-target-id")?.value
      const text = document.getElementById("alias-edit-text")?.value?.trim()
      const type = document.getElementById("alias-edit-type")?.value || "alias"
      if (!selectedTargetId || !text) {
        toast("请选择目标对象并输入别名", "warning")
        return false
      }
      try {
        const projectId = getAppState()?.currentProjectId
        const payload = {
          target_entity_id: selectedTargetId,
          alias: text,
          alias_type: type,
        }
        if (sid) {
          await getApi().world.resolveSuggestionAsAlias(sid, payload, projectId)
        } else {
          await getApi().world.resolveEntityAsAlias(candidateId, payload, projectId)
        }
        toast("待处理项已设为别名", "success")
        getRouter()?.refresh?.()
      } catch (err) {
        toast(err.message || "设为别名失败", "error")
        return false
      }
    },
  }])
  mountEntityReferencePicker({
    rootId: "alias-target-picker",
    inputId: "alias-target-id",
    sourceId: candidateId,
    selectedId: targetId,
    selectedName: targetName,
  })
  globalThis.refreshModalFormBaseline?.()
}

// ============================================================
// 合并 / 回滚 / 知识 / 地图
// ============================================================

/** 对应 vanilla showMergeForm。 */
export function showMergeForm(candidateId) {
  const esc = getEsc()
  const toast = getToast()
  const showModalHtml = getShowModalHtml()
  const confirmAction = getConfirmAction()
  const entity = findEntity(candidateId)
  if (!entity) return
  const targetId = candidateTargetId(entity)
  const targetName = candidateTargetName(entity)

  const formHtml = `
    <p style="margin-bottom:10px;">将 <strong>${esc(entity.name)}</strong> 合并到目标已采用对象。</p>
    <div class="form-group">
      <label>选择目标对象 *</label>
      <div id="merge-target-picker"></div>
      <input type="hidden" id="merge-target-id" value="${esc(targetId)}" />
      <p style="font-size:12px;color:var(--text-muted);margin-top:6px;">显示名称、类型、状态和摘要；没有明确目标时请先搜索再选择。</p>
    </div>
  `
  showModalHtml("合并对象", formHtml, [{
    text: "合并",
    class: "btn-primary",
    handler: async () => {
      const selectedTargetId = document.getElementById("merge-target-id")?.value
      if (!selectedTargetId) { toast("请选择目标对象", "warning"); return false }
      const selectedLabel = document.getElementById("merge-target-id")?.dataset.referenceLabel
        || findEntity(selectedTargetId)?.name
        || "所选目标对象"
      destroyWorldEntityPickers()
      confirmAction(
        `确定将「${entity.name || "当前对象"}」合并到「${selectedLabel}」吗？来源对象会进入历史态。`,
        () => mergeEntity(candidateId, selectedTargetId),
        "确认合并",
      )
      return false
    },
  }])
  mountEntityReferencePicker({
    rootId: "merge-target-picker",
    inputId: "merge-target-id",
    sourceId: entityId(entity),
    selectedId: targetId,
    selectedName: targetName,
    canonicalOnly: true,
  })
  globalThis.refreshModalFormBaseline?.()
}

/** 对应 vanilla _mergeEntity。 */
async function mergeEntity(candidateId, targetId) {
  const toast = getToast()
  try {
    const projectId = getAppState()?.currentProjectId
    const candidate = findEntity(candidateId)
    const sid = suggestionId(candidate)
    if (sid) {
      await getApi().world.mergeSuggestion(sid, targetId, projectId)
    } else {
      await getApi().world.mergeEntity(candidateId, targetId, projectId)
    }
    toast("实体已合并", "success")
    getRouter()?.refresh?.()
    return true
  } catch (err) {
    toast(err.message || "合并失败", "error")
    return false
  }
}

/** 对应 vanilla showRollbackForm。 */
export function showRollbackForm(entityIdParam) {
  const esc = getEsc()
  const toast = getToast()
  const showModalHtml = getShowModalHtml()
  const entity = worldListRegistry.entities.find((e) => entityId(e) === entityIdParam)
  if (!entity) return

  const formHtml = `
    <p style="margin-bottom:10px;">回滚 <strong>${esc(entity.name)}</strong> 到指定场景索引。</p>
    <div class="form-group">
      <label>目标场景索引 *</label>
      <input class="form-input" id="rollback-scene-index" type="number" min="0" value="0" />
    </div>
  `
  showModalHtml("回滚对象", formHtml, [{
    text: "回滚",
    class: "btn-primary",
    handler: async () => {
      const idx = parseInt(document.getElementById("rollback-scene-index")?.value || "0", 10)
      if (Number.isNaN(idx)) { toast("请输入有效的场景索引", "warning"); return false }
      try {
        const result = await getApi().world.rollbackEntity(entityIdParam, idx, getAppState()?.currentProjectId)
        toast((result.warnings || []).length ? "回滚完成，存在警告" : "回滚完成", (result.warnings || []).length ? "warning" : "success")
        getRouter()?.refresh?.()
      } catch (err) {
        toast(err.message || "回滚失败", "error")
        return false
      }
    },
  }])
}

/** 对应 vanilla showKnowledgeForm。 */
export function showKnowledgeForm(characterId) {
  const esc = getEsc()
  const toast = getToast()
  const showModalHtml = getShowModalHtml()
  const character = worldListRegistry.entities.find((e) => entityId(e) === characterId)
  if (!character) return

  const entityOptions = worldListRegistry.entities.length === 0
    ? `<option value="">暂无对象</option>`
    : worldListRegistry.entities
      .map((e) => `<option value="${esc(entityId(e))}">${esc(e.name || "未命名")}</option>`)
      .join("")
  const formHtml = `
    <p style="margin-bottom:10px;">为 <strong>${esc(character.name)}</strong> 添加知识边界。</p>
    <div class="form-group">
      <label>目标对象 *</label>
      <select class="form-select" id="knowledge-target-id"><option value="">请选择</option>${entityOptions}</select>
    </div>
    <div class="form-group">
      <label>了解程度 *</label>
      <select class="form-select" id="knowledge-level">
        <option value="unknown">未知</option>
        <option value="rumor">传闻</option>
        <option value="partial">部分了解</option>
        <option value="full">完全了解</option>
        <option value="false_belief">错误认知</option>
      </select>
    </div>
    <div class="form-group">
      <label>已知内容</label>
      <textarea class="form-textarea" id="knowledge-content" rows="2" placeholder="角色知道什么"></textarea>
    </div>
    <div class="form-group">
      <label>误解内容（仅错误认知）</label>
      <textarea class="form-textarea" id="knowledge-misconception" rows="2" placeholder="角色的误解"></textarea>
    </div>
    <div class="form-group">
      <label>来源章节索引</label>
      <input class="form-input" id="knowledge-chapter" type="number" min="0" placeholder="可选" />
    </div>
  `
  showModalHtml("添加知识边界", formHtml, [{
    text: "添加",
    class: "btn-primary",
    handler: async () => {
      const payload = {
        character_id: characterId,
        target_id: document.getElementById("knowledge-target-id")?.value,
        target_type: "entity",
        knowledge_level: document.getElementById("knowledge-level")?.value,
        known_content: document.getElementById("knowledge-content")?.value || "",
        misconception: document.getElementById("knowledge-misconception")?.value || "",
        source_chapter_index: document.getElementById("knowledge-chapter")?.value
          ? parseInt(document.getElementById("knowledge-chapter").value, 10)
          : null,
      }
      if (!payload.target_id) { toast("请选择目标对象", "warning"); return false }
      if (payload.knowledge_level === "false_belief" && !payload.misconception) {
        toast("错误认知必须填写误解内容", "warning")
        return false
      }
      try {
        await getApi().world.createKnowledge(characterId, payload, getAppState()?.currentProjectId)
        toast("知识边界已添加", "success")
        getRouter()?.refresh?.()
      } catch (err) {
        toast(err.message || "添加知识边界失败", "error")
        return false
      }
    },
  }])
}

/** 对应 vanilla _openEntityPresence。 */
function openEntityPresence(presence, entityIdParam, scope) {
  if (!ownsWorldOperationScope(scope)) return false
  const target = presence?.open_target || {}
  const pathRef = presence?._pathRef || presence?.path_refs?.[0] || {}
  const focusesPath = Boolean(pathRef.path_id || target.focus_path_id)
  const url = buildMapUrl({
    projectId: scope.projectId,
    mapId: target.map_id || presence.map_id,
    sceneId: target.scene_id,
    focusEntityId: target.focus_entity_id || entityIdParam,
    focusHexQ: focusesPath ? null : presence.representative_world_q ?? presence.representative_hex_q,
    focusHexR: focusesPath ? null : presence.representative_world_r ?? presence.representative_hex_r,
    focusPathId: pathRef.path_id || target.focus_path_id,
    focusLayerNodeId: pathRef.layer_node_id || target.focus_layer_node_id,
    mode: target.mode || "live",
  })
  window.open(url, "_blank", "noopener")
  return true
}

/** 对应 vanilla _openEntityMap。 */
export async function openEntityMap(entityIdParam) {
  const toast = getToast()
  const showModalHtml = getShowModalHtml()
  const closeModal = getCloseModal()
  const scope = captureWorldOperationScope()
  const projectId = scope.projectId
  if (!projectId) {
    toast("请先选择项目", "warning")
    return
  }
  try {
    const entity = findEntity(entityIdParam)
    const includeCandidates = entity?.status === "candidate" || entity?.status === "draft"
    const presence = await getApi().world.getEntityMapPresence(entityIdParam, projectId, includeCandidates)
    if (!ownsWorldOperationScope(scope)) return
    const items = presence?.items || []
    const choices = items.flatMap((item) => (
      item.path_refs?.length
        ? item.path_refs.map((pathRef) => ({ ...item, _pathRef: pathRef }))
        : [item]
    ))
    if (choices.length === 1) {
      openEntityPresence(choices[0], entityIdParam, scope)
      return
    }
    if (choices.length > 1) {
      const esc = getEsc()
      const roleLabels = {
        location: "地点",
        "marker.character": "人物标记",
        "marker.event": "事件标记",
        "marker.item": "物品标记",
        territory: "领地",
        terrain: "覆盖素材",
        "path.start": "线路起点",
        "path.end": "线路终点",
      }
      const body = `
        <div class="world-map-presence-list">
          ${choices.map((item, index) => `
            <button class="world-map-presence-row" data-map-presence-index="${index}">
              <strong>${esc(item.map_name)}${item._pathRef?.path_name ? ` · ${esc(item._pathRef.path_name)}` : ""}</strong>
              <span>${esc((item._pathRef?.roles || item.roles || []).map((role) => roleLabels[role] || role).join("、") || "地图位置")} · ${Number(item.binding_count || 0)} 个空间绑定</span>
              ${item.scene_index_min != null || item.scene_index_max != null
                ? `<small>场景 ${esc(item.scene_index_min ?? "?")}–${esc(item.scene_index_max ?? "?")}</small>`
                : ""}
            </button>
          `).join("")}
        </div>
      `
      showModalHtml("选择关联地图", body, [{ text: "取消", class: "btn", handler: closeModal }])
      document.querySelectorAll("[data-map-presence-index]").forEach((button) => {
        button.onclick = () => {
          closeModal()
          openEntityPresence(choices[Number(button.dataset.mapPresenceIndex)], entityIdParam, scope)
        }
      })
      return
    }
    const target = await getApi().world.getMapOpenTarget(projectId, { focusEntityId: entityIdParam })
    if (!ownsWorldOperationScope(scope)) return
    const url = buildMapUrl({
      projectId,
      mapId: target.map_id,
      sceneId: target.scene_id,
      focusEntityId: target.focus_entity_id || entityIdParam,
      focusPathId: target.focus_path_id,
      focusLayerNodeId: target.focus_layer_node_id,
      mode: target.mode || (target.map_id ? "dashboard" : "overview"),
    })
    if (target.fallback_message) {
      toast(target.fallback_message, "warning")
    }
    window.open(url, "_blank", "noopener")
  } catch (err) {
    if (ownsWorldOperationScope(scope)) {
      toast(`打开地图失败：${err.message || "未知错误"}`, "error")
    }
  }
}

// ============================================================
// fusion 建议模态
// ============================================================

/** 对应 vanilla _showEntityFusionSuggestions（建议列表来自 fusionManager，由调用方传入）。 */
export function showEntityFusionSuggestions(fusionProgress) {
  const esc = getEsc()
  const toast = getToast()
  const showModalHtml = getShowModalHtml()
  const closeModal = getCloseModal()
  const result = fusionProgress?.raw?.result || {}
  const suggestions = Array.isArray(result.suggestions) ? result.suggestions : []
  if (!suggestions.length) {
    toast("暂无合并建议", "info")
    return
  }
  const suggestionsByKey = new Map(suggestions.map((item) => [fusionSuggestionKey(item), item]))
  const rows = suggestions.map((item) => {
    const suggestionKey = fusionSuggestionKey(item)
    const actionLabel = item.action === "merge" ? "合并" : item.action === "alias_only" ? "登记别名" : "需要人工检查"
    const evidence = (item.evidence_anchors || []).map((anchor) => anchor.snippet || anchor.source_type || "").filter(Boolean).join(" / ")
    const canonical = item.requires_canonical_confirmation ? `
      <label style="display:block;margin-top:6px;color:var(--warning);font-size:12px;">
        <input type="checkbox" data-canonical-merge />
        ${item.action === "alias_only"
          ? "我理解这会将已采用来源对象转为目标对象的别名"
          : "我理解这会合并两个已采用对象"}
      </label>
    ` : ""
    return `
      <article class="world-fusion-suggestion-card" data-fusion-card="${esc(suggestionKey)}">
        <label style="display:flex;gap:8px;align-items:flex-start;">
          <input type="checkbox" data-fusion-key="${esc(suggestionKey)}" ${item.action === "needs_review" ? "" : "checked"} />
          <span>
            <strong>${esc(actionLabel)}：</strong>
            ${esc(item.source_entity_name)} → ${esc(item.target_entity_name)}
          </span>
        </label>
        <div style="color:var(--text-dim);font-size:12px;margin-top:4px;">
          ${esc(item.entity_type || "-")} · 置信度 ${esc(item.confidence ?? "-")} · ${esc(item.match_method || "-")}
        </div>
        <p style="margin:6px 0 0;">${esc(item.reason || "无说明")}</p>
        ${canonical}
        <details style="margin-top:6px;"><summary>证据</summary><p>${esc(evidence || "无")}</p></details>
      </article>
    `
  }).join("")
  showModalHtml("世界对象 AI 合并建议", rows, [{
    text: "应用选中建议",
    class: "btn-primary",
    handler: async () => {
      const selected = Array.from(document.querySelectorAll("[data-fusion-key]:checked"))
        .map((input) => {
          const key = input.getAttribute("data-fusion-key")
          const card = input.closest("[data-fusion-card]")
          return { item: suggestionsByKey.get(key), card }
        })
        .filter((entry) => entry.item)
        .filter((entry) => entry.item.action === "merge" || entry.item.action === "alias_only")
      if (!selected.length) {
        toast("请选择可应用的建议", "warning")
        return false
      }
      const payload = selected.map(({ item, card }) => {
        const allowCanonical = Boolean(card?.querySelector("[data-canonical-merge]")?.checked)
        return {
          action: item.action,
          source_entity_id: item.source_entity_id,
          target_entity_id: item.target_entity_id,
          alias: item.alias || item.source_entity_name,
          allow_canonical_merge: item.action === "merge" && allowCanonical,
          allow_canonical_alias: item.action === "alias_only" && allowCanonical,
        }
      })
      try {
        const applied = await getApi().world.applyEntityFusionSuggestions({
          novel_id: getAppState()?.currentProjectId,
          confirmed: true,
          suggestions: payload,
        })
        closeModal()
        toast(`已应用 ${applied.applied || 0} 条建议`, "success")
        getRouter()?.refresh?.()
      } catch (err) {
        toast(err.message || "应用失败", "error")
        return false
      }
    },
  }], { size: "large" })
}

// ============================================================
// 批量操作（objects scope：fuse-entities/alias-entities/delete-entities）
// ============================================================

/** 对应 vanilla _showBulkEntityResolution。 */
function showBulkEntityResolution(action, items) {
  const esc = getEsc()
  const toast = getToast()
  const showModalHtml = getShowModalHtml()
  const closeModal = getCloseModal()
  const confirmAction = getConfirmAction()
  if (items.length < 2) {
    toast("请至少选择两个已采用对象", "warning")
    return
  }
  if (items.some((item) => item.status && item.status !== "canonical")) {
    toast("融合和标记为别名仅适用于已采用对象", "warning")
    return
  }
  const entityTypes = new Set(items.map((item) => item.entity_type).filter(Boolean))
  if (entityTypes.size > 1) {
    toast("请选择相同类型的对象", "warning")
    return
  }

  const operationLabel = action === "fuse-entities" ? "融合" : "标记为别名"
  const rows = items.map((item, index) => {
    const id = entityId(item)
    return `
      <label class="world-bulk-resolution-option">
        <input type="radio" name="world-bulk-target" value="${esc(id)}" ${index === 0 ? "checked" : ""} />
        <span><strong>${esc(item.name || id)}</strong><small>${esc(item.entity_type || "未分类")}</small></span>
      </label>
    `
  }).join("")
  const explanation = action === "fuse-entities"
    ? "其余对象的内容、别名和关系会融合到保留对象，来源对象进入历史态。"
    : "其余对象的名称会成为保留对象的别名，关系会迁移，但不会融合摘要等内容；来源对象进入历史态。"

  showModalHtml(`批量${operationLabel}`, `
    <p>${esc(explanation)}</p>
    <p class="form-help">请选择要保留的主对象：</p>
    <div class="world-bulk-resolution-list">${rows}</div>
  `, [{
    text: `确认${operationLabel}`,
    class: "btn-primary",
    handler: async () => {
      const targetId = document.querySelector('input[name="world-bulk-target"]:checked')?.value
      const target = items.find((item) => entityId(item) === targetId)
      if (!target) {
        toast("请选择要保留的主对象", "warning")
        return false
      }
      const sources = items.filter((item) => entityId(item) !== targetId)
      const confirmationMessage = action === "fuse-entities"
        ? `确定将 ${sources.length} 个已采用对象融合到「${target.name || targetId}」吗？此操作会让来源对象进入历史态。`
        : `确定将 ${sources.length} 个已采用对象标记为「${target.name || targetId}」的别名吗？此操作会让来源对象进入历史态。`
      confirmAction(
        confirmationMessage,
        async () => {
          try {
            const result = await getApi().world.applyEntityFusionSuggestions({
              novel_id: getAppState()?.currentProjectId,
              confirmed: true,
              suggestions: sources.map((source) => ({
                action: action === "fuse-entities" ? "merge" : "alias_only",
                source_entity_id: entityId(source),
                target_entity_id: targetId,
                alias: source.name || undefined,
                allow_canonical_merge: action === "fuse-entities",
                allow_canonical_alias: action === "alias-entities",
              })),
            })
            closeModal()
            const warningCount = Number(result.skipped || 0)
            toast(
              `已${operationLabel} ${result.applied || 0} 个对象${warningCount ? `，跳过 ${warningCount} 个` : ""}`,
              warningCount ? "warning" : "success",
            )
            clearBulkSelection("world-objects")
            getRouter()?.refresh?.()
            return true
          } catch (err) {
            toast(err.message || `${operationLabel}失败`, "error")
            return false
          }
        },
        "确认执行",
      )
      return false
    },
  }], { size: "large" })
}

/** 对应 vanilla _executeBulkAction 的 world-objects 分支。 */
async function executeObjectsBulkAction(action, items) {
  const toast = getToast()
  const label = {
    "promote-entities": "批量采用",
    "review-entities": "批量标记已检查",
    "delete-entities": "批量删除对象",
  }[action] || "批量操作"

  let actionable = items
  if (action === "promote-entities") {
    actionable = items.filter((item) => item.status === "draft" || item.status === "candidate")
  } else if (action === "review-entities") {
    actionable = items.filter((item) => !isSuggestionShadow(item))
  }
  if (actionable.length === 0) {
    toast("所选项目没有可执行的批量动作", "warning")
    return
  }

  const api = getApi()
  const projectId = getAppState()?.currentProjectId
  const result = await runBulkAction(actionable, async (item) => {
    if (action === "promote-entities") {
      await adoptEntity(item)
    } else if (action === "review-entities") {
      await api.world.updateEntity(entityId(item), {
        content_json: entityReviewContent(item, true, "world_objects_bulk"),
      }, projectId)
    } else if (action === "delete-entities") {
      await ignoreOrDeleteEntity(item)
    }
  })

  toast(bulkResultMessage(result, label, (item) => item.name || entityId(item)), result.failed.length ? "warning" : "success")
  clearBulkSelection("world-objects")
  getRouter()?.refresh?.()
}

/** 对应 vanilla _runBulkAction 的 world-objects 分支。 */
export function runObjectsBulkAction(action, visibleEntities) {
  const toast = getToast()
  const selection = getBulkSelection("world-objects")
  const items = selectedItemsFrom(visibleEntities || worldListRegistry.entities, selection, entityId)
  if (items.length === 0) {
    toast("请先选择要处理的项目", "warning")
    return
  }
  if (["fuse-entities", "alias-entities"].includes(action)) {
    showBulkEntityResolution(action, items)
    return
  }
  const labelByAction = {
    "promote-entities": "批量采用",
    "review-entities": "批量标记已检查",
    "delete-entities": "批量删除对象",
  }
  const danger = action?.includes("delete") || action?.includes("ignore")
  getConfirmAction()(
    `确定对选中的 ${items.length} 项执行「${labelByAction[action] || action}」吗？`,
    async () => {
      await executeObjectsBulkAction(action, items)
    },
    danger ? "确认执行" : "确认",
  )
}
