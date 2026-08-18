<template>
  <details class="scene-lens" :class="{ 'scene-lens--mobile': mobile }" :open="!mobile">
    <summary>
      <span><strong>本场</strong><small>{{ scene?.title || '未命名 Scene' }}</small></span>
      <span aria-hidden="true">详情</span>
    </summary>
    <div class="scene-lens__body">
      <dl v-if="staticItems.length" class="scene-lens__facts">
        <template v-for="item in staticItems" :key="item.label">
          <dt>{{ item.label }}</dt><dd>{{ item.value }}</dd>
        </template>
      </dl>
      <p v-else class="writing-empty-hint">本场还没有可用的结构摘要。</p>

      <div class="scene-lens__load">
        <button type="button" class="btn btn-sm" :disabled="lens.loading" @click="$emit('load')">
          {{ lens.loading ? '正在查看…' : lens.error ? '重试角色可见信息' : lens.data ? '刷新角色可见信息' : '查看角色可见信息' }}
        </button>
        <p v-if="lens.error" class="writing-form-error" role="alert">{{ lens.error }}，静态摘要已保留。</p>
      </div>

      <template v-if="lens.data">
        <section class="scene-lens__section">
          <h4>POV 可见知识</h4>
          <ul v-if="knowledgeItems.length"><li v-for="item in knowledgeItems" :key="`${item.label}:${item.summary}`" :class="{ 'is-unavailable': !item.availability }"><strong>{{ item.label }}</strong><span>{{ item.summary }}</span></li></ul>
          <p v-else class="writing-empty-hint">未找到可安全展示的角色知识。</p>
        </section>
        <section class="scene-lens__section">
          <h4>场景时点状态</h4>
          <ul v-if="stateItems.length"><li v-for="item in stateItems" :key="`${item.label}:${item.summary}`" :class="{ 'is-unavailable': !item.availability }"><strong>{{ item.label }}</strong><span>{{ item.summary }}</span></li></ul>
          <p v-else class="writing-empty-hint">暂无已建立的 Scene 时点状态。</p>
        </section>
        <p v-for="warning in lens.data.warnings || []" :key="warning" class="scene-lens__warning">{{ warning }}</p>
      </template>
    </div>
  </details>
</template>

<script setup>
import { computed } from "vue"
import { sceneLensItems, sceneStructureSummary } from "../sceneLensModel.js"

const props = defineProps({
  scene: { type: Object, default: null },
  lens: { type: Object, default: () => ({ loading: false, data: null, error: null }) },
  mobile: { type: Boolean, default: false },
})
defineEmits(["load"])
const staticItems = computed(() => sceneStructureSummary(props.scene))
const knowledgeItems = computed(() => sceneLensItems(props.lens.data?.role_visible_knowledge))
const stateItems = computed(() => sceneLensItems(props.lens.data?.scene_world_state))
</script>
