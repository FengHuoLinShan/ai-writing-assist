<template>
  <section id="scene-runtime-panel-simulation" class="scene-runtime-panel scene-simulation-panel" role="tabpanel" aria-labelledby="scene-runtime-tab-simulation">
    <header class="scene-runtime-panel__header">
      <div>
        <p class="scene-runtime-panel__eyebrow">人物反应与剧情推演</p>
        <h2>{{ scene?.title || "先选择一个场景" }}</h2>
        <p>一键推演会补齐本场缺失或过期的人物卡；人物反应与剧本仍只作为待确认预览，不会自动保存。</p>
      </div>
      <div class="scene-runtime-panel__actions">
        <button v-if="running" type="button" class="btn btn-sm" data-action="cancel-scene-simulation" @click="$emit('cancel')">停止推演</button>
        <button v-else type="button" class="btn btn-sm" :disabled="!scene || loading || reactionRunning" data-action="run-scene-reactions" @click="$emit('run-reactions')">{{ reactionRunning ? "生成人物反应中..." : "只生成人物反应" }}</button>
        <button v-if="!running" type="button" class="btn btn-sm btn-primary" :disabled="!scene || loading || reactionRunning" data-action="run-scene-simulation" @click="$emit('run')">{{ simulation ? "重新推演并检查人物卡" : "推演并补齐人物卡" }}</button>
      </div>
    </header>

    <div v-if="!scene" class="scene-runtime-empty">
      <strong>请先从“管理”选择一个场景</strong>
      <p>推演会读取本场目标、冲突和人物资料。</p>
    </div>
    <div v-else-if="running" class="scene-runtime-progress" role="status" aria-live="polite">
      <strong>{{ progress?.message || "正在整理人物反应与剧情走向…" }}</strong>
      <span v-if="progress?.percent != null">{{ progress.percent }}%</span>
    </div>
    <div v-else-if="error" class="scene-runtime-error" role="alert">{{ error }}</div>
    <div v-else-if="!simulation" class="scene-runtime-empty">
      <strong>先生成一组可比较的候选</strong>
      <p>你可以逐条保留或拒绝人物反应，再把成立的方向带进剧本区。</p>
    </div>
    <div v-else class="scene-simulation-content">
      <section class="scene-runtime-constraints" aria-label="本场约束">
        <h3>本场约束</h3>
        <dl>
          <div><dt>目标</dt><dd>{{ scene.goal || "尚未填写" }}</dd></div>
          <div><dt>核心冲突</dt><dd>{{ scene.core_conflict || "尚未填写" }}</dd></div>
          <div><dt>必须发生</dt><dd>{{ scene.must_happen || "作者待确认" }}</dd></div>
          <div><dt>禁止发生</dt><dd>{{ scene.must_not_happen || "暂无" }}</dd></div>
        </dl>
      </section>

      <section class="scene-runtime-section" aria-labelledby="scene-reactions-heading">
        <div class="scene-runtime-section__heading"><h3 id="scene-reactions-heading">人物反应候选</h3><span>{{ keptCount }} 条已保留</span></div>
        <div v-if="!simulation.reactions?.length" class="scene-runtime-empty scene-runtime-empty--compact">暂未形成可比较的反应候选。</div>
        <article v-for="reaction in simulation.reactions || []" :key="reaction.id" class="scene-reaction-card" :class="`is-${reaction.status || 'candidate'}`">
          <div class="scene-reaction-card__heading"><strong>{{ reaction.name }}</strong><span>{{ reaction.status === "kept" ? "已保留" : reaction.status === "rejected" ? "已拒绝" : "待决定" }}</span></div>
          <p v-if="reaction.goal"><b>目标：</b>{{ reaction.goal }}</p>
          <p v-if="reaction.subjectiveJudgment"><b>判断：</b>{{ reaction.subjectiveJudgment }}</p>
          <p v-if="reaction.immediateReaction"><b>即时反应：</b>{{ reaction.immediateReaction }}</p>
          <p><b>压力：</b>{{ reaction.stance }}</p>
          <p><b>回应：</b>{{ reaction.action }}</p>
          <p v-if="reaction.dialogueTendency"><b>对白倾向：</b>{{ reaction.dialogueTendency }}</p>
          <p v-if="reaction.conflict"><b>冲突：</b>{{ reaction.conflict }}</p>
          <p v-if="reaction.confidence"><b>置信度：</b>{{ Math.round(reaction.confidence * 100) }}%</p>
          <div class="scene-reaction-card__actions">
            <button type="button" class="btn btn-sm btn-primary" :data-action="`keep-scene-reaction-${reaction.id}`" :disabled="reaction.status === 'kept'" @click="$emit('reaction', reaction.id, 'kept')">保留</button>
            <button type="button" class="btn btn-sm" :data-action="`reject-scene-reaction-${reaction.id}`" :disabled="reaction.status === 'rejected'" @click="$emit('reaction', reaction.id, 'rejected')">拒绝</button>
          </div>
        </article>
      </section>

      <section class="scene-runtime-section" aria-labelledby="scene-beats-heading">
        <div class="scene-runtime-section__heading"><h3 id="scene-beats-heading">Beat 链与叙事计划</h3></div>
        <ol class="scene-beat-list">
          <li v-for="beat in simulation.beats || []" :key="beat.id"><strong>{{ beat.title }}</strong><span>{{ beat.detail }}</span></li>
        </ol>
        <p class="scene-runtime-plan">{{ simulation.plan || "暂无叙事计划" }}</p>
      </section>
    </div>
  </section>
</template>

<script setup>
import { computed } from "vue"

const props = defineProps({
  scene: { type: Object, default: null },
  simulation: { type: Object, default: null },
  progress: { type: Object, default: null },
  loading: Boolean,
  running: Boolean,
  reactionRunning: Boolean,
  error: { type: String, default: null },
})

defineEmits(["run", "cancel", "reaction", "run-reactions"])

const keptCount = computed(() => (props.simulation?.reactions || []).filter((item) => item.status === "kept").length)
</script>
