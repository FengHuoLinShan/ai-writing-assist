<template>
  <div class="generate-task-workspace">
    <div class="generate-task-main">
      <form class="card generate-task-parameter-card" @submit.prevent="$emit('run-task')">
        <div><h3 class="card-title">整理任务参考资料</h3><p class="generate-task-intro">只整理参考资料，不会修改正文或设定。</p></div>
        <div class="form-group">
          <label for="gen-task-preset">常用任务（可选）</label>
          <select id="gen-task-preset" class="form-select" :value="preset" aria-describedby="gen-task-preset-hint" data-action="select-task-preset" @change="$emit('select-preset', $event.target.value)">
            <option v-for="(item, key) in TASK_PRESETS" :key="key" :value="key">{{ item.label }}</option>
          </select>
          <p id="gen-task-preset-hint" class="generate-form-hint">选择后会填入下方任务，你仍可以继续改写。</p>
        </div>
        <div class="form-group"><label for="gen-task">想完成什么 *</label><textarea id="gen-task" v-model="form.task" class="form-textarea" rows="3" required aria-describedby="gen-task-hint" placeholder="如：为旧档案缺页篇整理 10 章章节卡所需资料"></textarea><p id="gen-task-hint" class="generate-form-hint">写清目标即可，范围和人物等条件可以在下方补充。</p></div>
        <details class="gen-form-section generate-task-section"><summary><span>更多条件</span><small>范围、视角和参考对象</small></summary>
          <div class="form-group"><label for="gen-scope">参考范围</label><select id="gen-scope" v-model="form.scope" class="form-select"><option v-for="item in SCOPE_OPTIONS" :key="item.value" :value="item.value">{{ item.label }}</option></select></div>
          <div class="form-group"><label>重点参考的世界对象</label><ReferencePickerAdapter id="gen-entities-picker" v-model="form.entity_ids" :project-id="projectId" :sources="[entitySource]" mode="multiple" :max-items="20" placeholder="按名称搜索世界对象" /><input id="gen-entities" type="hidden" :value="form.entity_ids.join(',')" /></div>
          <div class="form-group"><label>重点参考的人物</label><ReferencePickerAdapter id="gen-characters-picker" v-model="form.character_ids" :project-id="projectId" :sources="[characterSource]" mode="multiple" :max-items="20" placeholder="按姓名或别名搜索人物" /><input id="gen-characters" type="hidden" :value="form.character_ids.join(',')" /></div>
          <div class="form-group"><label for="gen-chapter">当前章节</label><input id="gen-chapter" v-model.number="form.chapter_index" class="form-input" type="number" min="1" placeholder="选填，如 12" @change="clearScene" /></div>
          <div class="form-group"><label>当前场景</label><ReferencePickerAdapter id="gen-scene-picker" v-model="sceneIds" :project-id="projectId" :sources="[sceneSource]" placeholder="按标题、目标或冲突搜索场景" /><input id="gen-scene" type="hidden" :value="form.scene_id || ''" /></div>
          <div class="form-group"><label for="gen-budget">资料长度上限</label><input id="gen-budget" v-model.number="form.budget_tokens" class="form-input" type="number" min="0" max="1000000" aria-describedby="gen-budget-hint" /><p id="gen-budget-hint" class="generate-form-hint">留为 0 时自动适配当前模型；只有资料过长时才需要限制。</p></div>
          <div class="form-group"><label for="gen-reveal">可参考的信息</label><select id="gen-reveal" v-model="form.reveal_mode" class="form-select" @change="syncReveal"><option v-for="item in REVEAL_OPTIONS" :key="item.value" :value="item.value">{{ item.label }}</option></select></div>
          <label class="generate-quality-toggle"><input id="gen-include-world-synopsis" v-model="form.include_world_synopsis" type="checkbox" :disabled="synopsisDisabled" /><span>在作者模式中加入世界观简介</span></label>
          <p id="gen-world-synopsis-visibility-hint" class="generate-form-hint" :hidden="!synopsisDisabled">读者或角色视角不会包含作者才知道的简介。</p>
          <div v-show="form.reveal_mode === 'character'" id="gen-viewpoint-character-group" class="form-group"><label>从谁的视角判断 *</label><ReferencePickerAdapter id="gen-viewpoint-character-picker" v-model="viewpointIds" :project-id="projectId" :sources="[characterSource]" placeholder="选择视角人物" /><input id="gen-viewpoint-character" type="hidden" :value="form.viewpoint_character_id || ''" /><p class="generate-form-hint">这里只限制角色知道什么，不会改变上面的重点参考人物。</p></div>
        </details>
        <div class="generate-task-submit"><button class="btn btn-primary" type="submit" data-action="run-task" :disabled="pending">{{ pending ? '正在整理…' : '整理参考资料' }}</button><span>结果会显示在右侧并保留在当前任务中。</span></div>
      </form>

      <section class="card generate-task-result" aria-labelledby="generate-task-result-title">
        <div class="generate-task-output-header"><div><h3 id="generate-task-result-title" class="card-title">本次参考资料</h3><p>确认资料是否足够，再带入下一步工作。</p></div>
          <div v-if="bundle" class="generate-task-output-actions">
            <button class="btn btn-sm btn-primary" type="button" data-action="render-task-md" :disabled="pending || !form.task" @click="$emit('render-markdown')">查看完整资料</button>
            <button class="btn btn-sm" type="button" data-action="apply-to-chat" :disabled="pending || !form.task" @click="$emit('apply-to-chat')">带到世界设定对话</button>
          </div>
        </div>
        <div id="gen-task-output" :aria-busy="pending ? 'true' : undefined">
          <div v-if="pending" class="loading-skeleton generate-task-loading" role="status" aria-live="polite"><p>{{ pendingLabel }}</p><div class="skeleton loading-skeleton__heading" aria-hidden="true"></div><div class="skeleton loading-skeleton__line" aria-hidden="true"></div><div class="skeleton loading-skeleton__line loading-skeleton__line--medium" aria-hidden="true"></div></div>
          <template v-else>
            <div v-if="error" ref="errorEl" class="error-card generate-task-error" role="alert" tabindex="-1"><strong>{{ errorAction === 'render' ? '暂时没能准备完整资料' : '暂时没能整理完成' }}</strong><p>{{ error }}</p><button class="btn btn-sm" type="button" data-action="retry-task-context" @click="retry">重试</button></div>
            <ContextBundleView v-if="bundle" :bundle="bundle" />
            <div v-else-if="!error" class="generate-task-empty"><strong>还没有整理结果</strong><p>填写任务后，这里会汇集相关设定、人物和章节资料；不会自动改动作品。</p></div>
          </template>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, ref, watch } from "vue"
import { getApi } from "../../../bridge/index.js"
import { structureAssetDisplay, worldAssetDisplay } from "../../../../shared/assetDisplayState.js"
import { TASK_PRESETS, SCOPE_OPTIONS, REVEAL_OPTIONS } from "../logic/generateLogic.js"
import ReferencePickerAdapter from "./ReferencePickerAdapter.vue"
import ContextBundleView from "./ContextBundleView.vue"

const props = defineProps({ projectId: { type: String, required: true }, preset: { type: String, default: "custom" }, bundle: Object, pending: Boolean, pendingLabel: { type: String, default: "正在整理与任务有关的资料…" }, error: String, errorAction: { type: String, default: "compile" } })
const emit = defineEmits(["select-preset", "run-task", "render-markdown", "apply-to-chat"])
const form = defineModel("form", { type: Object, required: true })
const api = getApi()
const errorEl = ref(null)
watch(() => props.error, async (error) => { if (error) { await nextTick(); errorEl.value?.focus() } })
function retry() { emit(props.errorAction === "render" ? "render-markdown" : "run-task") }

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
