/**
 * worldRelationsAliasesOps — world 关系/别名模态操作与 inline 动作。
 *
 * 对应 vanilla worldView 的 showRelationCreateForm/showAliasCreateForm/
 * deleteRelation/deleteAlias（worldView.js:2351-2397 / 3086-3137）及
 * 关联的 review 动作。模态全部走全局 showModalHtml，API 经 bridge getApi，
 * toast 提示，成功后 router.refresh（同视图 navigate 会被 isSameRender 跳过 onEnter，拿到旧数据）。
 *
 * 列表数据（entities）不跨 subView 缓存，因此创建表单打开时需从 API
 * 拉取实体列表填充下拉菜单。
 */
import { getApi, getAppState, getConfirmAction, getEsc, getRouter, getShowModalHtml, getToast } from "../../../bridge/index.js"
import { runBulkAction, bulkResultMessage, selectedItemsFrom, getBulkSelection, clearBulkSelection } from "./worldBulkSelection.js"

// ============================================================
// 列表注册表（tab 在 props 变化时同步当前可见列表）
// ============================================================

const listRegistry = {
  relations: [],
  aliases: [],
}

export function syncRelationsAliasesRegistry(partial = {}) {
  if (Array.isArray(partial.relations)) listRegistry.relations = partial.relations
  if (Array.isArray(partial.aliases)) listRegistry.aliases = partial.aliases
}

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
    && (state.currentView || null) === scope.view
    && (state.currentSubView || null) === scope.subView,
  )
}

function captureModalOwner(node = null) {
  const body = document.getElementById("modal-body")
  const overlay = document.getElementById("modal-overlay")
  return { body, overlay, node: node || body?.firstElementChild || null }
}

function ownsModalOwner(owner) {
  if (!owner?.body || !owner?.overlay) return true
  return Boolean(
    document.getElementById("modal-body") === owner.body
    && document.getElementById("modal-overlay") === owner.overlay
    && owner.node?.isConnected
    && owner.body.contains(owner.node)
    && !owner.overlay.classList.contains("hidden"),
  )
}

// ============================================================
// 实体选项渲染（与 vanilla _entityOptionsHtml 一致：option 格式为 "名称 · 类型 · 状态"）
// ============================================================

/**
 * 从 API 拉取可引用的实体列表并返回 <option> HTML 字符串。
 * 参数与渲染形态与 vanilla _entityOptionsHtml（worldView.js:3646-3652 / 3999 区域）对齐。
 */
async function fetchEntityOptionsHtml() {
  const esc = getEsc()
  const api = getApi()
  const projectId = getAppState()?.currentProjectId
  if (!projectId) return '<option value="">请先选择项目</option>'
  try {
    const data = await api.world.listEntities({
      novel_id: projectId,
      display_state: "active",
      skip: 0,
      // 后端 MAX_PAGE_SIZE=50（shared/constants.py），超限 422
      limit: 50,
    })
    const items = (data?.items || data || [])
      .filter((item) => (
        ["canonical", "draft", "candidate"].includes(item.status)
        && !item.content_json?._meta?.compatibility_shadow
      ))
    if (!items.length) return '<option value="">暂无可用对象</option>'
    return items.map((item) => {
      const id = item.id || item.entity_id
      return `<option value="${esc(id)}">${esc(item.name || "未命名对象")} · ${esc(item.entity_type || "-")} · ${esc(item.status || "-")}</option>`
    }).join("")
  } catch {
    return '<option value="">加载失败</option>'
  }
}

/** 构造实体下拉选择器的完整 HTML（含空选项 + 实体选项）。 */
async function entitySelectHtml(selectId) {
  const options = await fetchEntityOptionsHtml()
  return `<select class="form-select" id="${selectId}"><option value="">请选择</option>${options}</select>`
}

// ============================================================
// 创建表单（async：先 fetch 实体，再展示含实体选项的完整模态 HTML）
// ============================================================

/** 对应 vanilla showRelationCreateForm（worldView.js:2351-2397）。 */
export async function showRelationCreateForm() {
  const toast = getToast()
  const showModalHtml = getShowModalHtml()
  const scope = captureWorldOperationScope()
  const projectId = scope.projectId
  let pending = false
  // 先 fetch 实体选项再构建 HTML（确保模态打开时 select 已有完整选项）
  const [sourceSelectHtml, targetSelectHtml] = await Promise.all([
    entitySelectHtml("rel-source"),
    entitySelectHtml("rel-target"),
  ])
  if (!ownsWorldOperationScope(scope)) return
  const formHtml = `
    <div class="form-group">
      <label>源对象</label>
      ${sourceSelectHtml}
    </div>
    <div class="form-group">
      <label>关系类型</label>
      <select class="form-select" id="rel-type">
        <option value="friend_of">朋友</option>
        <option value="enemy_of">敌人</option>
        <option value="ally_of">盟友</option>
        <option value="member_of">成员</option>
        <option value="leader_of">领导者</option>
        <option value="located_at">位于</option>
        <option value="contains">包含</option>
        <option value="related_to">相关</option>
      </select>
    </div>
    <div class="form-group">
      <label>目标对象</label>
      ${targetSelectHtml}
    </div>
    <div class="form-group">
      <label>描述</label>
      <input class="form-input" id="rel-desc" placeholder="关系描述（可选）" />
    </div>
  `
  showModalHtml("新建关系", formHtml, [{
    text: "创建",
    class: "btn-primary",
    handler: async () => {
      if (pending) return false
      const src = document.getElementById("rel-source")?.value
      const tgt = document.getElementById("rel-target")?.value
      if (!src || !tgt) {
        toast("请选择源对象和目标对象", "warning")
        return false
      }
      const modalOwner = captureModalOwner(document.getElementById("rel-source"))
      pending = true
      try {
        const api = getApi()
        await api.world.createRelationship({
          source_id: src,
          source_type: "entity",
          target_id: tgt,
          target_type: "entity",
          relation_type: document.getElementById("rel-type")?.value || "related_to",
          description: document.getElementById("rel-desc")?.value || "",
        }, projectId)
        if (!ownsWorldOperationScope(scope) || !ownsModalOwner(modalOwner)) return true
        toast("关系已创建", "success")
        getRouter()?.refresh?.()
        return true
      } catch (err) {
        pending = false
        if (!ownsWorldOperationScope(scope) || !ownsModalOwner(modalOwner)) return true
        toast(err?.message || "创建失败", "error")
        return false
      }
    },
  }])
}

/** 对应 vanilla showAliasCreateForm（worldView.js:3086-3124）。 */
export async function showAliasCreateForm() {
  const toast = getToast()
  const showModalHtml = getShowModalHtml()
  const scope = captureWorldOperationScope()
  const projectId = scope.projectId
  let pending = false
  // 先 fetch 实体选项
  const aliasSelectHtml = await entitySelectHtml("alias-entity")
  if (!ownsWorldOperationScope(scope)) return
  const formHtml = `
    <div class="form-group">
      <label>所属对象</label>
      ${aliasSelectHtml}
    </div>
    <div class="form-group">
      <label>别名文本</label>
      <input class="form-input" id="alias-text" placeholder="别名" />
    </div>
    <div class="form-group">
      <label>别名类型</label>
      <select class="form-select" id="alias-type">
        <option value="name">名称</option>
        <option value="title">称号</option>
        <option value="nickname">昵称</option>
        <option value="alias">化名</option>
        <option value="translation">译名</option>
      </select>
    </div>
  `
  showModalHtml("新建别名", formHtml, [{
    text: "创建",
    class: "btn-primary",
    handler: async () => {
      if (pending) return false
      const eid = document.getElementById("alias-entity")?.value
      const text = document.getElementById("alias-text")?.value?.trim()
      if (!eid || !text) {
        toast("请选择对象并输入别名", "warning")
        return false
      }
      const modalOwner = captureModalOwner(document.getElementById("alias-text"))
      pending = true
      try {
        const api = getApi()
        await api.world.createAlias({
          entity_id: eid,
          alias: text,
          alias_type: document.getElementById("alias-type")?.value || "name",
        }, projectId)
        if (!ownsWorldOperationScope(scope) || !ownsModalOwner(modalOwner)) return true
        toast("别名已创建", "success")
        getRouter()?.refresh?.()
        return true
      } catch (err) {
        pending = false
        if (!ownsWorldOperationScope(scope) || !ownsModalOwner(modalOwner)) return true
        toast(err?.message || "创建失败", "error")
        return false
      }
    },
  }])
}

// ============================================================
// 删除操作
// ============================================================

/** 对应 vanilla deleteRelation（worldView.js:2649-2657）。 */
export function deleteRelation(relId) {
  const toast = getToast()
  const confirmAction = getConfirmAction()
  const api = getApi()
  const scope = captureWorldOperationScope()
  const projectId = scope.projectId
  confirmAction("确定删除此关系？", async () => {
    const modalOwner = captureModalOwner()
    try {
      await api.world.deleteRelationship(relId, { novel_id: projectId })
      if (!ownsWorldOperationScope(scope) || !ownsModalOwner(modalOwner)) return true
      toast("已删除", "success")
      const router = getRouter()
      router?.refresh?.()
      return true
    } catch (err) {
      if (!ownsWorldOperationScope(scope) || !ownsModalOwner(modalOwner)) return true
      toast(err?.message || "删除失败", "error")
      return false
    }
  }, "确认删除")
}

/** 对应 vanilla deleteAlias（worldView.js:3126-3137）。 */
export function deleteAlias(entityId, alias) {
  const esc = getEsc()
  const toast = getToast()
  const confirmAction = getConfirmAction()
  const scope = captureWorldOperationScope()
  const projectId = scope.projectId
  if (!entityId || !alias) {
    toast("参数错误：缺少实体 ID 或别名", "error")
    return
  }
  confirmAction(`确定删除别名 "${esc(alias)}"？`, async () => {
    const modalOwner = captureModalOwner()
    try {
      const api = getApi()
      await api.world.deleteAlias(entityId, alias, { novel_id: projectId })
      if (!ownsWorldOperationScope(scope) || !ownsModalOwner(modalOwner)) return true
      toast("已删除", "success")
      const router = getRouter()
      router?.refresh?.()
      return true
    } catch (err) {
      if (!ownsWorldOperationScope(scope) || !ownsModalOwner(modalOwner)) return true
      toast(err?.message || "删除失败", "error")
      return false
    }
  }, `确认删除别名 "${esc(alias)}"`)
}

// ============================================================
// 批量操作（对应 vanilla _executeBulkAction 的 world-relations/world-aliases 分支）
// ============================================================

/** 批量操作：给定 scope、action 和已选列表，执行 API 调用。 */
export async function runCanonicalBulkAction(scope, action, items) {
  const toast = getToast()
  const router = getRouter()
  const api = getApi()
  const operationScope = captureWorldOperationScope()
  const projectId = operationScope.projectId
  const label = {
    "review-relations": "批量采用关系",
    "delete-relations": "批量删除关系",
    "review-aliases": "批量采用别名",
    "delete-aliases": "批量删除别名",
  }[action] || "批量操作"

  const result = await runBulkAction(items, async (item) => {
    if (action === "delete-relations") {
      await api.world.deleteRelationship(item.id || item.relationship_id, { novel_id: projectId })
    } else if (action === "review-relations") {
      await api.world.reviewEditRelationship(item.id || item.relationship_id, { confirm_review: true }, projectId)
    } else if (action === "delete-aliases") {
      await api.world.deleteAlias(item.entity_id, item.alias, { novel_id: projectId })
    } else if (action === "review-aliases") {
      await api.world.updateAlias(item.entity_id, item.alias, {
        status: "canonical",
        needs_review: false,
        reviewed_at: new Date().toISOString(),
        reviewed_by: "manual",
        reviewed_from: "world_aliases_bulk",
      }, { novel_id: projectId })
    }
  })

  if (!ownsWorldOperationScope(operationScope)) return
  toast(
    bulkResultMessage(result, label, (item) => item.alias || item.relation_type || item.id || ""),
    result.failed.length ? "warning" : "success",
  )
  clearBulkSelection(scope)
  router?.refresh?.()
}

// ============================================================
// Inline 证据渲染助手（纯函数，供 tab 模板使用）
// ============================================================

/**
 * 对应 vanilla _inlineEvidenceHtml（worldView.js:2032-2043），
 * 适用于别名等扁平对象。
 */
export function inlineEvidencePairs(item = {}) {
  const esc = (v) => String(v ?? "")
  return [
    ["来源", item.source === "deep_import" ? "深度导入" : item.source],
    ["处理批次", item.workflow_id],
    ["章节", item.source_chapter_index],
    ["场景", item.scene_index || item.scene_id],
    ["置信度", item.confidence != null ? `${(Number(item.confidence) * 100).toFixed(0)}%` : ""],
    ["引用", item.quote],
  ].filter(([, value]) => value != null && String(value).trim() !== "")
}

/**
 * 对应 vanilla _inlineRelationEvidenceHtml（worldView.js:2318-2348），
 * 适用于关系对象的 evidence。
 */
export function inlineRelationEvidencePairs(relation = {}) {
  const reviewMeta = relation.review_meta && typeof relation.review_meta === "object"
    ? relation.review_meta
    : {}
  const pairs = [
    ["来源", (reviewMeta.source || relation.source) === "deep_import" ? "深度导入" : (reviewMeta.source || relation.source)],
    ["处理批次", reviewMeta.workflow_id || relation.workflow_id],
    ["场景", reviewMeta.scene_index ?? reviewMeta.scene_id ?? relation.scene_index ?? relation.scene_id],
    ["章节", reviewMeta.source_chapter_index ?? relation.source_chapter_index ?? relation.source_chapter_id],
    ["强度", relation.strength != null ? `${Math.round(Number(relation.strength) * 100)}%` : ""],
    ["引用", reviewMeta.quote || relation.quote || ""],
  ]
  return pairs.filter(([, value]) => value != null && String(value).trim() !== "")
}

/**
 * 对应 vanilla _aliasKey（worldView.js:2922-2925）。
 */
export function aliasKey(alias) {
  if (!alias) return ""
  return `${alias.entity_id || ""}::${alias.alias || ""}`
}

// ============================================================
// review 动作（迁自 vanilla _markRelationReviewed / _markAliasReviewed 等）
// ============================================================

/** 对应 vanilla _markRelationReviewed。 */
export async function markRelationReviewed(id) {
  const api = getApi()
  const toast = getToast()
  const scope = captureWorldOperationScope()
  const projectId = scope.projectId
  try {
    await api.world.reviewEditRelationship(id, { confirm_review: true }, projectId)
    if (ownsWorldOperationScope(scope)) {
      toast("关系已采用", "success")
      getRouter()?.refresh?.()
    }
    return true
  } catch (err) {
    if (ownsWorldOperationScope(scope)) toast(err?.message || "采用关系失败", "error")
    return false
  }
}

/** 对应 vanilla _markRelationUnreviewed。 */
export async function markRelationUnreviewed(id) {
  const api = getApi()
  const toast = getToast()
  const scope = captureWorldOperationScope()
  const projectId = scope.projectId
  try {
    await api.world.reviewEditRelationship(id, { confirm_review: false, clear_review: true }, projectId)
    if (ownsWorldOperationScope(scope)) {
      toast("关系已标记为待处理", "success")
      getRouter()?.refresh?.()
    }
    return true
  } catch (err) {
    if (ownsWorldOperationScope(scope)) toast(err?.message || "状态更新失败", "error")
    return false
  }
}

/** 对应 vanilla _markAliasReviewed。 */
export async function markAliasReviewed(entityId, alias) {
  const api = getApi()
  const toast = getToast()
  const scope = captureWorldOperationScope()
  const projectId = scope.projectId
  if (!entityId || !alias) {
    toast("参数错误", "error")
    return false
  }
  try {
    await api.world.updateAlias(entityId, alias, {
      status: "canonical",
      needs_review: false,
      reviewed_at: new Date().toISOString(),
      reviewed_by: "manual",
      reviewed_from: "world_aliases",
    }, { novel_id: projectId })
    if (ownsWorldOperationScope(scope)) {
      toast("别名已采用", "success")
      getRouter()?.refresh?.()
    }
    return true
  } catch (err) {
    if (ownsWorldOperationScope(scope)) toast(err?.message || "采用别名失败", "error")
    return false
  }
}

/** 对应 vanilla _markAliasUnreviewed。 */
export async function markAliasUnreviewed(entityId, alias) {
  const api = getApi()
  const toast = getToast()
  const scope = captureWorldOperationScope()
  const projectId = scope.projectId
  if (!entityId || !alias) {
    toast("参数错误", "error")
    return false
  }
  try {
    await api.world.updateAlias(entityId, alias, {
      needs_review: true,
      reviewed_at: null,
    }, { novel_id: projectId })
    if (ownsWorldOperationScope(scope)) {
      toast("别名已标记为待处理", "success")
      getRouter()?.refresh?.()
    }
    return true
  } catch (err) {
    if (ownsWorldOperationScope(scope)) toast(err?.message || "状态更新失败", "error")
    return false
  }
}

/** 对应 vanilla showRelationReviewEditForm（worldView.js:2587-2647）。 */
export function showRelationReviewEditForm(relationId) {
  const esc = getEsc()
  const toast = getToast()
  const showModalHtml = getShowModalHtml()
  const confirmAction = getConfirmAction()
  const api = getApi()
  const scope = captureWorldOperationScope()
  const projectId = scope.projectId
  const relation = listRegistry.relations.find((r) => (r.id || r.relationship_id) === relationId)
  if (!relation) {
    toast("未找到目标关系", "error")
    return
  }
  const formHtml = `
    <div class="form-group">
      <label>源对象</label>
      <select class="form-select" id="rel-review-source"><option value="${esc(relation.source_id || relation.source_entity_id || "")}">${esc(relation.source_name || relation.source_entity_name || "当前源对象")}</option></select>
    </div>
    <div class="form-group">
      <label>关系类型</label>
      <input class="form-input" id="rel-review-type" value="${esc(relation.relation_type || "")}" />
    </div>
    <div class="form-group">
      <label>目标对象</label>
      <select class="form-select" id="rel-review-target"><option value="${esc(relation.target_id || relation.target_entity_id || "")}">${esc(relation.target_name || relation.target_entity_name || "当前目标对象")}</option></select>
    </div>
    <div class="form-group">
      <label>描述</label>
      <textarea class="form-textarea" id="rel-review-description" rows="3">${esc(relation.description || "")}</textarea>
    </div>
    <div class="form-group">
      <label>强度</label>
      <input class="form-input" id="rel-review-strength" type="number" min="0" max="1" step="0.01" value="${esc(relation.strength ?? 0.5)}" />
    </div>
  `
  showModalHtml("编辑后采用关系", formHtml, [{
    text: "采用",
    class: "btn-primary",
    handler: async () => {
      const sourceId = document.getElementById("rel-review-source")?.value || ""
      const targetId = document.getElementById("rel-review-target")?.value || ""
      const relationType = document.getElementById("rel-review-type")?.value?.trim() || ""
      if (!sourceId || !targetId || !relationType) {
        toast("请填写源对象、目标对象和关系类型", "warning")
        return false
      }
      const modalOwner = captureModalOwner(document.getElementById("rel-review-type"))
      try {
        await api.world.reviewEditRelationship(relationId, {
          source_id: sourceId,
          target_id: targetId,
          relation_type: relationType,
          description: document.getElementById("rel-review-description")?.value?.trim() || "",
          strength: Number(document.getElementById("rel-review-strength")?.value || 0.5),
          confirm_review: true,
        }, projectId)
        if (!ownsWorldOperationScope(scope) || !ownsModalOwner(modalOwner)) return true
        toast("关系已采用", "success")
        getRouter()?.refresh?.()
        return true
      } catch (err) {
        if (!ownsWorldOperationScope(scope) || !ownsModalOwner(modalOwner)) return true
        toast(err?.message || "采用关系失败", "error")
        return false
      }
    },
  }])
}
