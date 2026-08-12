<template>
  <div class="card chapter-tree-card" :class="{ 'is-collapsed': collapsed }">
    <div class="chapter-tree-header">
      <button
        type="button"
        class="chapter-tree-title writing-rail-heading-toggle"
        :aria-label="`${collapsed ? '展开' : '收起'}章节`"
        :aria-expanded="!collapsed"
        @click="$emit('toggle-collapse')"
      >
        <span class="writing-rail-heading-label">{{ collapsed ? "章节" : `章节 · 共 ${chapterList.length} 章` }}</span>
        <span aria-hidden="true">{{ collapsed ? "›" : "‹" }}</span>
      </button>
      <div v-if="!collapsed" class="chapter-tree-actions">
        <button type="button" class="btn btn-sm" title="上一章" aria-label="上一章" :disabled="!previousChapter" @click="$emit('select', previousChapter)">←</button>
        <button type="button" class="btn btn-sm" title="下一章" aria-label="下一章" :disabled="!nextChapter" @click="$emit('select', nextChapter)">→</button>
        <button class="btn btn-sm" @click="$emit('create')">+ 新章</button>
      </div>
    </div>

    <div v-if="!collapsed && loadError" class="empty-state writing-empty-icon--warning" role="alert">
      <p>章节列表加载失败</p>
      <p class="writing-empty-hint">{{ loadError }}</p>
    </div>
    <div v-else-if="!collapsed && chapterList.length === 0" class="empty-state">
      <p>尚无章节</p>
      <button class="btn btn-primary" @click="$emit('create')">创建第一章</button>
    </div>
    <div v-else-if="!collapsed" class="chapter-tree-list">
      <template v-for="group in groups" :key="group.id">
        <div v-if="group.scene" class="scene-tree-node">
          <div class="scene-tree-scene" :class="{ 'scene-tree-scene--current': group.scene.id === selectedSceneId }">
            <button
              type="button"
              class="scene-tree-toggle"
              :aria-label="`${expanded.has(group.id) ? '收起' : '展开'}场景“${group.scene.title || '未命名'}”的章节`"
              :aria-expanded="expanded.has(group.id)"
              :title="expanded.has(group.id) ? '折叠' : '展开'"
              @click="toggle(group.id)"
            >
              <span class="toggle-icon">{{ expanded.has(group.id) ? '▼' : '▶' }}</span>
            </button>
            <button
              type="button"
              class="scene-tree-label"
              :class="{ 'scene-tree-label--current': group.scene.id === selectedSceneId }"
              @click="$emit('select-scene', group.scene.id)"
            >{{ group.scene.title || '未命名' }}<template v-if="rangeLabel(group.scene)"> · {{ rangeLabel(group.scene) }}</template></button>
            <span class="scene-tree-count">({{ group.chapters.length }}章)</span>
          </div>
          <div v-show="expanded.has(group.id)" class="scene-tree-chapters">
            <ChapterRow
              v-for="chapter in group.chapters"
              :key="chapter"
              :chapter="chapter"
              :meta="chapters[chapter]"
              :selected="chapter === selectedChapter"
              :manage="manage"
              :bulk-selected="selectedBulk.has(chapter)"
              @select="$emit('select', chapter)"
              @toggle-bulk="toggleBulk(chapter)"
            />
          </div>
        </div>
        <template v-else>
          <ChapterRow
            v-for="chapter in group.chapters"
            :key="chapter"
            :chapter="chapter"
            :meta="chapters[chapter]"
            :selected="chapter === selectedChapter"
            :manage="manage"
            :bulk-selected="selectedBulk.has(chapter)"
            @select="$emit('select', chapter)"
            @toggle-bulk="toggleBulk(chapter)"
          />
        </template>
      </template>
    </div>
    <div v-if="!collapsed" class="chapter-tree-bulk-toggle">
      <button class="btn btn-sm btn-ghost" @click="manage = !manage">{{ manage ? '收起管理 ▴' : '管理 ▾' }}</button>
    </div>
    <div v-if="!collapsed && manage" class="row-actions chapter-tree-bulk-toolbar">
      <button class="btn btn-sm" :disabled="!chapterList.length" @click="toggleAll">{{ selectedBulk.size === chapterList.length ? '取消全选' : '全选当前章节' }}</button>
      <button class="btn btn-sm btn-danger" :disabled="!selectedBulk.size" @click="removeSelected">批量删除章节 ({{ selectedBulk.size }})</button>
      <span class="writing-empty-hint">只删除当前可见章节</span>
    </div>
  </div>
</template>

<script setup>
import { computed, defineComponent, h, ref, watch, watchEffect } from "vue"

const props = defineProps({
  chapterList: { type: Array, default: () => [] },
  chapters: { type: Object, default: () => ({}) },
  scenes: { type: Array, default: () => [] },
  selectedChapter: { type: Number, default: null },
  selectedSceneId: { type: String, default: null },
  loadError: { type: String, default: null },
  collapsed: { type: Boolean, default: false },
})
const emit = defineEmits(["select", "select-scene", "create", "delete-selected", "toggle-collapse"])

const ChapterRow = defineComponent({
  props: { chapter: Number, meta: Object, selected: Boolean, manage: Boolean, bulkSelected: Boolean },
  emits: ["select", "toggle-bulk"],
  setup(rowProps, { emit }) {
    const chapterButton = () => h("button", {
      type: "button",
      class: ["chapter-row", { "chapter-row--active": rowProps.selected }],
      "aria-current": rowProps.selected ? "true" : "false",
      "aria-label": `打开第 ${rowProps.chapter} 章${rowProps.meta?.title ? `：${rowProps.meta.title}` : ""}，${Number(rowProps.meta?.word_count || 0)} 字`,
      onClick: () => emit("select"),
    }, [
      h("div", { class: "chapter-row__status" }, [
        h("span", { class: ["chapter-status", `chapter-status--${rowProps.meta?.status === "published" ? "published" : "draft"}`] }),
      ]),
      h("div", { class: "chapter-row__info" }, [
        h("div", { class: "chapter-row__title" }, [
          h("span", { class: "chapter-number" }, `第 ${rowProps.chapter} 章`),
          rowProps.meta?.title ? h("span", { class: "chapter-title-text" }, rowProps.meta.title) : null,
        ]),
        h("div", { class: "chapter-row__meta" }, [
          h("span", { class: "chapter-wc" }, `${Number(rowProps.meta?.word_count || 0).toLocaleString()} 字`),
        ]),
      ]),
    ])
    return () => rowProps.manage
      ? h("div", { class: "chapter-tree-bulk-row" }, [
          h("input", {
            type: "checkbox",
            checked: rowProps.bulkSelected,
            "aria-label": `选择第 ${rowProps.chapter} 章`,
            onChange: () => emit("toggle-bulk"),
          }),
          chapterButton(),
        ])
      : chapterButton()
  },
})

const expanded = ref(new Set())
const initializedGroups = new Set()
const manage = ref(false)
const selectedBulk = ref(new Set())
const groups = computed(() => {
  if (!props.scenes.length) return [{ id: "all", scene: null, chapters: props.chapterList }]
  const assigned = new Set()
  const sceneGroups = props.scenes.map((scene) => {
    const chapters = (scene.chapter_ids || [])
      .map(Number)
      .filter((chapter) => props.chapterList.includes(chapter))
    chapters.forEach((chapter) => assigned.add(chapter))
    return { id: `scene:${scene.id}`, scene, chapters }
  }).filter((group) => group.chapters.length)
  const unassigned = props.chapterList.filter((chapter) => !assigned.has(chapter))
  return [...(unassigned.length ? [{ id: "unassigned", scene: null, chapters: unassigned }] : []), ...sceneGroups]
})

watchEffect(() => {
  for (const group of groups.value) {
    if (!initializedGroups.has(group.id)) {
      initializedGroups.add(group.id)
      if (group.chapters.length) expanded.value.add(group.id)
    }
    if (group.chapters.includes(props.selectedChapter) || group.scene?.id === props.selectedSceneId) {
      expanded.value.add(group.id)
    }
  }
})

function toggle(id) {
  const next = new Set(expanded.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  expanded.value = next
}

function rangeLabel(scene) {
  const labels = (scene?.scene_chunks || []).map((chunk) => {
    const chapter = Number(chunk.chapter_index ?? chunk.chapter_id)
    const start = Number(chunk.start_offset ?? chunk.start_pos)
    const end = Number(chunk.end_offset ?? chunk.end_pos)
    if (!Number.isInteger(chapter) || !Number.isFinite(start) || !Number.isFinite(end) || end <= start) return ""
    return `第 ${chapter} 章字符 ${Math.floor(start) + 1}–${Math.floor(end)}`
  }).filter(Boolean)
  return labels.slice(0, 2).join(" · ")
}

const currentIndex = computed(() => props.chapterList.indexOf(props.selectedChapter))
const previousChapter = computed(() => currentIndex.value > 0 ? props.chapterList[currentIndex.value - 1] : null)
const nextChapter = computed(() => currentIndex.value >= 0 && currentIndex.value < props.chapterList.length - 1 ? props.chapterList[currentIndex.value + 1] : null)

watch(() => props.chapterList, (chapters) => {
  const allowed = new Set(chapters)
  selectedBulk.value = new Set([...selectedBulk.value].filter((chapter) => allowed.has(chapter)))
}, { deep: true })

function toggleBulk(chapter) {
  const next = new Set(selectedBulk.value)
  if (next.has(chapter)) next.delete(chapter)
  else next.add(chapter)
  selectedBulk.value = next
}

function toggleAll() {
  selectedBulk.value = selectedBulk.value.size === props.chapterList.length
    ? new Set()
    : new Set(props.chapterList)
}

function removeSelected() {
  emit("delete-selected", [...selectedBulk.value])
}
</script>
