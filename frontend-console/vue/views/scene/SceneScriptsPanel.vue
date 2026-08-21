<template>
  <section id="scene-runtime-panel-script" class="scene-runtime-panel scene-scripts-panel" role="tabpanel" aria-labelledby="scene-runtime-tab-script">
    <header class="scene-runtime-panel__header">
      <div>
        <p class="scene-runtime-panel__eyebrow">剧本区</p>
        <h2>{{ scene?.title || "先选择一个场景" }}</h2>
        <p>这里是本场的可编辑剧本草稿。保存或提交前仍需作者确认，正式正文继续在写作页维护。</p>
      </div>
      <div class="scene-runtime-panel__actions">
        <span v-if="savedAt" class="scene-runtime-saved">草稿已保存</span>
        <button type="button" class="btn btn-sm" :disabled="saving || !scene" data-action="save-scene-script-draft" @click="$emit('save', { adopt: false })">{{ saving ? "保存中..." : "保存新版本" }}</button>
        <button type="button" class="btn btn-sm" :disabled="saving || !scene" data-action="adopt-scene-script-draft" @click="$emit('save', { adopt: true })">保存并采用</button>
        <button type="button" class="btn btn-sm" :disabled="scriptGenerating || !scene" data-action="generate-scene-script" @click="$emit('generate')">{{ scriptGenerating ? "生成中..." : "生成剧本建议" }}</button>
        <button type="button" class="btn btn-sm btn-primary" :disabled="!scene" data-action="open-scene-writing" @click="$emit('open-writing')">回到写作</button>
      </div>
    </header>

    <div v-if="!scene" class="scene-runtime-empty">
      <strong>请先从“管理”选择一个场景</strong>
      <p>选择场景后，这里的草稿会按作品和场景分别恢复。</p>
    </div>
    <template v-else>
      <div class="scene-script-files" aria-label="剧本文件">
        <label><span>当前剧本文件</span><select class="form-select" :value="activeScriptFileId || ''" @change="$emit('select-file', $event.target.value)"><option v-if="!scripts.length" value="">尚未建立文件</option><option v-for="file in scripts" :key="file.fileId" :value="file.fileId">{{ file.title }}{{ file.adoptedRevisionId ? " · 已采用" : "" }}</option></select></label>
        <label><span>新文件名称</span><input class="form-input" :value="newScriptTitle" placeholder="例如：审讯版本" @input="$emit('update-new-title', $event.target.value)" /></label>
        <button type="button" class="btn btn-sm" :disabled="saving || !newScriptTitle.trim()" data-action="create-scene-script-file" @click="$emit('new-file')">新建剧本文件</button>
      </div>
      <label class="scene-script-editor">
        <span>本场剧本草稿</span>
        <textarea
          class="form-textarea"
          rows="18"
          :value="draft"
          data-action="scene-script-draft-input"
          placeholder="先写下这一场的动作、对白和结果……"
          @input="$emit('update:draft', $event.target.value)"
        ></textarea>
      </label>
      <div class="scene-script-toolbar">
        <button type="button" class="btn btn-sm" data-action="validate-scene-script" @click="$emit('validate')">检查这一稿</button>
        <button v-if="activeScriptFileId" type="button" class="btn btn-sm" data-action="load-scene-script-history" @click="$emit('history')">版本历史</button>
        <button v-if="activeScript?.adoptedRevisionId" type="button" class="btn btn-sm" data-action="unadopt-scene-script" @click="$emit('unadopt')">撤销采用</button>
        <span class="scene-script-toolbar__hint">{{ draft.length }} / 200000 字符</span>
      </div>
      <section v-if="scriptPreview" class="scene-script-preview" aria-label="待确认剧本建议">
        <div class="scene-runtime-section__heading"><h3>待确认剧本建议</h3><span>不会自动替换剧本草稿</span></div>
        <p v-if="scriptPreview.plan">{{ scriptPreview.plan }}</p>
        <ol v-if="scriptPreview.beats?.length" class="scene-beat-list">
          <li v-for="beat in scriptPreview.beats" :key="beat.beat_id || beat.id"><strong>{{ beat.purpose || beat.title }}</strong><span>{{ beat.action }}<template v-if="beat.consequence"> → {{ beat.consequence }}</template></span></li>
        </ol>
        <button type="button" class="btn btn-sm btn-primary" data-action="apply-scene-script-preview" @click="$emit('apply-preview')">放入剧本草稿</button>
      </section>
      <section v-if="scriptHistory.length" class="scene-script-history" aria-label="剧本版本历史">
        <div class="scene-runtime-section__heading"><h3>版本历史</h3><span v-if="historyLoading">正在加载…</span></div>
        <article v-for="revision in scriptHistory" :key="revision.id" class="scene-script-history__item">
          <div><strong>v{{ revision.versionNumber }}</strong><span>{{ revision.isAdopted ? "当前采用" : revision.isCurrent ? "当前草稿" : "历史版本" }}</span></div>
          <button v-if="!revision.isAdopted" type="button" class="btn btn-sm" :data-action="`adopt-scene-script-version-${revision.versionNumber}`" @click="$emit('adopt-revision', revision)">{{ activeScript?.adoptedRevisionId ? "撤换采用" : "采用此版本" }}</button>
        </article>
      </section>
      <section v-if="findings.length" class="scene-script-findings" aria-label="剧本检查结果">
        <article v-for="(finding, index) in findings" :key="`${finding.level}-${index}`" :class="`scene-script-finding is-${finding.level}`"><strong>{{ findingLabel(finding.level) }}</strong><span>{{ finding.message }}</span></article>
      </section>
      <p v-else class="scene-runtime-note">检查结果会显示在这里；它不会自动替换你的草稿。</p>
    </template>
  </section>
</template>

<script setup>
import { computed } from "vue"

const props = defineProps({
  scene: { type: Object, default: null },
  draft: { type: String, default: "" },
  scripts: { type: Array, default: () => [] },
  activeScriptFileId: { type: String, default: null },
  newScriptTitle: { type: String, default: "" },
  scriptHistory: { type: Array, default: () => [] },
  scriptPreview: { type: Object, default: null },
  scriptGenerating: Boolean,
  historyLoading: Boolean,
  findings: { type: Array, default: () => [] },
  savedAt: { type: String, default: null },
  saving: Boolean,
})

const activeScript = computed(() => props.scripts.find((item) => item.fileId === props.activeScriptFileId) || props.scripts[0] || null)

defineEmits(["save", "open-writing", "update:draft", "validate", "generate", "apply-preview", "history", "adopt-revision", "unadopt", "select-file", "update-new-title", "new-file"])

function findingLabel(level) {
  return { error: "需要处理", warning: "建议确认", info: "提示" }[level] || "提示"
}
</script>
