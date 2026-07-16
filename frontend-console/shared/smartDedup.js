/**
 * Smart Dedup 业务管理器
 *
 * 负责智能去重扫描的启动、轮询、建议展示与应用。
 * 从 app.js 下沉，便于独立测试与复用。
 */
import {
  clearActiveWorkflow,
  normalizeTaskProgress,
  persistActiveWorkflow,
  pollTaskProgress,
  recoverActiveWorkflows,
} from "./workflowProgress.js"
import { renderWorkflowCard } from "./progressRenderer.js"
import { createReferencePicker } from "./referencePicker.js"
import { worldAssetDisplay } from "./assetDisplayState.js"

const PAGE_SIZE = 6

export function createSmartDedupManager({
  api,
  router,
  toast,
  modal,
  esc,
  onRenderActions,
  getCurrentProjectId,
}) {
  const modalApi = modal || {
    showModalHtml: globalThis.showModalHtml,
    closeModal: globalThis.closeModal,
  }

  const manager = {
    _taskId: null,
    _progress: null,
    _poller: null,
    _suggestionPage: 0,
    _suggestionDraft: {},
    _scanTaskId: null,
    _scanProjectId: null,
    _workbenchResult: null,
    _groupDraft: {},
    _activeGroupId: null,
    _groupResults: {},
    _activeProjectId: null,
    _manualPrimaryPickers: [],
    _currentProjectId() {
      return typeof getCurrentProjectId === "function" ? getCurrentProjectId() : null
    },

    getState() {
      return {
        taskId: this._taskId,
        progress: this._progress,
        suggestionPage: this._suggestionPage,
        suggestionDraft: { ...this._suggestionDraft },
        scanTaskId: this._scanTaskId,
        scanProjectId: this._scanProjectId,
        groupDraft: { ...this._groupDraft },
        activeGroupId: this._activeGroupId,
      }
    },

    _showModalHtml(title, body, buttons = [], options = {}) {
      this._destroyManualPrimaryPickers()
      const fn = modalApi.showModalHtml || modalApi.showHtml
      if (typeof fn === "function") fn(title, body, buttons, options)
    },

    _closeModal() {
      this._destroyManualPrimaryPickers()
      const fn = modalApi.closeModal || modalApi.close
      if (typeof fn === "function") fn()
    },

    syncProject(projectId) {
      const nextProjectId = projectId || null
      if (this._activeProjectId === nextProjectId) return

      this._clearScanState()
      this._activeProjectId = nextProjectId
      if (nextProjectId) this.recoverWorkflow(nextProjectId)
      this._notifyRender()
    },

    recoverWorkflow(projectId) {
      const nextProjectId = projectId || null
      if (!nextProjectId) return
      if (this._activeProjectId !== nextProjectId) {
        this._clearScanState()
        this._activeProjectId = nextProjectId
      }
      const workflow = recoverActiveWorkflows(nextProjectId)
        .find((item) => item.workflowType === "smart_dedup_scan")
      if (!workflow?.taskId) return
      this._taskId = workflow.taskId
      this._scanProjectId = nextProjectId
      this._progress = normalizeTaskProgress({
        task_id: workflow.taskId,
        task_type: "smart_dedup_scan",
        status: "running",
        meta: workflow.meta || {},
      }, "smart_dedup_scan")
      this._startPolling(workflow.taskId)
    },

    async startScan() {
      const projectId = this._currentProjectId()
      if (!projectId) {
        toast("请先选择项目", "warning")
        return
      }
      this.syncProject(projectId)
      if (this._progress && !this._progress.terminal) {
        this.showProgress()
        return
      }
      try {
        this._suggestionPage = 0
        this._suggestionDraft = {}
        this._scanTaskId = null
        this._scanProjectId = projectId
        this._workbenchResult = null
        this._groupDraft = {}
        this._activeGroupId = null
        this._groupResults = {}
        const result = await api.projects.startSmartDedupScan(projectId, {})
        persistActiveWorkflow({
          taskId: result.task_id,
          workflowType: "smart_dedup_scan",
          label: "智能去重扫描",
          projectId,
        })
        if (this._currentProjectId() !== projectId) {
          this.syncProject(this._currentProjectId())
          return
        }
        this._taskId = result.task_id
        this._progress = normalizeTaskProgress({
          ...result,
          task_type: "smart_dedup_scan",
        }, "smart_dedup_scan")
        toast("智能去重扫描已提交", "success")
        this._startPolling(result.task_id, projectId)
        this._notifyRender()
      } catch (err) {
        if (this._currentProjectId() !== projectId) {
          this.syncProject(this._currentProjectId())
          return
        }
        toast(`智能去重启动失败：${err.message}`, "error")
      }
    },

    showProgress() {
      const progress = this._progress
      if (!progress) {
        this.startScan()
        return
      }
      if (progress.done) {
        this._showSuggestions()
        return
      }
      this._showModalHtml("智能去重", renderWorkflowCard(progress, {
        title: "智能去重扫描",
        destinationLabel: "完成后可选择合并或软废弃重复资产",
        detailLevel: "detailed",
      }), [])
    },

    handleAction(action) {
      if (action === "start-smart-dedup") {
        this.startScan()
      } else if (action === "show-smart-dedup-progress") {
        this.showProgress()
      }
    },

    renderActionButton(progressState = null) {
      const progress = progressState !== null ? progressState : this._progress
      const running = progress && !progress.terminal
      const done = progress?.done
      const label = running ? "查看智能去重" : done ? "查看去重建议" : "智能去重"
      const action = running || done ? "show-smart-dedup-progress" : "start-smart-dedup"
      return `
        <button class="btn btn-sm ${running ? "btn-primary" : ""}" data-action="${action}">
          ${esc(label)}
        </button>
      `
    },

    dispose() {
      this._destroyManualPrimaryPickers()
      this._stopPolling()
    },

    // ============================================================
    // 内部方法
    // ============================================================

    _notifyRender() {
      if (typeof onRenderActions === "function") onRenderActions()
    },

    _startPolling(taskId, projectId = this._activeProjectId || this._currentProjectId()) {
      this._stopPolling()
      const capturedProjectId = projectId
      this._poller = pollTaskProgress({
        taskId,
        workflowType: "smart_dedup_scan",
        apiClient: api,
        onUpdate: (progress) => {
          if (this._currentProjectId() !== capturedProjectId) {
            this.syncProject(this._currentProjectId())
            return
          }
          this._progress = progress
          this._notifyRender()
        },
        onDone: (progress) => {
          if (this._currentProjectId() !== capturedProjectId) {
            this.syncProject(this._currentProjectId())
            return
          }
          clearActiveWorkflow(progress.taskId || taskId)
          this._scanTaskId = progress.taskId || taskId
          this._taskId = null
          this._progress = progress
          toast("智能去重扫描完成", "success")
          this._notifyRender()
          this._showSuggestions()
        },
        onFailed: (progress) => {
          if (this._currentProjectId() !== capturedProjectId) {
            this.syncProject(this._currentProjectId())
            return
          }
          clearActiveWorkflow(progress.taskId || taskId)
          this._taskId = null
          this._progress = progress
          toast(`智能去重扫描失败：${progress.errorMessage || "未知错误"}`, "error")
          this._notifyRender()
        },
      })
    },

    _stopPolling() {
      if (this._poller?.stop) this._poller.stop()
      this._poller = null
    },

    _clearScanState() {
      this._destroyManualPrimaryPickers()
      this._stopPolling()
      this._taskId = null
      this._progress = null
      this._scanTaskId = null
      this._scanProjectId = null
      this._workbenchResult = null
      this._suggestionPage = 0
      this._suggestionDraft = {}
      this._groupDraft = {}
      this._activeGroupId = null
      this._groupResults = {}
    },

    _resetResult() {
      const taskId = this._taskId
        || this._progress?.taskId
        || this._progress?.id
        || this._progress?.raw?.result?.task_id
      if (taskId) clearActiveWorkflow(taskId)
      this._clearScanState()
      this._notifyRender()
    },

    _showSuggestions(page = this._suggestionPage || 0) {
      this._destroyManualPrimaryPickers()
      if (this._scanProjectId && this._scanProjectId !== this._currentProjectId()) {
        this._resetResult()
        return
      }
      const result = this._progress?.raw?.result || {}
      if (Number(result.schema_version) === 2 && Array.isArray(result.groups)) {
        this._workbenchResult = result
        this._showGroupWorkbench()
        return
      }
      const suggestions = this._suggestions(result)
      if (!suggestions.length) {
        this._resetResult()
        this._showModalHtml("智能去重", "<p>没有发现可处理的重复资产。</p>", [{
          text: "重新扫描",
          class: "btn-primary",
          handler: async () => this.startScan(),
        }])
        return
      }
      const totalPages = Math.max(1, Math.ceil(suggestions.length / PAGE_SIZE))
      this._suggestionPage = Math.max(0, Math.min(Number(page) || 0, totalPages - 1))
      const body = this._renderSuggestionsBody(
        result,
        suggestions,
        this._suggestionPage,
      )
      this._showModalHtml("智能去重建议", body, [{
        text: "应用选中建议",
        class: "btn-primary",
        handler: async () => this._applySuggestions(suggestions),
      }])
      this._bindSuggestionControls(suggestions)
    },

    _destroyManualPrimaryPickers() {
      for (const picker of this._manualPrimaryPickers || []) picker?.destroy?.()
      this._manualPrimaryPickers = []
    },

    _mountManualPrimaryPickers(suggestions) {
      const projectId = this._currentProjectId()
      document.querySelectorAll("[data-smart-dedup-manual-picker]").forEach((root) => {
        const index = Number(root.getAttribute("data-smart-dedup-manual-picker"))
        const item = suggestions[index]
        if (!item || item.asset_type !== "world_entity") return
        const draft = this._draftFor(index, item)
        const picker = createReferencePicker({
          root,
          projectId,
          sources: [{
            kind: "entity",
            label: "世界对象",
            search: async (query, { projectId: ownerProjectId, limit }) => {
              const data = await api.world.listEntities({
                novel_id: ownerProjectId,
                display_state: "active",
                q: query || undefined,
                skip: 0,
                limit,
              })
              const suggestionIds = new Set([
                String(item.source_asset_id || item.source_entity_id || ""),
                String(item.target_asset_id || item.target_entity_id || ""),
              ])
              return (data?.items || []).filter((entry) => {
                const entryId = String(entry.id || entry.entity_id || "")
                return entry?.status === "canonical" && !suggestionIds.has(entryId)
              }).map((entry) => {
                const display = worldAssetDisplay(entry)
                return {
                  id: entry.id || entry.entity_id,
                  label: entry.name || "未命名对象",
                  description: [entry.entity_type, entry.summary || entry.description].filter(Boolean).join(" · "),
                  status: display.label,
                }
              })
            },
            resolve: async (ids, { projectId: ownerProjectId }) => Promise.all(ids.map(async (id) => {
              try {
                const entry = await api.world.getEntity(id, ownerProjectId)
                const display = worldAssetDisplay(entry)
                return {
                  id: entry.id || entry.entity_id,
                  label: entry.name || "未命名对象",
                  description: entry.entity_type || "世界对象",
                  status: display.label,
                  unavailable: display.isHistory,
                }
              } catch {
                return { id, label: "不可用引用", unavailable: true }
              }
            })),
          }],
          placeholder: "按名称搜索其他主体对象",
          onChange: (items, refs) => {
            const hidden = document.querySelector(`[data-smart-dedup-manual-primary="${index}"]`)
            if (hidden) hidden.value = refs[0]?.id || ""
            const radio = document.querySelector(`input[name="smart-dedup-primary-${index}"][value="manual"]`)
            if (refs[0] && radio) radio.checked = true
            this._suggestionDraft[index] = {
              ...(this._suggestionDraft[index] || draft),
              primaryMode: refs[0] ? "manual" : (this._suggestionDraft[index]?.primaryMode || "target"),
              manualPrimaryId: refs[0]?.id || "",
              manualPrimaryLabel: items[0]?.label || "",
            }
          },
        })
        if (draft.manualPrimaryId) {
          picker.resolve([{ kind: "entity", id: draft.manualPrimaryId }]).then((items) => {
            if (items[0] && draft.manualPrimaryLabel) {
              picker.setItems([{ ...items[0], label: draft.manualPrimaryLabel }])
            }
          })
        }
        this._manualPrimaryPickers.push(picker)
      })
    },

    _captureGroupWorkbenchScroll() {
      const modalBody = document.getElementById("modal-body")
      const queue = document.querySelector(".smart-dedup-queue")
      const decision = document.querySelector(".smart-dedup-decision")
      const comparison = document.querySelector(".smart-dedup-compare-scroll")
      if (!modalBody && !queue && !decision && !comparison) return null
      return {
        modalBodyTop: modalBody?.scrollTop || 0,
        queueTop: queue?.scrollTop || 0,
        decisionTop: decision?.scrollTop || 0,
        comparisonLeft: comparison?.scrollLeft || 0,
      }
    },

    _restoreGroupWorkbenchScroll(snapshot) {
      if (!snapshot) return
      const modalBody = document.getElementById("modal-body")
      const queue = document.querySelector(".smart-dedup-queue")
      const decision = document.querySelector(".smart-dedup-decision")
      const comparison = document.querySelector(".smart-dedup-compare-scroll")
      if (modalBody) modalBody.scrollTop = snapshot.modalBodyTop
      if (queue) queue.scrollTop = snapshot.queueTop
      if (decision) decision.scrollTop = snapshot.decisionTop
      if (comparison) comparison.scrollLeft = snapshot.comparisonLeft
    },

    _showGroupWorkbench({ preserveScroll = false } = {}) {
      const scrollSnapshot = preserveScroll ? this._captureGroupWorkbenchScroll() : null
      if (this._scanProjectId !== this._currentProjectId()) {
        this._resetResult()
        return
      }
      const result = this._workbenchResult || this._progress?.raw?.result || {}
      const groups = this._groups(result)
      if (!groups.length) {
        this._resetResult()
        this._showModalHtml("智能去重", "<p>没有发现可处理的重复资产。</p>", [{
          text: "重新扫描",
          class: "btn-primary",
          handler: async () => this.startScan(),
        }])
        return
      }
      if (!groups.some((group) => group.group_id === this._activeGroupId)) {
        this._activeGroupId = groups[0].group_id
      }
      groups.forEach((group) => this._groupDraftFor(group))
      const readyCount = groups.filter((group) => this._groupReadiness(group).ready).length
      const successful = groups.filter((group) => this._groupResults[group.group_id]?.status === "success").length
      const staleCount = groups.filter((group) => this._groupResults[group.group_id]?.error_code === "stale_suggestion").length
      this._showModalHtml("智能去重裁决工作台", this._renderGroupWorkbench(result, groups), [
        {
          text: `执行已就绪组 (${readyCount})`,
          class: "btn-primary",
          handler: async () => this._applyReadyGroups(groups),
        },
        ...(successful === groups.length || staleCount > 0 ? [{
          text: "重新扫描",
          handler: async () => {
            this._resetResult()
            await this.startScan()
          },
        }] : []),
      ], { size: "large", protectUnsaved: true })
      this._bindGroupControls(groups)
      this._restoreGroupWorkbenchScroll(scrollSnapshot)
    },

    _groups(result) {
      return (Array.isArray(result?.groups) ? result.groups : [])
        .filter((group) => group && group.group_id && Array.isArray(group.members))
        .map((group) => ({
          ...group,
          group_id: String(group.group_id),
          asset_type: String(group.asset_type || ""),
          members: group.members.filter(Boolean).map((member) => ({
            ...member,
            asset_id: String(member.asset_id || member.id || ""),
            title: member.title || member.name || member.asset_id || member.id || "未命名",
          })).filter((member) => member.asset_id),
          eligible_primary_asset_ids: (group.eligible_primary_asset_ids || []).map(String),
          edges: Array.isArray(group.edges) ? group.edges : [],
        }))
    },

    _draftKey(groupId) {
      return `${this._currentProjectId() || ""}:${this._scanTaskId || ""}:${groupId}`
    },

    _groupDraftFor(group) {
      const key = this._draftKey(group.group_id)
      if (this._groupDraft[key]) return this._groupDraft[key]
      const eligible = new Set(group.eligible_primary_asset_ids || [])
      const primaryId = eligible.has(String(group.recommended_primary_asset_id))
        ? String(group.recommended_primary_asset_id)
        : String(group.eligible_primary_asset_ids?.[0] || "")
      const operations = {}
      group.members.forEach((member) => {
        if (member.asset_id === primaryId) return
        const edge = this._edgeFor(group, member.asset_id, primaryId)
        const recommended = String(edge?.recommended_action || "")
        const safeDefault = edge?.allowed_actions?.includes(recommended)
          && recommended !== "needs_review"
          && group.risk_level !== "high"
        operations[member.asset_id] = {
          action: safeDefault ? recommended : "later",
          allowCanonicalMerge: false,
          allowCanonicalAlias: false,
          scenePreviewConfirmed: false,
          scenePreview: null,
        }
      })
      const draft = { primaryId, operations, onlyDifferences: true }
      if (this._groupResults[group.group_id]?.status !== "success") {
        this._groupDraft[key] = draft
      }
      return draft
    },

    _edgeFor(group, leftId, rightId) {
      return group.edges.find((edge) => {
        const ids = [String(edge.source_asset_id), String(edge.target_asset_id)]
        return ids.includes(String(leftId)) && ids.includes(String(rightId))
      }) || null
    },

    _groupReadiness(group) {
      if (this._groupResults[group.group_id]?.status === "success") {
        return { ready: false, status: "success", message: "已执行成功" }
      }
      if (this._groupResults[group.group_id]?.error_code === "stale_suggestion") {
        return { ready: false, status: "stale", message: "建议已过期，请重新扫描" }
      }
      const draft = this._groupDraftFor(group)
      if (!draft.primaryId || !(group.eligible_primary_asset_ids || []).includes(draft.primaryId)) {
        return { ready: false, status: "incomplete", message: "请选择合格主对象" }
      }
      for (const member of group.members) {
        if (member.asset_id === draft.primaryId) continue
        const operation = draft.operations[member.asset_id]
        const edge = this._edgeFor(group, member.asset_id, draft.primaryId)
        if (!operation || operation.action === "later" || !edge?.allowed_actions?.includes(operation.action)) {
          return { ready: false, status: "incomplete", message: "尚有成员未完成裁决" }
        }
        if (member.status === "canonical" && operation.action === "merge" && !operation.allowCanonicalMerge) {
          return { ready: false, status: "incomplete", message: "需确认已采用对象融合" }
        }
        if (member.status === "canonical" && operation.action === "alias_only" && !operation.allowCanonicalAlias) {
          return { ready: false, status: "incomplete", message: "需确认已采用对象别名化" }
        }
        if (group.asset_type === "scene" && operation.action === "merge" && !operation.scenePreviewConfirmed) {
          return { ready: false, status: "incomplete", message: "需预览并确认 Scene 影响" }
        }
      }
      return { ready: true, status: "ready", message: "已就绪" }
    },

    _renderGroupWorkbench(result, groups) {
      const active = groups.find((group) => group.group_id === this._activeGroupId) || groups[0]
      const queue = groups.map((group, index) => {
        const readiness = this._groupReadiness(group)
        const failed = this._groupResults[group.group_id]?.status === "failed"
        const state = failed && readiness.status !== "stale" ? "failed" : readiness.status
        const stateLabel = { incomplete: "未完成", ready: "已就绪", success: "执行成功", failed: "执行失败", stale: "建议已过期" }[state]
        return `
          <button type="button" class="smart-dedup-queue-item ${group.group_id === active.group_id ? "is-active" : ""} is-${esc(state)}" data-smart-dedup-group="${esc(group.group_id)}">
            <span class="smart-dedup-queue-index">${esc(index + 1)}</span>
            <span><strong>${esc(this._assetLabel(group.asset_type))}</strong><small>${esc(group.members.map((item) => item.title).join(" / "))}</small></span>
            <span class="smart-dedup-state">${esc(stateLabel)}</span>
          </button>
        `
      }).join("")
      return `
        <div class="smart-dedup-workbench">
          <header class="smart-dedup-summary">
            <span>已扫描 ${esc(result.total_assets_scanned || 0)} 个资产</span>
            <span>${esc(groups.length)} 个待裁决组</span>
            <span>各组独立提交与回滚</span>
          </header>
          <div class="smart-dedup-layout">
            <aside class="smart-dedup-queue" aria-label="重复组队列">${queue}</aside>
            <section class="smart-dedup-decision">${this._renderActiveGroup(active)}</section>
          </div>
        </div>
      `
    },

    _renderActiveGroup(group) {
      const draft = this._groupDraftFor(group)
      const result = this._groupResults[group.group_id]
      const locked = result?.status === "success"
      const readiness = this._groupReadiness(group)
      const primaryChoices = group.eligible_primary_asset_ids.map((id) => {
        const member = group.members.find((item) => item.asset_id === id)
        return `<label class="smart-dedup-primary-option"><input type="radio" name="smart-dedup-group-primary" value="${esc(id)}" data-smart-dedup-group-primary="${esc(id)}" ${draft.primaryId === id ? "checked" : ""} ${locked ? "disabled" : ""}/><span>${esc(member?.title || id)}</span><small>${esc(member?.status || "-")}</small></label>`
      }).join("")
      const operationCards = group.members
        .filter((member) => member.asset_id !== draft.primaryId)
        .map((member) => this._renderGroupOperation(group, member, draft, locked))
        .join("")
      const resultNotice = result ? `<div class="smart-dedup-result is-${esc(result.status)}"><strong>${result.status === "success" ? "执行成功" : (result.error_code === "stale_suggestion" ? "建议已过期" : "执行失败")}</strong>${result.error_code ? ` · ${esc(result.error_code)}` : ""}${result.message ? `<p>${esc(result.message)}</p>` : ""}</div>` : ""
      return `
        ${resultNotice}
        <div class="smart-dedup-decision-head">
          <div><span class="smart-dedup-kicker">${esc(this._assetLabel(group.asset_type))} · ${esc(group.presentation === "cluster" ? "重复组" : "重复对")}</span><h3>${esc(group.members.map((item) => item.title).join(" / "))}</h3></div>
          <span class="smart-dedup-readiness is-${esc(readiness.status)}">${esc(readiness.message)}</span>
        </div>
        ${group.risk_level === "high" ? '<div class="smart-dedup-risk">高风险命中：需要逐项确认，系统不会自动应用。</div>' : ""}
        <section class="smart-dedup-section"><h4>1. 选择主对象</h4><div class="smart-dedup-primary-grid">${primaryChoices}</div></section>
        <section class="smart-dedup-section">
          <div class="smart-dedup-section-title"><h4>2. 对比成员字段</h4><label><input type="checkbox" data-smart-dedup-diff ${draft.onlyDifferences ? "checked" : ""}/> 只看差异</label></div>
          ${this._renderComparison(group.members, draft.onlyDifferences)}
        </section>
        <section class="smart-dedup-section"><h4>3. 为每个非主成员选择动作</h4>${operationCards}</section>
      `
    },

    _renderComparison(members, onlyDifferences) {
      const ignored = new Set(["asset_id", "id", "asset_type", "entity_type", "workflow_id"])
      const fields = [...new Set(members.flatMap((member) => Object.keys(member)))].filter((key) => !ignored.has(key))
      const rows = fields.filter((field) => {
        if (!onlyDifferences) return true
        return new Set(members.map((member) => JSON.stringify(member[field] ?? null))).size > 1
      }).map((field) => `<tr><th>${esc(this._fieldLabel(field))}</th>${members.map((member) => `<td>${esc(this._displayValue(member[field]))}</td>`).join("")}</tr>`).join("")
      return `<div class="smart-dedup-compare-scroll"><table class="smart-dedup-compare"><thead><tr><th>字段</th>${members.map((member) => `<th>${esc(member.title)}</th>`).join("")}</tr></thead><tbody>${rows || '<tr><td colspan="99">没有可见差异</td></tr>'}</tbody></table></div>`
    },

    _renderGroupOperation(group, member, draft, locked) {
      const edge = this._edgeFor(group, member.asset_id, draft.primaryId)
      const operation = draft.operations[member.asset_id] || { action: "later" }
      const options = [{ value: "later", label: "稍后处理" }, ...(edge?.allowed_actions || []).map((action) => ({ value: action, label: this._actionLabel(action) }))]
      const evidence = (edge?.evidence_anchors || []).map((item) => item?.snippet || item?.reason || item?.source_type).filter(Boolean)
      const canonicalMerge = member.status === "canonical" && operation.action === "merge"
      const canonicalAlias = member.status === "canonical" && operation.action === "alias_only"
      const scenePreview = group.asset_type === "scene" && operation.action === "merge"
      return `
        <article class="smart-dedup-operation">
          <div class="smart-dedup-operation-head"><div><strong>${esc(member.title)}</strong><small>将处理到主对象</small></div><select class="form-select" data-smart-dedup-operation="${esc(member.asset_id)}" ${locked ? "disabled" : ""}>${options.map((item) => `<option value="${esc(item.value)}" ${operation.action === item.value ? "selected" : ""}>${esc(item.label)}</option>`).join("")}</select></div>
          <p class="smart-dedup-reason">${esc(edge?.reason || "系统未提供额外原因。")}</p>
          <div class="smart-dedup-impact">影响：${esc(this._impactText(operation.action, member, group.members.find((item) => item.asset_id === draft.primaryId)))}</div>
          ${canonicalMerge ? `<label class="smart-dedup-confirm"><input type="checkbox" data-smart-dedup-confirm-merge="${esc(member.asset_id)}" ${operation.allowCanonicalMerge ? "checked" : ""} ${locked ? "disabled" : ""}/> 我理解来源是已采用对象，融合后将进入历史态</label>` : ""}
          ${canonicalAlias ? `<label class="smart-dedup-confirm"><input type="checkbox" data-smart-dedup-confirm-alias="${esc(member.asset_id)}" ${operation.allowCanonicalAlias ? "checked" : ""} ${locked ? "disabled" : ""}/> 我理解来源是已采用对象，别名化后将进入历史态</label>` : ""}
          ${scenePreview ? `<div class="smart-dedup-scene-preview"><button type="button" class="btn btn-sm" data-smart-dedup-preview-scene="${esc(member.asset_id)}" ${locked ? "disabled" : ""}>${operation.scenePreview ? "刷新 Scene 影响预览" : "生成 Scene 影响预览"}</button>${operation.scenePreview ? `<pre>${esc(this._displayValue(operation.scenePreview))}</pre><label><input type="checkbox" data-smart-dedup-confirm-scene="${esc(member.asset_id)}" ${operation.scenePreviewConfirmed ? "checked" : ""}/> 我已核对当前预览</label>` : ""}</div>` : ""}
          <details><summary>匹配证据</summary><p>${esc(evidence.join(" / ") || "无可展开证据")}</p></details>
        </article>
      `
    },

    _bindGroupControls(groups) {
      document.querySelectorAll("[data-smart-dedup-group]").forEach((button) => button.addEventListener("click", () => {
        this._activeGroupId = button.getAttribute("data-smart-dedup-group")
        this._showGroupWorkbench()
      }))
      document.querySelectorAll("[data-smart-dedup-group-primary]").forEach((input) => input.addEventListener("change", () => {
        const group = groups.find((item) => item.group_id === this._activeGroupId)
        if (!group) return
        const selectedPrimaryId = input.getAttribute("data-smart-dedup-group-primary") || input.value
        if (!group.eligible_primary_asset_ids.includes(selectedPrimaryId)) return
        const key = this._draftKey(group.group_id)
        delete this._groupDraft[key]
        this._groupDraftFor({ ...group, recommended_primary_asset_id: selectedPrimaryId }).primaryId = selectedPrimaryId
        this._showGroupWorkbench({ preserveScroll: true })
      }))
      document.querySelector("[data-smart-dedup-diff]")?.addEventListener("change", (event) => {
        const group = groups.find((item) => item.group_id === this._activeGroupId)
        if (!group) return
        this._groupDraftFor(group).onlyDifferences = Boolean(event.target.checked)
        this._showGroupWorkbench({ preserveScroll: true })
      })
      document.querySelectorAll("[data-smart-dedup-operation]").forEach((select) => select.addEventListener("change", () => {
        const group = groups.find((item) => item.group_id === this._activeGroupId)
        if (!group) return
        const sourceId = select.getAttribute("data-smart-dedup-operation")
        const operation = this._groupDraftFor(group).operations[sourceId]
        operation.action = select.value
        operation.scenePreviewConfirmed = false
        operation.scenePreview = null
        this._showGroupWorkbench({ preserveScroll: true })
      }))
      const bindConfirm = (selector, field) => document.querySelectorAll(selector).forEach((input) => input.addEventListener("change", () => {
        const group = groups.find((item) => item.group_id === this._activeGroupId)
        const sourceId = input.getAttribute(selector.slice(1, -1))
        if (!group || !sourceId) return
        this._groupDraftFor(group).operations[sourceId][field] = Boolean(input.checked)
        this._showGroupWorkbench({ preserveScroll: true })
      }))
      bindConfirm("[data-smart-dedup-confirm-merge]", "allowCanonicalMerge")
      bindConfirm("[data-smart-dedup-confirm-alias]", "allowCanonicalAlias")
      bindConfirm("[data-smart-dedup-confirm-scene]", "scenePreviewConfirmed")
      document.querySelectorAll("[data-smart-dedup-preview-scene]").forEach((button) => button.addEventListener("click", async () => {
        const group = groups.find((item) => item.group_id === this._activeGroupId)
        if (!group) return
        const sourceId = button.getAttribute("data-smart-dedup-preview-scene")
        const operation = this._groupDraftFor(group).operations[sourceId]
        try {
          operation.scenePreview = await api.outline.previewSceneMerge(this._currentProjectId(), {
            target_scene_id: this._groupDraftFor(group).primaryId,
            source_scene_ids: [sourceId],
            confirmed: false,
          })
          operation.scenePreviewConfirmed = false
          this._showGroupWorkbench({ preserveScroll: true })
        } catch (error) {
          toast(`Scene 预览失败：${error.message}`, "error")
        }
      }))
    },

    _buildGroupPayload(group) {
      const draft = this._groupDraftFor(group)
      return {
        group_id: group.group_id,
        asset_type: group.asset_type,
        primary_asset_id: draft.primaryId,
        operations: group.members.filter((member) => member.asset_id !== draft.primaryId).map((member) => {
          const edge = this._edgeFor(group, member.asset_id, draft.primaryId)
          const sourceIsEdgeSource = String(edge.source_asset_id) === member.asset_id
          const operation = draft.operations[member.asset_id]
          return {
            source_asset_id: member.asset_id,
            action: operation.action,
            alias: member.title,
            expected_source_execution_fingerprint: sourceIsEdgeSource ? edge.source_execution_fingerprint : edge.target_execution_fingerprint,
            expected_target_execution_fingerprint: sourceIsEdgeSource ? edge.target_execution_fingerprint : edge.source_execution_fingerprint,
            allow_canonical_merge: Boolean(operation.allowCanonicalMerge),
            allow_canonical_alias: Boolean(operation.allowCanonicalAlias),
            scene_preview_confirmed: Boolean(operation.scenePreviewConfirmed),
          }
        }),
      }
    },

    async _applyReadyGroups(groups) {
      if (this._scanProjectId !== this._currentProjectId()) {
        this._closeModal()
        this._resetResult()
        toast("项目已切换，旧扫描裁决已清理", "warning")
        return
      }
      const ready = groups.filter((group) => this._groupReadiness(group).ready)
      if (!ready.length) {
        toast("请先完成至少一组裁决", "warning")
        return
      }
      try {
        const response = await api.projects.applySmartDedup(this._currentProjectId(), {
          confirmed: true,
          scan_task_id: this._scanTaskId,
          groups: ready.map((group) => this._buildGroupPayload(group)),
        })
        ;(response.group_results || []).forEach((item) => {
          this._groupResults[item.group_id] = item
          if (item.status === "success") {
            delete this._groupDraft[this._draftKey(item.group_id)]
          }
        })
        const succeeded = (response.group_results || []).filter((item) => item.status === "success").length
        if (succeeded) {
          api.clearCache()
          router.refresh()
        }
        if (groups.every((group) => this._groupResults[group.group_id]?.status === "success")) {
          this._progress = null
        }
        toast(`本次执行成功 ${succeeded} 组，失败 ${(response.group_results || []).length - succeeded} 组`, succeeded ? "success" : "warning")
        this._showGroupWorkbench()
      } catch (error) {
        toast(error.message || "执行失败", "error")
      }
    },

    _assetLabel(assetType) {
      return { world_entity: "世界对象", plot_thread: "剧情线", outline_arc: "篇章纲", scene: "Scene", foreshadowing_plan: "伏笔", reveal_plan: "揭示" }[assetType] || assetType || "资产"
    },

    _actionLabel(action) {
      return { merge: "融合内容并迁移引用", alias_only: "仅登记别名并迁移关系", deprecate_duplicate: "废弃重复项", keep_separate: "保持独立" }[action] || action
    },

    _impactText(action, source, target) {
      if (action === "later") return "不进入本次提交"
      if (action === "keep_separate") return "保存本资产对的当前指纹裁决，语义变化后会重新扫描"
      const references = Number(source?.relation_count || source?.reference_count || 0)
      if (action === "alias_only") return `来源进入历史态，迁移/去重 ${references} 条当前关系，不融合正文字段`
      if (action === "merge") return `保留「${target?.title || "主对象"}」，来源进入历史态，迁移相关引用`
      return "来源标记为重复历史项，主对象保留"
    },

    _fieldLabel(field) {
      return { title: "名称", status: "状态", summary: "概要", aliases: "别名", chapter_span: "章节范围", source: "来源", updated_at: "更新时间", relation_count: "关系数", details: "业务字段" }[field] || field
    },

    _displayValue(value) {
      if (value == null || value === "") return "-"
      if (typeof value === "object") return JSON.stringify(value, null, 2)
      return String(value)
    },

    _suggestions(result) {
      if (!result || typeof result !== "object") return []
      const raw = Array.isArray(result.suggestions) ? result.suggestions : []
      return raw
        .map((item) => this._normalizeSuggestion(item))
        .filter(Boolean)
    },

    _normalizeSuggestion(item) {
      if (!item || typeof item !== "object") return null
      const sourceId = item.source_asset_id || item.source_entity_id
      const targetId = item.target_asset_id || item.target_entity_id
      if (!sourceId || !targetId || sourceId === targetId) return null
      const evidence = Array.isArray(item.evidence_anchors)
        ? item.evidence_anchors.filter((anchor) => anchor && typeof anchor === "object")
        : []
      const normalized = {
        ...item,
        asset_type: item.asset_type || "world_entity",
        action: item.action || "needs_review",
        source_asset_id: String(sourceId),
        source_title: item.source_title || item.source_entity_name || String(sourceId),
        target_asset_id: String(targetId),
        target_title: item.target_title || item.target_entity_name || String(targetId),
        recommended_primary_asset_id: item.recommended_primary_asset_id
          || item.recommended_primary_entity_id
          || item.target_asset_id
          || item.target_entity_id,
        recommended_primary_title: item.recommended_primary_title
          || item.recommended_primary_entity_name
          || item.target_title
          || item.target_entity_name,
        evidence_anchors: evidence,
        requires_canonical_confirmation: Boolean(item.requires_canonical_confirmation),
        requires_manual_confirmation: Boolean(item.requires_manual_confirmation),
        risk_level: item.risk_level || null,
      }
      if (this._isHighRiskSuggestion(normalized)) {
        normalized.requires_manual_confirmation = true
        normalized.risk_level = normalized.risk_level || "high"
      }
      return normalized
    },

    _isHighRiskSuggestion(item) {
      if (!item || typeof item !== "object") return false
      if (item.risk_level === "high" || item.requires_manual_confirmation) return true
      const method = String(item.match_method || "").toLowerCase()
      const action = String(item.action || "")
      const sourceTitle = normalizeTitle(item.source_title)
      const targetTitle = normalizeTitle(item.target_title)
      return method.includes("alias")
        && ["merge", "alias_only"].includes(action)
        && sourceTitle
        && targetTitle
        && sourceTitle !== targetTitle
    },

    _renderSuggestionsBody(result, suggestions, page = 0) {
      const totalPages = Math.max(1, Math.ceil(suggestions.length / PAGE_SIZE))
      const currentPage = Math.max(0, Math.min(Number(page) || 0, totalPages - 1))
      const start = currentPage * PAGE_SIZE
      const visible = suggestions.slice(start, start + PAGE_SIZE)
      const rows = visible
        .map((item, offset) => this._renderSuggestion(item, start + offset))
        .join("")
      return `
        <div style="margin-bottom:12px;color:var(--text-dim);font-size:13px;">
          扫描 ${esc(result.total_assets_scanned || 0)} 个资产，
          发现 ${esc(result.suggestion_count || suggestions.length)} 条建议。
          第 ${esc(currentPage + 1)} / ${esc(totalPages)} 页。
        </div>
        <div style="display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:10px;">
          <span style="font-size:12px;color:var(--text-muted);">
            本页 ${esc(start + 1)}-${esc(Math.min(start + visible.length, suggestions.length))} / ${esc(suggestions.length)}
          </span>
          <span style="display:flex;gap:6px;">
            <button type="button" class="btn btn-sm" data-smart-dedup-page="prev" ${currentPage <= 0 ? "disabled" : ""}>上一页</button>
            <button type="button" class="btn btn-sm" data-smart-dedup-page="next" ${currentPage >= totalPages - 1 ? "disabled" : ""}>下一页</button>
          </span>
        </div>
        ${rows}
      `
    },

    _bindSuggestionControls(suggestions) {
      document.querySelectorAll("[data-smart-dedup-page]").forEach((button) => {
        button.addEventListener("click", () => {
          if (button.disabled) return
          this._captureDraft()
          const delta = button.getAttribute("data-smart-dedup-page") === "next" ? 1 : -1
          this._showSuggestions(this._suggestionPage + delta)
        })
      })
      const bindings = [
        ["[data-smart-dedup-primary-mode]", "change"],
        ["[data-smart-dedup-manual-primary]", "input"],
        ["[data-smart-dedup-index], [data-smart-dedup-canonical], [data-smart-dedup-canonical-alias]", "change"],
      ]
      bindings.forEach(([selector, eventName]) => {
        document.querySelectorAll(selector).forEach((input) => {
          input.addEventListener(eventName, () => this._captureDraft())
        })
      })
      this._mountManualPrimaryPickers(suggestions)
    },

    _renderSuggestion(item, index) {
      const actionLabel = {
        merge: "合并",
        alias_only: "登记别名",
        deprecate_duplicate: "废弃重复项",
        needs_review: "需要人工检查",
      }[item.action] || item.action || "需要人工检查"
      const assetLabel = {
        world_entity: "世界对象",
        plot_thread: "剧情线",
        outline_arc: "篇章纲",
        scene: "Scene",
        foreshadowing_plan: "伏笔",
        reveal_plan: "揭示",
      }[item.asset_type] || item.asset_type || "资产"
      const evidence = (item.evidence_anchors || [])
        .map((anchor) => anchor.snippet || anchor.reason || anchor.source_type || "")
        .filter(Boolean)
        .join(" / ")
      const draft = this._draftFor(index, item)
      const selected = draft.selected ? "checked" : ""
      const sourceTitle = item.source_title || item.source_asset_id || "左侧对象"
      const targetTitle = item.target_title || item.target_asset_id || "右侧对象"
      const recommended = this._recommendedPrimary(item)
      const primary = this._resolvePrimaryChoice(item, draft)
      const sourcePrimary = draft.primaryMode === "source" ? "checked" : ""
      const targetPrimary = draft.primaryMode === "target" ? "checked" : ""
      const manualPrimary = draft.primaryMode === "manual" ? "checked" : ""
      const manualChoice = item.asset_type === "world_entity" ? `
        <label style="display:block;font-size:12px;">
          <input type="radio" name="smart-dedup-primary-${esc(index)}" data-smart-dedup-primary-mode="${esc(index)}" value="manual" ${manualPrimary} />
          选择其他主体对象
        </label>
        <div data-smart-dedup-manual-picker="${esc(index)}" style="margin-top:4px;"></div>
        <input type="hidden" data-smart-dedup-manual-primary="${esc(index)}" value="${esc(draft.manualPrimaryId || "")}" />
      ` : ""
      const operationText = {
        merge: `保留「${primary.primaryTitle}」，合并「${primary.duplicateTitle}」`,
        alias_only: `登记为别名：将「${primary.duplicateTitle}」登记到「${primary.primaryTitle}」`,
        deprecate_duplicate: `废弃「${primary.duplicateTitle}」，关联到「${primary.primaryTitle}」`,
        needs_review: "仅标记需要人工检查，不会直接应用",
      }[item.action] || "需要人工检查后处理"
      const riskNotice = this._isHighRiskSuggestion(item) ? `
        <div style="margin-top:8px;padding:8px;border:1px solid var(--warning);border-radius:var(--radius-md);color:var(--warning);font-size:12px;">
          高风险别名命中：默认不选中。确认这确实是同一对象后再手动勾选应用。
        </div>
      ` : ""
      const canonicalField = item.action === "alias_only"
        ? "data-smart-dedup-canonical-alias"
        : "data-smart-dedup-canonical"
      const canonical = item.requires_canonical_confirmation ? `
        <label style="display:block;margin-top:6px;color:var(--warning);font-size:12px;">
          <input type="checkbox" ${canonicalField}="${esc(index)}" ${item.action === "alias_only" ? (draft.allowCanonicalAlias ? "checked" : "") : (draft.allowCanonicalMerge ? "checked" : "")} />
          ${item.action === "alias_only" ? "我理解这会将已采用来源改为主对象别名" : "我理解这会合并两个已采用对象"}
        </label>
      ` : ""
      return `
        <article style="border:1px solid var(--border);border-radius:var(--radius-md);padding:10px;margin-bottom:10px;" data-smart-dedup-card="${esc(index)}">
          <label style="display:flex;gap:8px;align-items:flex-start;">
            <input type="checkbox" data-smart-dedup-index="${esc(index)}" ${selected} />
            <span>
              <strong>${esc(assetLabel)} · ${esc(actionLabel)}：</strong>
              ${esc(item.source_title || item.source_asset_id)} → ${esc(item.target_title || item.target_asset_id)}
            </span>
          </label>
          <div style="color:var(--text-dim);font-size:12px;margin-top:4px;">
            置信度 ${esc(item.confidence ?? "-")} · ${esc(item.match_method || "-")}
          </div>
          <p style="margin:6px 0 0;">${esc(item.reason || "无说明")}</p>
          <div style="margin-top:8px;padding:8px;border:1px solid var(--border-light);border-radius:var(--radius-md);background:var(--bg-alt);">
            <div style="font-size:12px;color:var(--text-muted);margin-bottom:6px;">
              操作路径：${esc(operationText)}
            </div>
            <div style="font-size:12px;font-weight:600;margin-bottom:6px;">
              主体对象 <span style="font-weight:400;color:var(--accent);">推荐主体：${esc(recommended.title || recommended.id || "-")}</span>
            </div>
            <label style="display:block;font-size:12px;margin-bottom:4px;">
              <input type="radio" name="smart-dedup-primary-${esc(index)}" data-smart-dedup-primary-mode="${esc(index)}" value="target" ${targetPrimary} />
              保留右侧：${esc(targetTitle)}
            </label>
            <label style="display:block;font-size:12px;margin-bottom:4px;">
              <input type="radio" name="smart-dedup-primary-${esc(index)}" data-smart-dedup-primary-mode="${esc(index)}" value="source" ${sourcePrimary} />
              保留左侧：${esc(sourceTitle)}
            </label>
            ${manualChoice}
          </div>
          ${riskNotice}
          ${canonical}
          <details style="margin-top:6px;"><summary>证据</summary><p>${esc(evidence || "无")}</p></details>
        </article>
      `
    },

    _draftFor(index, item) {
      const existing = this._suggestionDraft[index] || {}
      const recommended = this._recommendedPrimary(item)
      let primaryMode = existing.primaryMode
      let manualPrimaryId = existing.manualPrimaryId || ""
      if (!primaryMode) {
        if (recommended.id && recommended.id === item.source_asset_id) {
          primaryMode = "source"
        } else if (item.asset_type === "world_entity" && recommended.id && recommended.id !== item.target_asset_id) {
          primaryMode = "manual"
          manualPrimaryId = recommended.id
        } else {
          primaryMode = "target"
        }
      }
      return {
        selected: existing.selected ?? (
          item.action !== "needs_review"
          && !this._isHighRiskSuggestion(item)
        ),
        primaryMode,
        manualPrimaryId,
        manualPrimaryLabel: existing.manualPrimaryLabel || recommended.title || "",
        allowCanonicalMerge: Boolean(existing.allowCanonicalMerge),
        allowCanonicalAlias: Boolean(existing.allowCanonicalAlias),
      }
    },

    _recommendedPrimary(item) {
      const id = item.recommended_primary_asset_id
        || item.recommended_target_asset_id
        || item.primary_asset_id
        || item.target_asset_id
      const title = item.recommended_primary_title
        || item.recommended_target_title
        || item.primary_title
        || (id === item.source_asset_id ? item.source_title : item.target_title)
      return { id, title }
    },

    _resolvePrimaryChoice(item, draft) {
      const source = {
        id: item.source_asset_id,
        title: item.source_title || item.source_asset_id,
      }
      const target = {
        id: item.target_asset_id,
        title: item.target_title || item.target_asset_id,
      }
      const [primary, duplicate] = draft.primaryMode === "source"
        ? [source, target]
        : [target, source]
      if (draft.primaryMode === "manual" && draft.manualPrimaryId) {
        primary.id = draft.manualPrimaryId
        primary.title = draft.manualPrimaryLabel || "所选主体对象"
      }
      return {
        primaryId: primary.id,
        primaryTitle: primary.title,
        duplicateId: duplicate.id,
        duplicateTitle: duplicate.title,
      }
    },

    _captureDraft() {
      if (typeof document === "undefined") return
      document.querySelectorAll("[data-smart-dedup-index]").forEach((input) => {
        const index = Number(input.getAttribute("data-smart-dedup-index"))
        if (!Number.isFinite(index)) return
        const primary = document.querySelector(`input[name="smart-dedup-primary-${index}"]:checked`)
        const manual = document.querySelector(`[data-smart-dedup-manual-primary="${index}"]`)
        const canonical = document.querySelector(`[data-smart-dedup-canonical="${index}"]`)
        const canonicalAlias = document.querySelector(`[data-smart-dedup-canonical-alias="${index}"]`)
        this._suggestionDraft[index] = {
          ...(this._suggestionDraft[index] || {}),
          selected: Boolean(input.checked),
          primaryMode: primary?.value || this._suggestionDraft[index]?.primaryMode,
          manualPrimaryId: manual?.value?.trim() || "",
          manualPrimaryLabel: this._suggestionDraft[index]?.manualPrimaryLabel || "",
          allowCanonicalMerge: Boolean(canonical?.checked),
          allowCanonicalAlias: Boolean(canonicalAlias?.checked),
        }
      })
    },

    _buildApplyItem(item, draft) {
      const primary = this._resolvePrimaryChoice(item, draft)
      if (!primary.primaryId || !primary.duplicateId) return null
      return {
        asset_type: item.asset_type,
        action: item.action,
        source_asset_id: primary.duplicateId,
        target_asset_id: primary.primaryId,
        alias: item.alias || primary.duplicateTitle,
        allow_canonical_merge: Boolean(draft.allowCanonicalMerge),
        allow_canonical_alias: Boolean(draft.allowCanonicalAlias),
      }
    },

    async _applySuggestions(suggestions) {
      if (this._scanProjectId && this._scanProjectId !== this._currentProjectId()) {
        this._closeModal()
        this._resetResult()
        toast("项目已切换，旧扫描建议已清理", "warning")
        return
      }
      this._captureDraft()
      const selected = suggestions
        .map((item, index) => ({
          index,
          item,
          draft: this._draftFor(index, item),
        }))
        .filter((entry) => entry.item)
        .filter((entry) => entry.draft.selected)
        .filter((entry) => ["merge", "alias_only", "deprecate_duplicate"].includes(entry.item.action))
      if (!selected.length) {
        toast("请选择可应用的建议", "warning")
        return
      }
      const payload = selected
        .map(({ item, draft }) => this._buildApplyItem(item, draft))
        .filter(Boolean)
      try {
        const applied = await api.projects.applySmartDedup(this._currentProjectId(), {
          confirmed: true,
          suggestions: payload,
        })
        this._closeModal()
        toast(`已应用 ${applied.applied || 0} 条智能去重建议`, "success")
        this._resetResult()
        api.clearCache()
        router.refresh()
      } catch (err) {
        toast(err.message || "应用失败", "error")
      }
    },
  }

  return manager
}

function normalizeTitle(value) {
  return String(value || "").trim().toLowerCase()
}
