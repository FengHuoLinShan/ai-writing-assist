<template>
  <section class="object-dossier" aria-label="场景对象档案">
    <header class="object-dossier__header">
      <div>
        <p class="object-dossier__eyebrow">本场明确关联对象</p>
        <h3>对象档案</h3>
      </div>
      <button
        type="button"
        class="btn btn-sm btn-primary"
        :disabled="loadingEntities || loadingBrief || !selectedIds.length"
        @click="loadBrief"
      >
        {{ loadingBrief ? `读取第 ${currentBatch} / ${totalBatches} 批…` : `读取所选对象（${selectedIds.length}）` }}
      </button>
    </header>

    <p class="object-dossier__basis">
      简报只读取 Scene POV 与明确关联 ID。每次请求最多 16 个对象；更多对象会分批读取，不限制本场可选对象总数。
    </p>
    <p v-if="invalidReferenceCount" class="object-dossier__warning" role="status">
      有 {{ invalidReferenceCount }} 个 Scene 关联值不是有效对象 ID，已跳过并保留为未核对状态。
    </p>
    <p v-if="entityLoadError" class="object-dossier__error" role="alert">
      {{ entityLoadError }}
      <button type="button" class="btn btn-sm" :disabled="loadingEntities" @click="loadEntities">重新读取关联对象</button>
    </p>

    <div v-if="loadingEntities" class="object-dossier__empty" role="status">正在核对 Scene 关联对象…</div>
    <div v-else-if="!validReferences.length" class="object-dossier__empty">
      <p>当前 Scene 没有明确的 POV 或对象关联，暂时不能生成对象简报。</p>
      <div class="object-dossier__actions">
        <button type="button" class="btn btn-sm" @click="$emit('organize')">整理本场关联</button>
        <button type="button" class="btn btn-sm btn-ghost" @click="$emit('open-evidence')">打开查证资料</button>
      </div>
    </div>

    <template v-else>
      <div class="object-dossier__selection" aria-label="选择本场对象">
        <section v-for="group in choiceGroups" :key="group.key" class="object-dossier__type-group">
          <h4>{{ group.label }} <span>{{ group.items.length }}</span></h4>
          <label v-for="choice in group.items" :key="choice.id" class="object-dossier__choice">
            <input v-model="choice.selected" type="checkbox" :disabled="!choice.entity || loadingBrief">
            <span class="object-dossier__choice-main">
              <strong>{{ choice.entity?.name || choice.entity?.title || `对象 ${shortId(choice.id)}` }}</strong>
              <small>{{ choice.linkLabels.join("、") }} · {{ choice.entity ? typeLabel(choice.entity.entity_type) : "关联对象暂不可读" }}</small>
            </span>
            <button
              v-if="choice.entity"
              type="button"
              class="btn btn-sm btn-ghost"
              :disabled="loadingBrief"
              @click.prevent="$emit('open-object', choice.id)"
            >对象资料</button>
            <span v-else class="object-dossier__choice-error" :title="choice.error">不可读</span>
          </label>
        </section>
      </div>

      <label class="object-dossier__option">
        <input v-model="includePatterns" type="checkbox" :disabled="loadingBrief">
        <span>按需包含 Evolution 倾向（解释性参考，不是正史）</span>
      </label>
      <label v-if="includePatterns" class="object-dossier__option object-dossier__option--nested">
        <input v-model="onlyAdoptedPatterns" type="checkbox" :disabled="loadingBrief">
        <span>只看作者已采用的倾向</span>
      </label>

      <p v-if="briefError" class="object-dossier__error" role="alert">
        {{ briefError }}
        <button type="button" class="btn btn-sm" :disabled="loadingBrief" @click="loadBrief">重新读取所选对象</button>
      </p>
      <p v-if="loadingBrief" class="object-dossier__progress" role="status">
        正在读取第 {{ currentBatch }} / {{ totalBatches }} 批；已收到 {{ Object.keys(reports).length }} 个对象的结果。
      </p>

      <div v-if="responseCount" class="object-dossier__reports">
        <section v-for="group in reportGroups" :key="group.key" class="object-dossier__report-group">
          <h4>{{ group.label }}</h4>
          <article v-for="choice in group.items" :key="choice.id" class="object-dossier__card">
            <header class="object-dossier__card-header">
              <div>
                <h5>{{ choice.entity?.name || choice.entity?.title || `对象 ${shortId(choice.id)}` }}</h5>
                <p>{{ typeLabel(choice.entity?.entity_type) }} · {{ choice.linkLabels.join("、") }}</p>
              </div>
                <span class="object-dossier__coverage" :data-coverage='reportFor(choice.id)?.coverage || "unknown"'>
                {{ coverageLabel(reportFor(choice.id)?.coverage) }}
              </span>
            </header>

            <p v-if="reportFor(choice.id)?.error" class="object-dossier__error" role="alert">
              本批暂不可读：{{ reportFor(choice.id).error }}；这不表示对象没有档案。
            </p>
            <template v-else-if="reportFor(choice.id)">
              <div class="object-dossier__layers">
                <span v-for="layer in reportFor(choice.id).layers" :key="layer" class="object-dossier__layer">
                  {{ layerLabel(layer) }}已读取
                </span>
                <span v-for="layer in reportFor(choice.id).unknownLayers" :key="`unknown:${layer}`" class="object-dossier__layer object-dossier__layer--unknown">
                  {{ layerLabel(layer) }}未知
                </span>
              </div>
              <p v-if="reportFor(choice.id).omittedCount" class="object-dossier__warning" role="status">
                有 {{ reportFor(choice.id).omittedCount }} 项未纳入简报。
              </p>
              <ul v-if="reportFor(choice.id).omissions.length" class="object-dossier__omissions">
                <li v-for="(reason, index) in reportFor(choice.id).omissions" :key="index">{{ reason }}</li>
              </ul>

              <section class="object-dossier__layer-section" aria-label="World 稳定设定">
                <h6>稳定设定 <small>World</small></h6>
                <article v-for="item in reportFor(choice.id).worldItems" :key="item.revision_id || item.entry_id || item.field_key" class="object-dossier__entry">
                  <header>
                    <strong>{{ worldItemLabel(item) }}</strong>
                    <span v-if="item.visibility === 'secret'" class="object-dossier__secret">作者秘密</span>
                  </header>
                  <p>{{ item.content || displayValue(item.value) || "条目内容暂不可用" }}</p>
                  <div v-if="item.tags?.length" class="object-dossier__tags">
                    <span v-for="tag in item.tags" :key="tag">{{ tag }}</span>
                  </div>
                  <p v-if="item.validity" class="object-dossier__validity">{{ validityLabel(item.validity) }}</p>
                  <details v-if="item.source_refs?.length">
                    <summary>查看来源（{{ item.source_refs.length }}）</summary>
                    <ul><li v-for="(ref, index) in item.source_refs" :key="index">{{ sourceLabel(ref) }}</li></ul>
                  </details>
                </article>
                <p v-if="!reportFor(choice.id).worldItems.length" class="object-dossier__empty-layer">
                  {{ layerStateMessage(reportFor(choice.id), "world", "稳定设定") }}
                </p>
              </section>

              <section class="object-dossier__layer-section" aria-label="Story 本场时点状态">
                <h6>本场时点状态 <small>Story</small></h6>
                <article v-for="(item, index) in reportFor(choice.id).continuityItems" :key="`${item.checkpoint_id}:${item.dimension}:${item.field}:${index}`" class="object-dossier__entry">
                  <header>
                    <strong>{{ item.subject_label || item.dimension }} · {{ item.field }}</strong>
                    <span v-if="item.possibly_false" class="object-dossier__uncertain">可能不真实</span>
                  </header>
                  <p>{{ displayValue(item.value) }}</p>
                  <p class="object-dossier__meta">{{ layerName(item.layer) }} · {{ item.confidence || "置信度未知" }}<template v-if="item.occurred_at?.scene_index != null"> · 第 {{ item.occurred_at.scene_index }} 场</template></p>
                  <details v-if="item.source_refs?.length">
                    <summary>查看来源（{{ item.source_refs.length }}）</summary>
                    <ul><li v-for="(ref, refIndex) in item.source_refs" :key="refIndex">{{ sourceLabel(ref) }}</li></ul>
                  </details>
                </article>
                <p v-if="!reportFor(choice.id).continuityItems.length" class="object-dossier__empty-layer">
                  {{ layerStateMessage(reportFor(choice.id), "continuity", "本场时点状态") }}
                </p>
              </section>

              <section v-if="includePatterns" class="object-dossier__layer-section" aria-label="Evolution 解释性倾向">
                <h6>解释性倾向 <small>Evolution</small></h6>
                <p class="object-dossier__interpretation">以下内容来自演化台账，只是带证据的解释，不会自动成为正史。</p>
                <article v-for="item in reportFor(choice.id).patternItems" :key="item.revision_id || item.entry_id" class="object-dossier__entry">
                  <header><strong>{{ item.category || "行为倾向" }}</strong><span>{{ Math.round(Number(item.confidence || 0) * 100) }}% 置信度</span></header>
                  <p>{{ item.statement || "倾向内容暂不可用" }}</p>
                  <p v-if="item.conditions?.length" class="object-dossier__meta">条件：{{ item.conditions.join("；") }}</p>
                  <details v-if="item.evidence_refs?.length">
                    <summary>查看证据（{{ item.evidence_refs.length }}）</summary>
                    <ul><li v-for="(ref, refIndex) in item.evidence_refs" :key="refIndex">{{ sourceLabel(ref) }}</li></ul>
                  </details>
                </article>
                <p v-if="!reportFor(choice.id).patternItems.length" class="object-dossier__empty-layer">
                  {{ layerStateMessage(reportFor(choice.id), "evolution", "解释性倾向") }}
                </p>
              </section>
            </template>
            <div v-else class="object-dossier__empty-layer" role="status">尚未读取；选择对象后点击“读取所选对象”。</div>
          </article>
        </section>
      </div>
    </template>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from "vue"
import { getApi } from "../../../bridge/index.js"

const props = defineProps({
  projectId: { type: String, default: null },
  scene: { type: Object, default: null },
})
const references = computed(() => sceneReferences(props.scene))
const invalidReferenceCount = computed(() => references.value.filter((item) => !isUuid(item.id)).length)
const validReferences = computed(() => references.value.filter((item) => isUuid(item.id)))
const choices = ref([])
const reports = ref({})
const failedBatches = ref([])
const includePatterns = ref(false)
const onlyAdoptedPatterns = ref(false)
const loadingEntities = ref(false)
const loadingBrief = ref(false)
const entityLoadError = ref("")
const briefError = ref("")
const currentBatch = ref(0)
const totalBatches = ref(0)
let generation = 0
let controller = null

const selectedIds = computed(() => choices.value
  .filter((item) => item.entity && item.selected)
  .map((item) => item.id))
const choiceGroups = computed(() => groupChoices(choices.value))
const reportGroups = computed(() => groupChoices(choices.value.filter((item) => item.selected)))
const responseCount = computed(() => Object.keys(reports.value).length || failedBatches.value.length)

function current(token, projectId, sceneId) {
  return token === generation && projectId === props.projectId && sceneId === (props.scene?.id || null)
}

function resetScope() {
  controller?.abort()
  controller = new AbortController()
  generation += 1
  choices.value = []
  reports.value = {}
  failedBatches.value = []
  loadingEntities.value = false
  loadingBrief.value = false
  entityLoadError.value = ""
  briefError.value = ""
  currentBatch.value = 0
  totalBatches.value = 0
  return { token: generation, controller, projectId: props.projectId, sceneId: props.scene?.id || null }
}

async function loadEntities() {
  const scope = resetScope()
  const ids = references.value.filter((item) => isUuid(item.id))
  if (!scope.projectId || !scope.sceneId || !ids.length) return
  loadingEntities.value = true
  try {
    const results = await Promise.allSettled(ids.map((item) => getApi().world.getEntity(
      item.id, scope.projectId, { cache: "no-store", signal: scope.controller.signal },
    )))
    if (!current(scope.token, scope.projectId, scope.sceneId)) return
    choices.value = ids.map((reference, index) => {
      const result = results[index]
      return {
        ...reference,
        entity: result.status === "fulfilled" ? result.value : null,
        error: result.status === "rejected" ? result.reason?.message || "关联对象暂不可读" : "",
        selected: result.status === "fulfilled",
      }
    })
    if (results.every((item) => item.status === "rejected")) {
      entityLoadError.value = "所有本场关联对象暂时无法核对；这不代表没有对象档案。"
    } else if (results.some((item) => item.status === "rejected")) {
      entityLoadError.value = "部分本场关联对象暂时无法核对；已保留可读对象，失败对象没有被当作空档案。"
    }
  } catch (error) {
    if (current(scope.token, scope.projectId, scope.sceneId) && error?.name !== "AbortError") {
      entityLoadError.value = error?.message || "本场关联对象读取失败。"
    }
  } finally {
    if (current(scope.token, scope.projectId, scope.sceneId)) loadingEntities.value = false
  }
}

async function loadBrief() {
  if (loadingBrief.value || !selectedIds.value.length || !props.projectId || !props.scene?.id) return
  controller?.abort()
  controller = new AbortController()
  const token = ++generation
  const projectId = props.projectId
  const sceneId = props.scene.id
  const ids = [...selectedIds.value]
  const groups = chunks(ids, 16)
  reports.value = {}
  failedBatches.value = []
  briefError.value = ""
  currentBatch.value = 0
  totalBatches.value = groups.length
  loadingBrief.value = true
  try {
    for (let index = 0; index < groups.length; index += 1) {
      if (!current(token, projectId, sceneId)) return
      currentBatch.value = index + 1
      try {
        const result = await getApi().context.objectDossierBrief({
          novel_id: projectId,
          scene_id: sceneId,
          entity_ids: groups[index],
          reveal_mode: "author_full",
          content_mode: "canonical",
          include_patterns: includePatterns.value,
          only_adopted_patterns: includePatterns.value && onlyAdoptedPatterns.value,
        }, { signal: controller.signal })
        if (!current(token, projectId, sceneId)) return
        const next = { ...reports.value }
        for (const entityId of groups[index]) next[entityId] = projectReport(result, entityId)
        reports.value = next
      } catch (error) {
        if (!current(token, projectId, sceneId) || error?.name === "AbortError") return
        const failed = { index: index + 1, entityIds: groups[index], message: error?.message || "本批对象档案暂时无法读取" }
        failedBatches.value = [...failedBatches.value, failed]
        const next = { ...reports.value }
        for (const entityId of groups[index]) next[entityId] = { error: failed.message, coverage: "unknown" }
        reports.value = next
      }
    }
    if (current(token, projectId, sceneId) && failedBatches.value.length) {
      briefError.value = `${failedBatches.value.length} 批对象暂不可读；已成功批次的结果仍保留。`
    }
  } finally {
    if (current(token, projectId, sceneId)) loadingBrief.value = false
  }
}

function groupChoices(items) {
  const groups = new Map()
  for (const item of items) {
    const type = item.entity?.entity_type || "unavailable"
    if (!groups.has(type)) groups.set(type, { key: type, label: typeLabel(type), items: [] })
    groups.get(type).items.push(item)
  }
  return [...groups.values()].sort((left, right) => left.label.localeCompare(right.label))
}

function reportFor(entityId) { return reports.value[entityId] || null }
function layerStateMessage(report, layer, label) {
  if (!includePatterns.value && layer === "evolution") return "默认未读取 Evolution 倾向；可勾选后按需查看解释性参考。"
  if (!report?.layers?.includes(layer)) return `${label}尚未确认可读。`
  if (report.unknownLayers?.includes(layer)) return `${label}当前未知，不能据此判断没有记录。`
  return `本次读取没有返回${label}条目。`
}
function coverageLabel(value) { return ({ complete: "范围完整", partial: "部分省略", unknown: "范围未知" })[value] || "范围未知" }
function layerLabel(value) { return ({ world: "稳定设定", continuity: "时点状态", evolution: "演化倾向" })[value] || value }
function layerName(value) { return ({ fact: "事实", belief: "人物认知", observation: "观察" })[value] || value || "层级未知" }
function typeLabel(value) { return ({ character: "人物", location: "地点", item: "物件", faction: "势力", organization: "组织", rule: "规则", secret: "秘密" })[value] || value || "对象类型未知" }
function shortId(value) { return String(value || "").slice(0, 8) }
function displayValue(value) {
  if (value == null || value === "") return ""
  return typeof value === "string" ? value : JSON.stringify(value)
}
function worldItemLabel(item) {
  return item.facing_label || item.field_key || item.legacy_field_key
    || (item.kind === "legacy_profile_field" ? "旧档案字段" : "档案条目")
}
function validityLabel(validity) {
  const anchor = (value) => value ? `${value.kind === "scene" ? "Scene" : "章节"} ${shortId(value.id)}` : "全书"
  return `生效：${anchor(validity.start)} — ${anchor(validity.end)}`
}
function sourceLabel(value) {
  const location = value?.scene_index != null ? `第 ${value.scene_index} 场` : value?.chapter_index != null ? `第 ${value.chapter_index} 章` : "来源位置未记录"
  return [value?.label || value?.title || value?.kind || "证据来源", location, value?.note || value?.summary].filter(Boolean).join(" · ")
}

function sceneReferences(scene) {
  if (!scene) return []
  const refs = []
  const add = (value, label) => {
    if (Array.isArray(value)) {
      for (const id of value) refs.push({ id: String(id || ""), linkLabels: [label] })
    } else if (value) refs.push({ id: String(value), linkLabels: [label] })
  }
  add(scene.pov_character_id, "POV")
  const meta = scene.structure_meta && typeof scene.structure_meta === "object" ? scene.structure_meta : {}
  add(meta.related_entity_ids, "Scene 关联")
  add(meta.world_entity_ids, "World 关联")
  add(meta.item_ids, "物件关联")
  const grouped = new Map()
  for (const reference of refs) {
    const current = grouped.get(reference.id)
    if (current) current.linkLabels = [...new Set([...current.linkLabels, ...reference.linkLabels])]
    else grouped.set(reference.id, reference)
  }
  return [...grouped.values()]
}

function isUuid(value) {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(String(value || ""))
}

function chunks(items, size) {
  const result = []
  for (let index = 0; index < items.length; index += size) result.push(items.slice(index, index + size))
  return result
}

function projectReport(result, entityId) {
  const id = String(entityId)
  return {
    coverage: result?.coverage || "unknown",
    layers: result?.layers || [],
    unknownLayers: result?.unknown_layers || [],
    omittedCount: Number(result?.omitted_count || 0),
    omissions: result?.omissions || [],
    fingerprint: result?.fingerprint || null,
    worldItems: (result?.world_items || []).filter((item) => String(item.entity_id) === id),
    continuityItems: (result?.continuity_items || []).filter((item) => String(item.entity_id) === id),
    patternItems: (result?.pattern_items || []).filter((item) => (item.entity_ids || []).map(String).includes(id)),
  }
}

watch(() => [props.projectId, props.scene?.id || null, JSON.stringify(sceneReferences(props.scene))], loadEntities, { immediate: true })
onBeforeUnmount(() => { generation += 1; controller?.abort() })
</script>

<style scoped>
.object-dossier { display: grid; gap: 10px; min-width: 0; }
.object-dossier__header, .object-dossier__card-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; min-width: 0; }
.object-dossier__header h3, .object-dossier__card-header h5 { margin: 2px 0 0; }
.object-dossier__eyebrow { margin: 0; color: var(--text-secondary); font-size: 11px; letter-spacing: .04em; }
.object-dossier__basis, .object-dossier__progress, .object-dossier__meta, .object-dossier__empty-layer { margin: 0; color: var(--text-secondary); font-size: 12px; line-height: 1.55; }
.object-dossier__empty, .object-dossier__warning, .object-dossier__error { padding: 9px; border-radius: 8px; font-size: 12px; line-height: 1.55; overflow-wrap: anywhere; }
.object-dossier__empty { border: 1px dashed var(--border-color, var(--border)); color: var(--text-secondary); }
.object-dossier__warning { border-left: 3px solid var(--warning, #a66a00); background: var(--warning-soft, rgba(176, 132, 32, .08)); color: var(--text-primary); }
.object-dossier__error { border-left: 3px solid var(--danger, #b42318); background: var(--danger-soft, rgba(180, 35, 24, .06)); color: var(--text-primary); }
.object-dossier__error button { margin-left: 6px; }
.object-dossier__actions, .object-dossier__choice, .object-dossier__option { display: flex; align-items: center; gap: 8px; }
.object-dossier__selection, .object-dossier__reports { display: grid; gap: 9px; }
.object-dossier__type-group, .object-dossier__report-group { display: grid; gap: 6px; }
.object-dossier__type-group h4, .object-dossier__report-group h4 { margin: 4px 0 0; font-size: 12px; }
.object-dossier__type-group h4 span { color: var(--text-secondary); font-weight: 400; }
.object-dossier__choice { min-width: 0; padding: 7px 8px; border: 1px solid var(--border-color, var(--border)); border-radius: 7px; background: var(--bg-primary, var(--surface)); }
.object-dossier__choice-main { display: grid; flex: 1; min-width: 0; gap: 2px; }
.object-dossier__choice-main strong, .object-dossier__choice-main small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.object-dossier__choice-main strong { font-size: 12px; }
.object-dossier__choice-main small, .object-dossier__choice-error { color: var(--text-secondary); font-size: 11px; }
.object-dossier__choice-error, .object-dossier__coverage { flex: none; }
.object-dossier__option { color: var(--text-secondary); font-size: 12px; }
.object-dossier__option--nested { margin-left: 22px; }
.object-dossier__card { display: grid; gap: 9px; min-width: 0; padding: 10px; border: 1px solid var(--border-color, var(--border)); border-radius: 9px; background: var(--bg-primary, var(--surface)); }
.object-dossier__card-header h5 { font-size: 13px; overflow-wrap: anywhere; }
.object-dossier__card-header p { margin: 2px 0 0; color: var(--text-secondary); font-size: 11px; }
.object-dossier__coverage, .object-dossier__layer { padding: 3px 7px; border: 1px solid var(--border-color, var(--border)); border-radius: 999px; color: var(--text-secondary); font-size: 10px; white-space: nowrap; }
.object-dossier__coverage[data-coverage="unknown"], .object-dossier__layer--unknown { border-color: var(--warning, #a66a00); color: var(--warning, #8a5b00); }
.object-dossier__coverage[data-coverage="partial"] { border-color: var(--warning, #a66a00); }
.object-dossier__layers { display: flex; flex-wrap: wrap; gap: 5px; }
.object-dossier__layer-section { display: grid; gap: 6px; padding-top: 8px; border-top: 1px solid var(--border-color, var(--border)); }
.object-dossier__layer-section h6 { margin: 0; font-size: 12px; }
.object-dossier__layer-section h6 small { margin-left: 5px; color: var(--text-secondary); font-size: 10px; font-weight: 400; }
.object-dossier__entry { display: grid; gap: 5px; min-width: 0; padding-left: 8px; border-left: 2px solid var(--border-color, var(--border)); }
.object-dossier__entry header { display: flex; flex-wrap: wrap; align-items: baseline; justify-content: space-between; gap: 6px; font-size: 11px; }
.object-dossier__entry > p { margin: 0; overflow-wrap: anywhere; white-space: pre-wrap; font-size: 12px; line-height: 1.55; }
.object-dossier__secret { color: var(--danger, #a1362f); }
.object-dossier__uncertain { color: var(--warning, #8a5b00); }
.object-dossier__tags { display: flex; flex-wrap: wrap; gap: 4px; }
.object-dossier__tags span { padding: 2px 6px; border-radius: 999px; background: var(--bg-muted, #f4f2ee); color: var(--text-secondary); font-size: 10px; }
.object-dossier__validity, .object-dossier__meta { color: var(--text-secondary); font-size: 10px !important; }
.object-dossier__entry details { color: var(--text-secondary); font-size: 11px; }
.object-dossier__entry summary { cursor: pointer; }
.object-dossier__entry ul, .object-dossier__omissions { margin: 4px 0 0; padding-left: 17px; color: var(--text-secondary); font-size: 11px; }
.object-dossier__interpretation { margin: 0; color: var(--warning, #8a5b00); font-size: 11px; line-height: 1.5; }
@media (max-width: 520px) {
  .object-dossier__header { align-items: flex-start; }
  .object-dossier__header > button { max-width: 48%; white-space: normal; }
  .object-dossier__choice { flex-wrap: wrap; }
  .object-dossier__choice-main { flex-basis: calc(100% - 28px); }
}
</style>
