<template>
  <section class="map-dynamic-section map-inspector">
    <h4>检查器</h4>
    <article class="map-dynamic-item">
      <div class="map-dynamic-title">{{ inspector.title || "暂无世界动态" }}</div>
      <div class="map-dynamic-meta">{{ metadata }}</div>
      <div class="map-dynamic-source">{{ mapSourceText(inspector.summary || "") }}</div>
      <ul v-if="inspector.source_evidence?.length" class="map-evidence-list">
        <li v-for="text in inspector.source_evidence.slice(0, 5)" :key="text">
          {{ mapSourceText(text) }}
        </li>
      </ul>
    </article>
  </section>
</template>

<script setup>
import { computed } from "vue"
import { mapSourceText } from "../mapModel.js"

const props = defineProps({ inspector: { type: Object, required: true } })
const metadata = computed(() => [
  props.inspector.type_label,
  props.inspector.location_label,
  props.inspector.spatial_anchor_label,
].filter(Boolean).join(" · "))
</script>
