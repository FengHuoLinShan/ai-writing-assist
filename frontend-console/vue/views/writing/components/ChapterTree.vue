<template>
  <div class="chapter-tree-shell" :class="{ 'is-collapsed': collapsed }">
    <button
      type="button"
      class="chapter-tree-collapse-handle"
      :aria-label="`${collapsed ? '展开' : '收起'}章节目录`"
      :aria-expanded="!collapsed"
      @click="$emit('toggle-collapse')"
    >
      <span>{{ collapsed ? '展' : '收' }}</span>
      <span>{{ collapsed ? '开' : '起' }}</span>
      <span aria-hidden="true">{{ collapsed ? '▶' : '◀' }}</span>
    </button>

    <div v-if="!collapsed" class="card chapter-tree-card">
      <div class="chapter-tree-header">
        <span class="chapter-tree-title">共 {{ chapterList.length }} 章</span>
      </div>

      <div v-if="loadError" class="empty-state writing-empty-icon--warning" role="alert">
        <p>章节列表加载失败</p>
        <p class="writing-empty-hint">{{ loadError }}</p>
      </div>
      <div v-else-if="chapterList.length === 0" class="empty-state">
        <p>尚无章节</p>
        <p class="writing-empty-hint">从下方新建第一章开始写作。</p>
      </div>
      <div v-else class="chapter-tree-list">
        <ChapterRow
          v-for="chapter in chapterList"
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

      <div class="chapter-tree-footer">
        <div class="chapter-tree-bulk-toggle">
          <button class="btn btn-sm btn-ghost" @click="manage = !manage">{{ manage ? '收起管理 ▴' : '管理 ▾' }}</button>
        </div>
        <div v-if="manage" class="row-actions chapter-tree-bulk-toolbar">
          <button class="btn btn-sm" :disabled="!chapterList.length" @click="toggleAll">{{ selectedBulk.size === chapterList.length ? '取消全选' : '全选当前章节' }}</button>
          <button class="btn btn-sm btn-danger" :disabled="!selectedBulk.size" @click="removeSelected">批量删除章节 ({{ selectedBulk.size }})</button>
          <span class="writing-empty-hint">只删除当前可见章节</span>
        </div>
        <button type="button" class="btn chapter-tree-create" aria-label="新建章节" @click="$emit('create')">＋ 新建章节</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { defineComponent, h, ref, watch } from "vue"

const props = defineProps({
  chapterList: { type: Array, default: () => [] },
  chapters: { type: Object, default: () => ({}) },
  selectedChapter: { type: Number, default: null },
  loadError: { type: String, default: null },
  collapsed: { type: Boolean, default: false },
})
const emit = defineEmits(["select", "create", "delete-selected", "toggle-collapse"])

const ChapterRow = defineComponent({
  props: { chapter: Number, meta: Object, selected: Boolean, manage: Boolean, bulkSelected: Boolean },
  emits: ["select", "toggle-bulk"],
  setup(rowProps, { emit: rowEmit }) {
    const title = () => rowProps.meta?.title || ""
    const chapterButton = () => h("button", {
      type: "button",
      class: ["chapter-row", { "chapter-row--active": rowProps.selected }],
      "aria-current": rowProps.selected ? "true" : undefined,
      "aria-label": `打开第 ${rowProps.chapter} 章${title() ? `：${title()}` : ""}，${Number(rowProps.meta?.word_count || 0)} 字`,
      onClick: () => rowEmit("select"),
    }, [
      h("div", { class: "chapter-row__status" }, [
        h("span", { class: ["chapter-status", `chapter-status--${rowProps.meta?.status === "published" ? "published" : "draft"}`] }),
      ]),
      h("div", { class: "chapter-row__info" }, [
        h("div", { class: "chapter-row__title" }, [
          h("span", { class: "chapter-number" }, `第 ${rowProps.chapter} 章`),
          title() ? h("span", { class: "chapter-title-text", title: title() }, title()) : null,
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
            onChange: () => rowEmit("toggle-bulk"),
          }),
          chapterButton(),
        ])
      : chapterButton()
  },
})

const manage = ref(false)
const selectedBulk = ref(new Set())

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
