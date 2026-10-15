<template>
  <section class="scene-character-card-v2" aria-label="人物卡资料与解释">
    <section class="scene-character-card-v2__group" aria-label="资料依据与场景状态">
      <h4>资料依据与场景状态</h4>
      <ul v-if="content.fact_basis?.length">
        <li v-for="fact in content.fact_basis" :key="fact.fact_id" data-role="character-card-fact">
          <span>{{ fact.value }}</span>
          <small>{{ factSource(fact) }}</small>
        </li>
      </ul>
      <p v-else>当前没有可展示的资料依据。</p>
    </section>
    <section v-if="content.pattern_basis?.length" class="scene-character-card-v2__group" aria-label="人物倾向参考">
      <h4>人物倾向参考 <small>已审阅的解释，不是事实</small></h4>
      <ul>
        <li v-for="pattern in content.pattern_basis" :key="pattern.pattern_id" data-role="character-card-pattern">
          <span>{{ pattern.statement }}</span>
          <small>{{ patternSource(pattern) }}</small>
        </li>
      </ul>
    </section>
    <section class="scene-character-card-v2__group" aria-label="本场解释性建议">
      <h4>本场解释性建议</h4>
      <p v-if="!content.interpretations?.length">暂无解释性建议；上方资料仍可供核对。</p>
      <ul v-else>
        <li v-for="(interpretation, index) in content.interpretations" :key="index" data-role="character-card-interpretation">
          <strong>{{ interpretation.statement }}</strong>
          <small>依据：{{ sourceSummary(content, interpretation) }}</small>
        </li>
      </ul>
    </section>
  </section>
</template>

<script setup>
defineProps({ content: { type: Object, required: true } })

const FACT_SOURCES = {
  character_profile: "人物资料",
  world_dossier: "世界档案",
  legacy_profile_field: "旧人物资料",
  story_state: "场景状态",
}
const FACT_LAYERS = { fact: "资料事实", belief: "人物所信", observation: "人物所见" }

function factSource(fact) {
  const source = FACT_SOURCES[fact.kind] || "来源资料"
  const layer = FACT_LAYERS[fact.layer] || "待核对"
  const revision = fact.revision_id ? " · 已保存修订" : fact.checkpoint_id ? " · 场景检查点" : ""
  return `${source} · ${layer}${revision}${fact.possibly_false ? " · 可能不实" : ""}`
}

function patternSource(pattern) {
  const refs = pattern.evidence_refs || []
  const locations = [...new Set(refs.map((ref) => {
    const chapter = ref.chapter_index == null ? NaN : Number(ref.chapter_index)
    if (Number.isInteger(chapter) && chapter > 0) return `第 ${chapter} 章`
    const scene = ref.scene_index == null ? NaN : Number(ref.scene_index)
    if (Number.isInteger(scene) && scene >= 0) return `场景 ${scene + 1}`
    return null
  }).filter(Boolean))]
  return locations.length ? `来源：${locations.join("、")}` : refs.length ? `附 ${refs.length} 条来源记录` : "来源记录待核对"
}

function sourceSummary(content, interpretation) {
  const facts = (content.fact_basis || [])
    .filter((fact) => (interpretation.source_fact_ids || []).includes(fact.fact_id))
    .map((fact) => fact.value)
  const patterns = (content.pattern_basis || [])
    .filter((pattern) => (interpretation.source_pattern_ids || []).includes(pattern.pattern_id))
    .map((pattern) => pattern.statement)
  return [...facts, ...patterns].join("；") || "引用的原资料当前不可显示"
}
</script>
