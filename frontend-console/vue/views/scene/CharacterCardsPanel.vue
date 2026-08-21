<template>
  <section id="scene-runtime-panel-characters" class="scene-runtime-panel scene-character-cards-panel" role="tabpanel" aria-labelledby="scene-runtime-tab-characters">
    <header class="scene-runtime-panel__header">
      <div>
        <p class="scene-runtime-panel__eyebrow">人物卡</p>
        <h2>{{ scene?.title || "先选择一个场景" }}</h2>
        <p>只展示本场可用的人物资料；作者笔记保存在本机草稿中，不会自动改动正史。</p>
      </div>
      <button v-if="error" type="button" class="btn btn-sm" data-action="retry-scene-character-cards" @click="$emit('retry')">重新加载</button>
    </header>

    <div v-if="!scene" class="scene-runtime-empty" data-role="scene-runtime-character-empty">
      <strong>请先从“管理”选择一个场景</strong>
      <p>人物卡会跟随当前场景切换，不会把不同场景的人物资料混在一起。</p>
      <button type="button" class="btn btn-sm btn-primary" data-action="scene-runtime-return-management" @click="$emit('return-management')">回到管理</button>
    </div>
    <div v-else-if="loading" class="scene-runtime-loading" role="status" aria-live="polite">正在加载本场人物资料…</div>
    <div v-else-if="error" class="scene-runtime-error" role="alert">{{ error }}</div>
    <div v-else-if="!characters.length" class="scene-runtime-empty">
      <strong>本场还没有人物卡</strong>
      <p>可以先在“管理”补充视角人物或章节关联，之后再回来整理人物反应。</p>
    </div>
    <div v-else class="scene-character-cards" data-role="scene-character-cards">
      <article v-for="character in characters" :key="character.id" class="scene-character-card" :class="{ 'is-selected': selectedId === character.id }">
        <div class="scene-character-card__avatar" aria-hidden="true">{{ initials(character.name) }}</div>
        <div class="scene-character-card__body">
          <div class="scene-character-card__heading">
            <div>
              <h3>{{ character.name }}</h3>
              <span class="scene-character-card__source">{{ character.source }}</span>
            </div>
            <div class="scene-runtime-panel__actions">
              <button type="button" class="btn btn-sm" :data-action="`select-scene-character-${character.id}`" @click="$emit('select', character.id)">{{ selectedId === character.id ? "已选" : "选为重点" }}</button>
              <button type="button" class="btn btn-sm" :data-action="`edit-scene-character-${character.id}`" @click="$emit('edit', character.id)">{{ selectedId === character.id ? "收起编辑" : character.cardId ? "编辑人物卡" : "新建人物卡" }}</button>
            </div>
          </div>
          <dl class="scene-character-card__facts">
            <div><dt>当前状态</dt><dd>{{ character.status || "待补充" }}</dd></div>
            <div v-if="character.currentGoal"><dt>当前目标</dt><dd>{{ character.currentGoal }}</dd></div>
            <div v-if="character.currentEmotion"><dt>情绪</dt><dd>{{ character.currentEmotion }}</dd></div>
            <div><dt>人物底色</dt><dd>{{ character.personality }}</dd></div>
          </dl>
          <label class="scene-character-card__notes">
            <span>本场作者笔记</span>
            <textarea
              class="form-textarea"
              rows="2"
              :value="notes[character.id] || ''"
              :placeholder="`记录${character.name}在本场的临时变化`"
              :data-action="`scene-character-note-${character.id}`"
              @input="$emit('note', character.id, $event.target.value)"
            ></textarea>
          </label>
          <div v-if="selectedId === character.id" class="scene-character-card__editor">
            <div class="scene-character-card__editor-heading">
              <strong>{{ character.cardId ? "编辑本场人物卡" : "新建本场人物卡" }}</strong>
              <span v-if="character.versionNumber">当前 v{{ character.versionNumber }}</span>
            </div>
            <label><span>人物底色</span><textarea class="form-textarea" rows="3" :value="cardDraft.personality || ''" @input="$emit('update-card', 'personality', $event.target.value)"></textarea></label>
            <label><span>当前目标</span><input class="form-input" :value="cardDraft.currentGoal || ''" @input="$emit('update-card', 'currentGoal', $event.target.value)" /></label>
            <label><span>当前状态</span><input class="form-input" :value="cardDraft.currentState || ''" @input="$emit('update-card', 'currentState', $event.target.value)" /></label>
            <label><span>当前情绪</span><input class="form-input" :value="cardDraft.currentEmotion || ''" @input="$emit('update-card', 'currentEmotion', $event.target.value)" /></label>
            <label><span>本场作者笔记</span><textarea class="form-textarea" rows="2" :value="cardDraft.authorNotes || ''" @input="$emit('update-card', 'authorNotes', $event.target.value)"></textarea></label>
            <div class="scene-runtime-panel__actions">
              <button type="button" class="btn btn-sm btn-primary" :disabled="cardSaving" data-action="save-scene-character-card" @click="$emit('save-card')">{{ cardSaving ? "保存中..." : "保存新版本" }}</button>
              <button type="button" class="btn btn-sm" :disabled="cardGenerating" data-action="generate-scene-character-card" @click="$emit('generate-card')">{{ cardGenerating ? "生成中..." : "生成建议" }}</button>
              <button v-if="cardDraft.cardId" type="button" class="btn btn-sm" data-action="load-scene-character-card-history" @click="$emit('history')">版本历史</button>
            </div>
            <div v-if="generatedCard" class="scene-character-card__generated">
              <strong>待确认的人物卡建议</strong>
              <p>{{ generatedCard.content?.personality || "生成结果暂未包含人物底色" }}</p>
              <button type="button" class="btn btn-sm" data-action="apply-generated-scene-character-card" @click="$emit('apply-generated')">放入编辑器</button>
            </div>
            <div v-if="cardHistoryLoading" class="scene-runtime-loading scene-runtime-loading--compact">正在加载版本历史…</div>
            <div v-else-if="cardHistory.length" class="scene-character-card__history" aria-label="人物卡版本历史">
              <div v-for="revision in cardHistory" :key="revision.id" class="scene-character-card__history-item">
                <span>v{{ revision.version_number || revision.versionNumber }} · {{ revision.is_current ? "当前" : "历史" }}</span>
                <button v-if="!revision.is_current" type="button" class="btn btn-sm" @click="$emit('restore-history', revision)">按此版本新建</button>
              </div>
            </div>
          </div>
        </div>
      </article>
    </div>
  </section>
</template>

<script setup>
defineProps({
  scene: { type: Object, default: null },
  characters: { type: Array, default: () => [] },
  notes: { type: Object, default: () => ({}) },
  selectedId: { type: String, default: null },
  cardDraft: { type: Object, default: () => ({}) },
  cardHistory: { type: Array, default: () => [] },
  generatedCard: { type: Object, default: null },
  cardSaving: Boolean,
  cardGenerating: Boolean,
  cardHistoryLoading: Boolean,
  loading: Boolean,
  error: { type: String, default: null },
})

defineEmits([
  "retry", "return-management", "select", "note", "edit", "update-card", "save-card",
  "generate-card", "apply-generated", "history", "restore-history",
])

function initials(name) {
  return String(name || "人").trim().slice(0, 1) || "人"
}
</script>
