<template>
  <section id="scene-runtime-panel-simulation" class="scene-runtime-panel scene-simulation-panel" role="tabpanel" aria-labelledby="scene-runtime-tab-simulation">
    <header class="scene-runtime-panel__header">
      <div>
        <p class="scene-runtime-panel__eyebrow">同一场景导演工作台</p>
        <h2>{{ scene?.title || "先选择一个场景" }}</h2>
        <p>预算预览、逐人物隔离排演、候选历史与分支都由同一个导演运行管理。</p>
      </div>
    </header>
    <SceneDirectorPanel :project-id="projectId" :scene="scene" :characters="characters" />
    <SceneRehearsalPanel
      v-if="scene && projectId && simulation?.rehearsalId"
      class="scene-simulation-panel__legacy"
      :project-id="projectId"
      :characters="characters"
      :rehearsal-id="simulation.rehearsalId"
      :running="false"
    />
  </section>
</template>

<script setup>
import SceneDirectorPanel from "./SceneDirectorPanel.vue"
import SceneRehearsalPanel from "./SceneRehearsalPanel.vue"

defineProps({
  projectId: { type: String, default: null },
  characters: { type: Array, default: () => [] },
  scene: { type: Object, default: null },
  simulation: { type: Object, default: null },
})
</script>

<style scoped>
.scene-simulation-panel__legacy{margin-top:18px;padding-top:12px;border-top:1px solid var(--border,#d9e0e4)}
</style>
