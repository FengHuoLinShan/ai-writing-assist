<template>
  <div class="scene-cockpit" :class="{ 'is-collapsed': railCollapsed }" :data-scene-cockpit-project="projectId || ''">
    <div class="scene-cockpit__title">
      <button
        type="button"
        class="writing-rail-heading-toggle"
        :aria-label="`${railCollapsed ? '展开' : '收起'}本章资料`"
        :aria-expanded="!railCollapsed"
        @click="$emit('toggle-collapse')"
      >
        <span class="writing-rail-heading-label writing-rail-heading-label--copilot">本章资料</span>
        <span aria-hidden="true">{{ railCollapsed ? "‹" : "›" }}</span>
      </button>
      <button v-if="!railCollapsed && chapter" class="btn btn-sm scene-cockpit-organize" @click="$emit('organize')">整理</button>
    </div>

    <section v-if="!railCollapsed && chapter" class="scene-cockpit-switcher" aria-labelledby="scene-cockpit-switcher-title">
      <div class="scene-cockpit-switcher__head">
        <strong id="scene-cockpit-switcher-title">本章场景</strong>
        <button type="button" class="btn btn-sm btn-ghost" @click="openAssociate">＋ 关联场景</button>
      </div>
      <div v-if="scenes.length" class="scene-cockpit-switcher__list" role="list" aria-label="切换本章场景">
        <button
          v-for="item in scenes"
          :key="item.id"
          type="button"
          class="scene-cockpit-switcher__item"
          :class="{ active: item.id === scene?.id }"
          :aria-pressed="item.id === scene?.id"
          :title="item.title || '未命名场景'"
          @click="$emit('select-scene', item.id)"
        >
          <span>{{ item.title || '未命名场景' }}</span>
          <small v-if="sceneChapterCount(item) > 1">跨章</small>
        </button>
      </div>
      <p v-else class="scene-cockpit-switcher__empty">本章未关联场景</p>
    </section>

    <div v-if="!railCollapsed && !chapter" class="empty-state writing-scene-panel-empty">
      <p>请先从左侧选择章节，再查看对应场景、人物和设定。</p>
    </div>
    <div v-if="!railCollapsed && chapter && !scene" class="scene-cockpit-empty">关联场景后，可在这里查看本场摘要与统一提醒。</div>

    <template v-if="!railCollapsed && chapter && scene">
      <div class="cockpit-tabs" role="tablist" aria-label="本章资料">
        <button v-for="tab in tabs" :key="tab.key" class="cockpit-tab" :class="{ active: activeTab === tab.key }" role="tab" :aria-selected="activeTab === tab.key" @click="activeTab = tab.key">{{ tab.label }}</button>
      </div>
      <div class="cockpit-body">
        <section v-if="activeTab === 'main'" class="cockpit-panel" data-panel="main">
          <SceneLensSummary :scene="scene" :lens="lens" :project-id="projectId" @load="$emit('load-lens')" @start-trial="$emit('start-trial', $event)" />
        </section>

        <section v-else-if="activeTab === 'objects'" class="cockpit-panel" data-panel="objects">
          <ObjectDossierPanel
            :project-id="projectId"
            :scene="scene"
            @open-evidence="openEvidenceSearch"
            @open-object="$emit('open-world-object', $event)"
            @organize="$emit('organize')"
          />
        </section>

        <section v-else-if="activeTab === 'notices'" class="cockpit-panel" data-panel="notices">
          <UnifiedNoticesPanel
            :project-id="projectId"
            :scene-id="scene?.id || null"
            :chapter-index="Number(chapter)"
            :unsaved="unsaved"
            :read-only="readOnly"
            @open-notice="$emit('open-notice', $event)"
          />
        </section>

        <section v-else-if="activeTab === 'director'" class="cockpit-panel cockpit-panel--unavailable" data-panel="director">
          <h3>场景导演暂未开放</h3>
          <p>当前页面不会生成剧本或导演建议。需要调整场景结构时，可打开现有场景工作台。</p>
          <button type="button" class="btn btn-sm" @click="$emit('organize')">打开场景工作台</button>
        </section>
      </div>
      <FocusedEvidencePanel
        ref="focusedPanel"
        :key="projectId + ':' + chapter + ':' + scene.id"
        :project-id="projectId"
        consumer="writing"
        :scene-id="scene.id"
        :chapter-index="Number(chapter)"
        content-mode="working"
        :roots="focus.roots"
        :initial-name="focus.name"
        :selected-refs="evidenceRefs"
        select-label="加入本次写作资料"
        @select-source="$emit('pin-evidence', $event)"
        @clear-selection="$emit('clear-evidence')"
      />
    </template>

    <div v-if="associateOpen" ref="overlayRef" class="modal-overlay" @keydown="onKeydown" @focusin="onFocusin">
      <div ref="dialogRef" class="modal-content scene-associate-dialog" role="dialog" aria-modal="true" aria-labelledby="scene-associate-title" tabindex="-1">
        <div class="modal-header">
          <h3 id="scene-associate-title">关联场景</h3>
          <button type="button" class="btn-icon" aria-label="关闭" @click="requestClose">×</button>
        </div>
        <div class="modal-body">
          <form v-if="creating" class="scene-associate-create" @submit.prevent="submitNewScene">
            <label for="scene-associate-title-input">Scene 名称</label>
            <input id="scene-associate-title-input" v-model="newTitle" class="form-input" maxlength="255" required autofocus>
            <p v-if="createError" class="writing-form-error" role="alert">{{ createError }}</p>
            <div class="row-actions">
              <button type="button" class="btn btn-ghost" :disabled="createBusy" @click="creating = false">返回列表</button>
              <button type="submit" class="btn btn-primary" :disabled="createBusy">{{ createBusy ? '创建中…' : '创建并关联' }}</button>
            </div>
          </form>
          <template v-else>
            <label class="scene-associate-search" for="scene-associate-search">
              <span class="sr-only">搜索已有场景</span>
              <input id="scene-associate-search" v-model="search" class="form-input" type="search" placeholder="搜索已有场景…">
            </label>
            <div class="scene-associate-list" role="list">
              <div v-for="item in filteredScenes" :key="item.id" class="scene-associate-row" role="listitem">
                <span :title="item.title || '未命名场景'">{{ item.title || '未命名场景' }}</span>
                <button
                  v-if="!isAssociated(item)"
                  type="button"
                  class="btn-icon"
                  :disabled="rowBusy === item.id"
                  :aria-label="`关联 ${item.title || '未命名场景'}`"
                  @click="associate(item)"
                >{{ rowBusy === item.id ? '…' : '＋' }}</button>
                <span v-else class="scene-associate-check" :aria-label="`${item.title || '未命名场景'}已关联`">✓</span>
                <p v-if="rowErrors[item.id]" class="writing-form-error" role="alert">{{ rowErrors[item.id] }}</p>
              </div>
              <p v-if="!filteredScenes.length" class="cockpit-empty">没有匹配的场景</p>
            </div>
          </template>
        </div>
        <div v-if="!creating" class="modal-footer scene-associate-footer">
          <button type="button" class="btn" @click="startCreate">＋ 新建场景</button>
          <button type="button" class="btn" @click="openWorkbench">打开场景工作台</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, reactive, ref } from "vue"
import { useModalDialog } from "../../../composables/useModalDialog.js"
import SceneLensSummary from "./SceneLensSummary.vue"
import ObjectDossierPanel from "./ObjectDossierPanel.vue"
import UnifiedNoticesPanel from "./UnifiedNoticesPanel.vue"
import FocusedEvidencePanel from "../../../components/FocusedEvidencePanel.vue"

const props = defineProps({
  projectId: { type: String, default: null },
  chapter: { type: Number, default: null },
  scene: { type: Object, default: null },
  scenes: { type: Array, default: () => [] },
  allScenes: { type: Array, default: () => [] },
  associateScene: { type: Function, default: async () => null },
  createScene: { type: Function, default: async () => null },
  unsaved: { type: Boolean, default: false },
  readOnly: { type: Boolean, default: false },
  railCollapsed: { type: Boolean, default: false },
  lens: { type: Object, default: () => ({ loading: false, data: null, error: null }) },
  evidenceRefs: { type: Array, default: () => [] },
})
const emit = defineEmits(["organize", "toggle-collapse", "select-scene", "load-lens", "start-trial", "pin-evidence", "clear-evidence", "open-notice", "open-world-object"])

const tabs = [
  { key: "main", label: "本场" }, { key: "objects", label: "对象" },
  { key: "notices", label: "提醒" }, { key: "director", label: "导演" },
]
const activeTab = ref("main")
const focus = reactive({ name: "", roots: [] })
const focusedPanel = ref(null)
async function openEvidenceSearch() {
  focus.name = ""
  focus.roots = []
  await nextTick()
  await focusedPanel.value?.open()
}
const associateOpen = ref(false)
const creating = ref(false)
const search = ref("")
const newTitle = ref("")
const createBusy = ref(false)
const createError = ref("")
const rowBusy = ref(null)
const rowErrors = reactive({})

const sceneChapters = (item) => new Set([
  ...(item?.chapter_ids || []).map(Number),
  ...(item?.scene_chunks || []).map((chunk) => Number(chunk.chapter_index ?? chunk.chapter_id)),
].filter(Number.isInteger))
const sceneChapterCount = (item) => sceneChapters(item).size
const isAssociated = (item) => sceneChapters(item).has(Number(props.chapter))
const filteredScenes = computed(() => {
  const needle = search.value.trim().toLocaleLowerCase()
  return props.allScenes.filter((item) => !needle || String(item.title || "").toLocaleLowerCase().includes(needle))
})

function openAssociate() {
  search.value = ""
  creating.value = false
  associateOpen.value = true
}
function requestClose() { associateOpen.value = false }
function startCreate() {
  newTitle.value = ""
  createError.value = ""
  creating.value = true
}
async function associate(item) {
  if (rowBusy.value || isAssociated(item)) return
  rowBusy.value = item.id
  rowErrors[item.id] = ""
  try {
    await props.associateScene(item.id)
  } catch (error) {
    rowErrors[item.id] = error?.message || "关联失败，请重试"
  } finally {
    rowBusy.value = null
  }
}
async function submitNewScene() {
  const title = newTitle.value.trim()
  if (!title || title.length > 255 || createBusy.value) {
    createError.value = "名称需为 1–255 个字符"
    return
  }
  createBusy.value = true
  createError.value = ""
  try {
    await props.createScene(title)
    creating.value = false
    search.value = ""
  } catch (error) {
    createError.value = error?.message || "创建失败，请重试"
  } finally {
    createBusy.value = false
  }
}
function openWorkbench() {
  requestClose()
  emit("organize")
}
const { overlayRef, dialogRef, onKeydown, onFocusin } = useModalDialog({ isOpen: () => associateOpen.value, requestClose })

</script>
