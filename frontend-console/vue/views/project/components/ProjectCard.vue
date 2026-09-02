<script setup>
import { computed } from "vue"
import {
  genreLabel,
  projectActivityTime,
  projectMonogram,
  projectName,
  projectStats,
  stageLabel,
} from "../logic/projectFilter.js"

/** 单个项目卡 — DOM 契约对齐 vanilla _renderProjectCards。 */
const props = defineProps({
  project: { type: Object, required: true },
  index: { type: Number, required: true },
  isCurrent: { type: Boolean, default: false },
  selected: { type: Boolean, default: false },
  manage: { type: Boolean, default: false },
})

const emit = defineEmits(["open", "toggle-select", "edit", "delete"])

const name = computed(() => projectName(props.project))
const isCanonical = computed(() => {
  const status = props.project.status || "active"
  return status === "active" || status === "canonical"
})
const created = computed(() => (
  props.project.created_at ? new Date(props.project.created_at).toLocaleDateString("zh-CN") : ""
))
const stats = computed(() => projectStats(props.project))
const activeTime = computed(() => projectActivityTime(props.project))
const stage = computed(() => (props.project.current_stage ? stageLabel(props.project.current_stage) : "创作进行中"))
const genre = computed(() => genreLabel(props.project.genre))
const monogram = computed(() => projectMonogram(props.project))
const description = computed(() => props.project.tone || props.project.description || "还没有写下作品简介，先从下一章继续。")

const cardClasses = computed(() => [
  "project-card",
  `project-card--variant-${props.index % 4}`,
  props.isCurrent ? "current" : "",
].filter(Boolean).join(" "))
</script>

<template>
  <article
    :class="cardClasses"
    :data-id="project.id"
    :aria-current="isCurrent ? 'true' : undefined"
  >
    <button
      type="button"
      class="project-card__open"
      data-action="open-project"
      :data-id="project.id"
      :aria-label="`打开作品：${name}`"
      @click="emit('open', project.id)"
    ></button>
    <div class="project-card__visual" aria-hidden="true">
      <span class="project-card__visual-code">作品 / {{ String(index + 1).padStart(2, "0") }}</span>
      <strong>{{ monogram }}</strong>
      <i class="project-card__visual-line"></i>
      <i class="project-card__visual-block"></i>
    </div>
    <div class="project-card__content">
      <div class="project-card__masthead">
        <div v-if="manage" class="project-card-selection" data-action="noop" @click.stop>
          <label class="selection-checkbox" :title="`选择 ${name}`">
            <input
              type="checkbox"
              data-action="bulk-toggle-one"
              data-scope="project-cards"
              :data-id="project.id"
              :checked="selected"
              @change="emit('toggle-select', project.id, $event.target.checked)"
            />
            <span class="sr-only">选择 {{ name }}</span>
          </label>
        </div>
        <div class="project-status">
          <span class="status-dot" :class="isCanonical ? 'canonical' : 'draft'"></span>
          <span>{{ isCanonical ? "进行中" : "已归档" }}</span>
        </div>
        <span v-if="isCurrent" class="project-current-badge">当前作品</span>
      </div>
      <div class="project-card__eyebrow">
        <span>{{ genre }}</span>
        <i aria-hidden="true"></i>
        <span>{{ stage }}</span>
      </div>
      <h2 class="project-title">{{ name }}</h2>
      <p class="project-desc">{{ description }}</p>
      <dl class="project-stats" aria-label="作品统计">
        <div :title="stats.wordCountTitle">
          <dt>字数</dt>
          <dd>{{ stats.wordCountText }}</dd>
        </div>
        <div :title="stats.chapterCountTitle">
          <dt>章节</dt>
          <dd>{{ stats.chapterCountText }}</dd>
        </div>
        <div :title="activeTime.full">
          <dt>最近更新</dt>
          <dd>{{ activeTime.relative }}</dd>
        </div>
      </dl>
      <div class="project-card__footer">
        <div class="project-meta">{{ created ? `创建于 ${created}` : "刚刚创建" }}</div>
        <div class="project-card__actions">
          <button class="btn btn-sm btn-primary" data-action="continue-writing" :data-id="project.id" @click.stop="emit('open', project.id)">继续写作</button>
          <button v-if="manage" class="btn btn-sm btn-ghost" data-action="edit-project" :data-id="project.id" @click.stop="emit('edit', project.id)">编辑</button>
          <button v-if="manage" class="btn btn-sm btn-danger" data-action="delete-project" :data-id="project.id" @click.stop="emit('delete', project.id)">删除</button>
        </div>
      </div>
    </div>
  </article>
</template>
