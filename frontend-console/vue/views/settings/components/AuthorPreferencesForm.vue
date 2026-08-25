<script setup>
import SourceLabel from "./SourceLabel.vue"
import {
  EDITOR_FONT_OPTIONS,
  defaultFocusModeDisplayLabel,
  editorFontDisplayLabel,
  isResettableSource,
} from "../logic/authorPreferences.js"

/**
 * 作者偏好表单（全局默认 / 项目 Tab 共用）。
 * sourceMap 为空对象时不渲染来源标签与"恢复到全局默认"按钮（全局页场景）。
 */
const form = defineModel({ type: Object, required: true })

defineProps({
  sourceMap: { type: Object, default: () => ({}) },
  errors: { type: Object, default: () => ({}) },
})

const emit = defineEmits(["reset-field"])
</script>

<template>
  <div class="author-preferences-form">
    <div class="form-row">
      <div class="form-group">
        <label for="author-daily-goal">日更目标（字）</label>
        <input
          class="form-input"
          id="author-daily-goal"
          type="number"
          min="0"
          max="100000"
          v-model="form.daily_goal"
          placeholder="6000"
          :aria-invalid="Boolean(errors.daily_goal)"
          :aria-describedby="errors.daily_goal ? 'author-daily-goal-help author-daily-goal-error' : 'author-daily-goal-help'"
        />
        <p id="author-daily-goal-help" class="settings-field-help">留空表示不显示日更进度目标。</p>
        <p v-if="errors.daily_goal" id="author-daily-goal-error" class="form-error" role="alert">{{ errors.daily_goal }}</p>
        <div v-if="sourceMap.daily_goal" class="settings-field-source">
          <SourceLabel :source="sourceMap.daily_goal.source" :value="sourceMap.daily_goal.value" />
        </div>
        <button
          v-if="isResettableSource(sourceMap.daily_goal)"
          class="btn btn-sm btn-link field-reset"
          data-field="daily_goal"
          type="button"
          @click="emit('reset-field', 'daily_goal')"
        >恢复到全局默认</button>
      </div>
      <div class="form-group">
        <label for="author-editor-font">编辑器字体</label>
        <select class="form-select" id="author-editor-font" v-model="form.editor_font">
          <option v-for="font in EDITOR_FONT_OPTIONS" :key="font" :value="font">{{ editorFontDisplayLabel(font) }}</option>
        </select>
        <div v-if="sourceMap.editor_font" class="settings-field-source">
          <SourceLabel :source="sourceMap.editor_font.source" :value="editorFontDisplayLabel(sourceMap.editor_font.value)" />
        </div>
        <button
          v-if="isResettableSource(sourceMap.editor_font)"
          class="btn btn-sm btn-link field-reset"
          data-field="editor_font"
          type="button"
          @click="emit('reset-field', 'editor_font')"
        >恢复到全局默认</button>
      </div>
      <div class="form-group settings-form-group-checkbox">
        <label class="settings-field-label-text" for="author-default-focus">默认专注模式</label>
        <label class="settings-checkbox-label">
          <input id="author-default-focus" type="checkbox" v-model="form.default_focus_mode" />
          新建写作会话时自动进入
        </label>
        <div v-if="sourceMap.default_focus_mode" class="settings-field-source">
          <SourceLabel :source="sourceMap.default_focus_mode.source" :value="defaultFocusModeDisplayLabel(sourceMap.default_focus_mode.value)" />
        </div>
        <button
          v-if="isResettableSource(sourceMap.default_focus_mode)"
          class="btn btn-sm btn-link field-reset"
          data-field="default_focus_mode"
          type="button"
          @click="emit('reset-field', 'default_focus_mode')"
        >恢复到全局默认</button>
      </div>
    </div>
  </div>
</template>
