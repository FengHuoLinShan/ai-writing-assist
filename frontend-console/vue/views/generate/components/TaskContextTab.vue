<template>
  <div class="generate-task-workspace">
    <div class="generate-task-cards" role="group" aria-label="任务预设">
      <button v-for="(item, key) in TASK_PRESETS" :key="key" class="generate-task-card" :class="{ active: preset === key }" type="button" :aria-pressed="preset === key" :data-preset="key" data-action="select-task-preset" @click="$emit('select-preset', key)">
        <h4>{{ item.label }}</h4><p>{{ item.task || '填写自定义任务描述' }}</p>
      </button>
    </div>
    <div class="generate-task-form">
      <div class="card">
        <div class="card-title">任务参数</div>
        <div class="form-group"><label for="gen-task">任务描述 *</label><textarea id="gen-task" v-model="form.task" class="form-textarea" rows="2" placeholder="如：为旧档案缺页篇生成 10 章章节卡" /></div>
        <details class="gen-form-section generate-task-section"><summary>高级设置</summary>
          <div class="form-group"><label for="gen-scope">范围</label><select id="gen-scope" v-model="form.scope" class="form-select"><option v-for="item in SCOPE_OPTIONS" :key="item.value" :value="item.value">{{ item.label }}</option></select></div>
          <div class="form-group"><label>相关对象</label><ReferencePickerAdapter id="gen-entities-picker" v-model="form.entity_ids" :project-id="projectId" :sources="[entitySource]" mode="multiple" :max-items="20" placeholder="按名称搜索世界对象" /><input id="gen-entities" type="hidden" :value="form.entity_ids.join(',')" /></div>
          <div class="form-group"><label>相关人物</label><ReferencePickerAdapter id="gen-characters-picker" v-model="form.character_ids" :project-id="projectId" :sources="[characterSource]" mode="multiple" :max-items="20" placeholder="按姓名或别名搜索人物" /><input id="gen-characters" type="hidden" :value="form.character_ids.join(',')" /></div>
          <div class="form-group"><label for="gen-chapter">章节索引</label><input id="gen-chapter" v-model.number="form.chapter_index" class="form-input" type="number" min="1" placeholder="当前章节（可选）" @change="clearScene" /></div>
          <div class="form-group"><label>当前 Scene</label><ReferencePickerAdapter id="gen-scene-picker" v-model="sceneIds" :project-id="projectId" :sources="[sceneSource]" placeholder="按标题、目标或冲突搜索 Scene" /><input id="gen-scene" type="hidden" :value="form.scene_id || ''" /></div>
          <div class="form-group"><label for="gen-budget">上下文预算 (tokens)</label><input id="gen-budget" v-model.number="form.budget_tokens" class="form-input" type="number" min="0" max="1000000" aria-describedby="gen-budget-hint" /><p id="gen-budget-hint" class="generate-form-hint">0 表示不做应用层裁剪；由实际模型上下文窗口决定上限。</p></div>
          <div class="form-group"><label for="gen-reveal">揭示模式</label><select id="gen-reveal" v-model="form.reveal_mode" class="form-select" @change="syncReveal"><option v-for="item in REVEAL_OPTIONS" :key="item.value" :value="item.value">{{ item.label }}</option></select></div>
          <label class="generate-quality-toggle"><input id="gen-include-world-synopsis" v-model="form.include_world_synopsis" type="checkbox" :disabled="synopsisDisabled" /><span>在作者模式中加入世界观简介</span></label>
          <p id="gen-world-synopsis-visibility-hint" class="generate-form-hint" :hidden="!synopsisDisabled">读者/角色模式强制排除作者全知简介。</p>
          <div v-show="form.reveal_mode === 'character'" id="gen-viewpoint-character-group" class="form-group"><label>视角人物 *</label><ReferencePickerAdapter id="gen-viewpoint-character-picker" v-model="viewpointIds" :project-id="projectId" :sources="[characterSource]" placeholder="选择视角人物" /><input id="gen-viewpoint-character" type="hidden" :value="form.viewpoint_character_id || ''" /><p class="generate-form-hint">视角人物与“相关人物”独立选择，提交时仍使用稳定内部引用。</p></div>
        </details>
      </div>
      <div class="card generate-task-result">
        <div class="card-title generate-task-output-header"><span>输出</span><span><button class="btn btn-sm" data-action="copy-task-md" :disabled="!markdown" @click="$emit('copy-markdown')">复制</button><button class="btn btn-sm" data-action="export-task-md" :disabled="!markdown" @click="$emit('export-markdown')">导出</button></span></div>
        <div id="gen-task-output">
          <div v-if="pending" class="loading">编译中...</div>
          <p v-else-if="error" class="generate-error-text">{{ error }}</p>
          <ContextBundleView v-else-if="bundle" :bundle="bundle" />
          <p v-else class="generate-empty-copy">选择任务或填写描述后编译、预览上下文；此页签不会启动不存在的业务执行链路。</p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from "vue"
import { getApi } from "../../../bridge/index.js"
import { structureAssetDisplay, worldAssetDisplay } from "../../../../shared/assetDisplayState.js"
import { TASK_PRESETS, SCOPE_OPTIONS, REVEAL_OPTIONS } from "../logic/generateLogic.js"
import ReferencePickerAdapter from "./ReferencePickerAdapter.vue"
import ContextBundleView from "./ContextBundleView.vue"

const props = defineProps({ projectId: { type: String, required: true }, preset: { type: String, default: "custom" }, bundle: Object, markdown: String, pending: Boolean, error: String })
defineEmits(["select-preset", "copy-markdown", "export-markdown"])
const form = defineModel("form", { type: Object, required: true })
const api = getApi()

function entityItem(item, kind) {
  const display = worldAssetDisplay(item)
  return { kind, id: item?.entity_id || item?.id, label: item?.name || item?.title || "未命名对象", description: [item?.entity_type || (kind === "character" ? "人物" : "世界对象"), item?.summary || item?.description].filter(Boolean).join(" · "), status: display.label, unavailable: display.isHistory || Boolean(item?.unavailable) }
}
async function resolveEntities(ids, context, kind) {
  return Promise.all(ids.map(async (id) => { try { return entityItem(await api.world.getEntity(id, context.projectId), kind) } catch { return { kind, id, label: "不可用引用", unavailable: true } } }))
}
const entitySource = {
  kind: "entity", label: "世界对象",
  async search(query, { projectId, limit }) { const data = await api.world.listEntities({ novel_id: projectId, display_state: "active", q: query || undefined, skip: 0, limit }); return (data?.items || []).filter((item) => item.entity_type !== "character").map((item) => entityItem(item, "entity")) },
  resolve: (ids, context) => resolveEntities(ids, context, "entity"),
}
const characterSource = {
  kind: "character", label: "人物",
  async search(query, { projectId, limit }) { const data = await api.world.listEntities({ novel_id: projectId, display_state: "active", entity_type: "character", q: query || undefined, skip: 0, limit }); return (data?.items || []).map((item) => entityItem(item, "character")) },
  resolve: (ids, context) => resolveEntities(ids, context, "character"),
}
function sceneItem(scene) {
  const display = structureAssetDisplay(scene)
  return { kind: "scene", id: scene?.id, label: scene?.title || "未命名 Scene", description: [(scene?.chapter_ids || []).map((value) => `第 ${value} 章`).join("、"), scene?.goal || scene?.core_conflict].filter(Boolean).join(" · "), status: display.label, unavailable: display.isHistory || Boolean(scene?.unavailable) }
}
const sceneSource = {
  kind: "scene", label: "Scene",
  async search(query, { projectId, limit }) {
    const chapterIndex = Number(form.value.chapter_index || 0)
    const projectData = await api.outline.getSceneWorkbench(projectId, null, { q: query || undefined, view_mode: "normal", skip: 0, limit })
    const projectScenes = (projectData?.items || []).map((entry) => entry.scene || entry).filter((scene) => scene.status !== "deprecated")
    if (!chapterIndex) return projectScenes.map(sceneItem)
    const chapterData = await api.outline.listScenesByChapter(projectId, chapterIndex)
    const needle = String(query || "").toLowerCase()
    const chapterScenes = (Array.isArray(chapterData) ? chapterData : chapterData?.items || []).filter((scene) => scene.status !== "deprecated").filter((scene) => !needle || [scene.title, scene.goal, scene.core_conflict].some((value) => String(value || "").toLowerCase().includes(needle)))
    const preferred = new Set(chapterScenes.map((scene) => String(scene.id)))
    return [...chapterScenes, ...projectScenes.filter((scene) => !preferred.has(String(scene.id)))].slice(0, limit).map(sceneItem)
  },
  async resolve(ids, { projectId }) { return Promise.all(ids.map(async (id) => { try { return sceneItem(await api.outline.getScene(id, projectId)) } catch { return { kind: "scene", id, label: "不可用引用", unavailable: true } } })) },
}
const sceneIds = computed({ get: () => form.value.scene_id ? [form.value.scene_id] : [], set: (ids) => { form.value.scene_id = ids[0] || "" } })
const viewpointIds = computed({ get: () => form.value.viewpoint_character_id ? [form.value.viewpoint_character_id] : [], set: (ids) => { form.value.viewpoint_character_id = ids[0] || "" } })
const synopsisDisabled = computed(() => ["reader", "character"].includes(form.value.reveal_mode))
function clearScene() { form.value.scene_id = "" }
function syncReveal() { if (synopsisDisabled.value) form.value.include_world_synopsis = false; if (form.value.reveal_mode !== "character") form.value.viewpoint_character_id = "" }
</script>
