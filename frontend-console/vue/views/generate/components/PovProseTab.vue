<template>
  <div v-if="loading" class="generate-pov-workspace">
    <div class="card generate-pov-status" role="status" aria-live="polite">
      <div class="loading">正在准备章节、场景和角色…</div>
    </div>
  </div>
  <div v-else-if="warning && !chapters.length" class="generate-pov-workspace">
    <div class="card generate-pov-status" role="alert">
      <div>
        <div class="card-title">暂时无法准备正文建议</div>
        <p class="generate-empty-copy">{{ warning }}</p>
      </div>
      <button type="button" class="btn btn-sm" data-action="retry-pov-options" @click="$emit('retry-load')">重新加载</button>
    </div>
  </div>
  <div v-else-if="!chapters.length" class="generate-pov-workspace">
    <div class="card generate-pov-form">
      <div class="card-title">角色视角正文需要先准备章节</div>
      <p class="generate-empty-copy">先创建至少一个章节，再补充场景和视角角色，才能生成符合角色知识边界的正文建议。</p>
      <div class="generate-result-actions"><button type="button" class="btn btn-sm btn-primary" data-action="open-writing-from-pov-empty" @click="$emit('open-writing')">去写作台创建第一章</button><button type="button" class="btn btn-sm" data-action="return-world-from-pov-empty" @click="$emit('return-world')">先完善世界设定</button></div>
    </div>
  </div>
  <div v-else class="generate-pov-workspace">
    <form class="card generate-pov-form" @submit.prevent="$emit('generate')">
      <div class="generate-pov-heading">
        <div class="card-title">准备正文建议</div>
        <p>选定这一场由谁来观察和感受，再补充你希望保留的写作方向。</p>
      </div>
      <div v-if="warning" class="generate-template-warning" role="alert">
        <span>{{ warning }}</span>
        <button v-if="form.chapterIndex" type="button" class="btn btn-sm" data-action="retry-pov-scenes" @click="$emit('change-chapter', form.chapterIndex)">重新加载场景</button>
      </div>
      <div class="generate-form-grid">
        <label for="generate-pov-chapter"><span>章节 *</span><select id="generate-pov-chapter" :value="form.chapterIndex || ''" class="form-select" required @change="$emit('change-chapter', $event.target.value)"><option value="">请选择章节</option><option v-for="chapter in chapters" :key="chapter.chapter_index" :value="chapter.chapter_index">第 {{ chapter.chapter_index }} 章{{ chapter.title ? ` · ${chapter.title}` : '' }}</option></select></label>
        <label for="generate-pov-scene"><span>场景 *</span><select id="generate-pov-scene" :value="form.sceneId" class="form-select" :disabled="!form.chapterIndex" required @change="$emit('change-scene', $event.target.value)"><option value="">请选择场景</option><option v-for="scene in scenes" :key="scene.id" :value="scene.id">{{ scene.title || scene.name || '未命名场景' }}</option></select></label>
        <label for="generate-pov-character"><span>由谁来感受这一场 *</span><select id="generate-pov-character" v-model="form.viewpointCharacterId" class="form-select" required><option value="">请选择角色</option><option v-for="character in characters" :key="characterId(character)" :value="characterId(character)">{{ character.name || character.display_name || '未命名角色' }}</option></select></label>
      </div>
      <p v-if="manualRole" class="generate-pov-inline-note">本次按你手动选择的角色生成，不会修改场景原有设置。</p>
      <p v-if="sceneWithoutPov" class="generate-pov-inline-note is-warning">这个场景还没有固定视角角色，请为本次生成选择一名角色。</p>
      <div class="generate-pov-guidance">
        <strong>角色只会知道自己应当知道的事</strong>
        <span>AI 只参考这名角色在当前剧情中已经接触到的内容；作者掌握但角色尚不知道的设定不会交给正文生成。</span>
      </div>
      <label for="generate-pov-instruction"><span>作者指令</span><textarea id="generate-pov-instruction" v-model="form.instruction" class="form-textarea" rows="5" placeholder="例如：保持克制，先让她观察门上的刻痕，再决定是否告诉同行者。"></textarea></label>
      <div class="generate-pov-submit">
        <button type="submit" class="btn btn-primary" data-action="generate-pov-prose" :disabled="pending">{{ pending ? '正在生成…' : '生成正文建议' }}</button>
        <span>结果先进入待审建议，不会覆盖现有工作稿。</span>
      </div>
    </form>
    <section class="card generate-pov-result-panel" aria-labelledby="generate-pov-result-title">
      <div id="generate-pov-result-title" class="card-title">本次建议</div>
      <div id="generate-pov-result" class="generate-result">
        <div v-if="pending" class="generate-pov-progress" role="status" aria-live="polite">
          <strong>{{ progressText }}</strong>
          <progress v-if="progress != null" :value="boundedProgress" max="1">{{ Math.round(boundedProgress * 100) }}%</progress>
          <span>可以留在这里等待，当前选择和作者指令已经保留。</span>
          <button type="button" class="btn btn-sm" @click="$emit('cancel')">取消生成</button>
        </div>
        <div v-else-if="error" ref="errorEl" class="generate-pov-error" role="alert" tabindex="-1">
          <strong>这次没有生成成功</strong>
          <p>{{ error }}</p>
          <div class="generate-result-actions"><button type="button" class="btn btn-sm" data-action="retry-pov-prose" @click="$emit('generate')">按当前选择重试</button></div>
        </div>
        <div v-else-if="submission" class="generate-result-card">
          <div class="generate-result-title">角色视角正文建议已生成</div>
          <div class="generate-result-meta">第 {{ submission.chapterIndex }} 章 · {{ submissionScene?.title || submissionScene?.name || submission.sceneLabel || '已选场景' }} · {{ submissionRole?.name || submissionRole?.display_name || submission.roleLabel || '已选角色' }}</div>
          <p class="generate-result-summary">建议不会自动覆盖正文。请到写作台核对角色是否知道了不该知道的信息，再决定是否采用。</p>
          <div class="generate-result-actions"><button type="button" class="btn btn-sm btn-primary" data-action="open-generated-destination" @click="$emit('open-result', submission)">打开写作台审阅</button></div>
        </div>
        <div v-else class="generate-pov-summary">
          <p class="generate-empty-copy">完成左侧选择后，正文建议会出现在这里。</p>
          <div>章节：{{ form.chapterIndex ? `第 ${form.chapterIndex} 章${chapterTitle ? ` · ${chapterTitle}` : ''}` : '未选择' }}</div>
          <div>场景：{{ selectedScene?.title || selectedScene?.name || (form.sceneId ? '已选择' : '未选择') }}</div>
          <div>角色：{{ selectedRole?.name || selectedRole?.display_name || (form.viewpointCharacterId ? '已选择角色' : '未选择') }}</div>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, nextTick, ref, watch } from "vue"
import { characterId } from "../logic/generateLogic.js"
const props = defineProps({ loading: Boolean, chapters: { type: Array, default: () => [] }, scenes: { type: Array, default: () => [] }, characters: { type: Array, default: () => [] }, warning: String, submission: Object, pending: Boolean, progress: Number, error: String })
defineEmits(["change-chapter", "change-scene", "generate", "retry-load", "cancel", "open-result", "open-writing", "return-world"])
const form = defineModel("form", { type: Object, required: true })
const errorEl = ref(null)
const selectedScene = computed(() => props.scenes.find((item) => item.id === form.value.sceneId) || null)
const selectedRole = computed(() => props.characters.find((item) => characterId(item) === form.value.viewpointCharacterId) || null)
const submissionScene = computed(() => props.scenes.find((item) => item.id === props.submission?.sceneId) || null)
const submissionRole = computed(() => props.characters.find((item) => characterId(item) === props.submission?.viewpointCharacterId) || null)
const chapterTitle = computed(() => props.chapters.find((item) => Number(item.chapter_index) === Number(form.value.chapterIndex))?.title || "")
const manualRole = computed(() => Boolean(form.value.viewpointCharacterId && selectedScene.value?.pov_character_id && form.value.viewpointCharacterId !== selectedScene.value.pov_character_id))
const sceneWithoutPov = computed(() => Boolean(selectedScene.value && !selectedScene.value.pov_character_id))
const progressText = computed(() => props.progress == null ? "正在确认参考资料..." : `正在生成正文建议... ${Math.max(0, Math.min(100, Math.round(props.progress * 100)))}%`)
const boundedProgress = computed(() => Math.max(0, Math.min(1, Number(props.progress) || 0)))
watch(() => props.error, async (error) => { if (error) { await nextTick(); errorEl.value?.focus() } })
</script>
