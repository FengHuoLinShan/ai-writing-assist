<template>
  <div class="generate-pov-workspace">
    <div class="card generate-pov-form">
      <div v-if="warning" class="generate-template-warning">{{ warning }}</div>
      <div class="generate-form-grid">
        <label>章节 *<select id="generate-pov-chapter" :value="form.chapterIndex || ''" class="form-select" @change="$emit('change-chapter', $event.target.value)"><option value="">请选择章节</option><option v-for="chapter in chapters" :key="chapter.chapter_index" :value="chapter.chapter_index">第 {{ chapter.chapter_index }} 章{{ chapter.title ? ` · ${chapter.title}` : '' }}</option></select></label>
        <label>Scene *<select id="generate-pov-scene" :value="form.sceneId" class="form-select" :disabled="!form.chapterIndex" @change="$emit('change-scene', $event.target.value)"><option value="">请选择 Scene</option><option v-for="scene in scenes" :key="scene.id" :value="scene.id">{{ scene.title || scene.name || scene.id }}</option></select></label>
        <label>视角角色 *<select id="generate-pov-character" v-model="form.viewpointCharacterId" class="form-select"><option value="">请选择角色</option><option v-for="character in characters" :key="characterId(character)" :value="characterId(character)">{{ character.name || character.display_name || characterId(character) }}</option></select></label>
      </div>
      <div v-if="manualRole" class="generate-pov-note">本次使用手动选择角色，不修改 Scene POV 设置。</div>
      <div v-if="sceneWithoutPov" class="generate-pov-note">当前 Scene 未设置 POV 角色，请手动选择本次生成角色。</div>
      <div class="generate-pov-note">世界观简介在角色视角模式中强制禁用；本次继续使用逐事实可见性过滤链。</div>
      <label>作者指令<textarea id="generate-pov-instruction" v-model="form.instruction" class="form-textarea" rows="5" placeholder="作为作者意图输入，不等于角色知识。" /></label>
      <p class="generate-empty-copy">生成结果先保存为正文建议；采用到工作稿后才能继续编辑和发布。结构化 POV 面板会展示泄漏诊断。</p>
    </div>
    <div class="card">
      <div class="card-title">结果</div>
      <div id="generate-pov-result" class="generate-result">
        <div v-if="pending" class="loading">{{ progressText }}</div>
        <p v-else-if="error" class="generate-error-text">生成失败：{{ error }}</p>
        <div v-else-if="submission" class="generate-result-card">
          <div class="generate-result-title">角色视角正文建议已生成</div>
          <div class="generate-result-meta">第 {{ submission.chapterIndex }} 章 · {{ selectedScene?.title || selectedScene?.name || submission.sceneId }} · {{ selectedRole?.name || selectedRole?.display_name || submission.viewpointCharacterId }}</div>
          <p class="generate-result-summary">{{ resultId ? `任务 / 建议：${resultId}` : '正文建议已生成，可到写作页采用到工作稿。' }}</p>
          <div class="generate-result-actions"><button class="btn btn-sm btn-primary" data-action="open-generated-destination" @click="$emit('open-result', submission)">打开并审阅建议</button></div>
        </div>
        <p v-else class="generate-empty-copy">选择章节、Scene 和视角角色后生成正文建议。</p>
      </div>
      <div v-if="selectedScene || selectedRole || form.chapterIndex" class="generate-pov-summary">
        <div>章节：{{ form.chapterIndex ? `第 ${form.chapterIndex} 章${chapterTitle ? ` · ${chapterTitle}` : ''}` : '未选择' }}</div>
        <div>Scene：{{ selectedScene?.title || selectedScene?.name || selectedScene?.id || '未选择' }}</div>
        <div>角色：{{ selectedRole?.name || selectedRole?.display_name || (selectedRole ? characterId(selectedRole) : '未选择') }}</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from "vue"
import { characterId } from "../logic/generateLogic.js"
const props = defineProps({ chapters: { type: Array, default: () => [] }, scenes: { type: Array, default: () => [] }, characters: { type: Array, default: () => [] }, warning: String, submission: Object, pending: Boolean, progress: Number, error: String })
defineEmits(["change-chapter", "change-scene", "open-result"])
const form = defineModel("form", { type: Object, required: true })
const selectedScene = computed(() => props.scenes.find((item) => item.id === form.value.sceneId) || null)
const selectedRole = computed(() => props.characters.find((item) => characterId(item) === form.value.viewpointCharacterId) || null)
const chapterTitle = computed(() => props.chapters.find((item) => Number(item.chapter_index) === Number(form.value.chapterIndex))?.title || "")
const manualRole = computed(() => Boolean(form.value.viewpointCharacterId && selectedScene.value?.pov_character_id && form.value.viewpointCharacterId !== selectedScene.value.pov_character_id))
const sceneWithoutPov = computed(() => Boolean(selectedScene.value && !selectedScene.value.pov_character_id))
const resultId = computed(() => props.submission?.result?.draft_id || props.submission?.result?.draft?.id || props.submission?.result?.id || props.submission?.result?.task_id || "")
const progressText = computed(() => props.progress == null ? "正在确认参考资料..." : `正在生成正文建议... ${Math.max(0, Math.min(100, Math.round(props.progress * 100)))}%`)
</script>
