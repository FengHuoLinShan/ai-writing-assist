<template>
  <section class="card world-design-panel" aria-label="持续世界推演">
    <div class="world-design-panel__bar">
      <div><strong>继续完善这个世界</strong><p>从已保存的{{ depthLabel }}继续。这里只保存创作成果，正式采用仍需另行审阅。</p></div>
      <span v-if="readOnly" class="badge">历史只读预览</span>
      <button v-else-if="historical" class="btn btn-primary" type="button" :disabled="busy" @click="$emit('fork')">在新会话继续</button>
      <button v-else class="btn btn-primary" type="button" :disabled="busy" @click="$emit('generate')">{{ busy ? '处理中…' : '推演本轮变化' }}</button>
    </div>
    <p v-if="historical">当前显示历史成果。单独开启会话后继续，现有会话与历史内容保持不变。</p>
    <p v-else>本轮使用上方选择的动作与当前输入；已保留、放弃和待定的决定会继续生效。</p>
    <details>
      <summary>选择本轮关注的面向</summary>
      <p>不勾选表示参考完整模型。模型较大时可只选择本轮需要的部分；作者决定始终保留。</p>
      <label v-for="section in focusSections" :key="section"><input type="checkbox" :checked="stateSections.includes(section)" :disabled="busy" @change="emit('update:stateSections', $event.target.checked ? [...stateSections, section] : stateSections.filter(value => value !== section))" />{{ sectionLabels[section] }}</label>
    </details>
    <details>
      <summary>已保存的决定与世界资料</summary>
      <div class="world-design-panel__decisions">
        <article v-for="decision in checkpoint.decisions || []" :key="decision.item_key">
          <strong>{{ decisionLabel[decision.disposition] }}</strong><p>{{ decision.text }}</p>
          <button v-if="!readOnly" type="button" class="btn btn-sm" :disabled="busy || historical" @click="editDecision(decision)">修改决定</button>
        </article>
        <button v-if="!readOnly" type="button" class="btn btn-sm" :disabled="busy || historical" @click="editDecision()">添加长期决定</button>
      </div>
      <details v-for="(value, section) in checkpoint.world_state" v-show="sectionLabels[section]" :key="section">
        <summary>{{ sectionLabels[section] }}</summary>
        <article v-for="entry in entries(section, value)" :key="entry.key" class="world-design-panel__entry">
          <strong>{{ entry.title }}</strong><p>{{ describe(entry.value) }}</p>
          <button v-if="!readOnly && ['rules', 'actors', 'places', 'institutions', 'history'].includes(section)" class="btn btn-sm" type="button" :disabled="busy || historical || entry.value.status === 'deprecated'" @click="emit('prepare-suggestion', { id: entry.value.id, name: entry.title, section })">整理为待审设定</button>
          <button v-if="!readOnly && editableSections.has(section)" type="button" class="btn btn-sm" :disabled="busy || historical" @click="editEntry(section, entry)">局部修改</button>
        </article>
      </details>
    </details>
    <button v-if="!readOnly" class="btn btn-ghost" type="button" @click="emit('export')">导出完整世界模型</button>
    <fieldset v-if="proposal" :disabled="busy || historical || readOnly">
      <h3>本轮改变</h3>
      <p v-if="proposal.stale" role="alert">资料或输入已变化；本轮提案保留供核对，请重新推演。</p>
      <p v-if="readOnly">{{ proposal.summary }}</p>
      <label v-else>本轮说明<textarea :value="proposal.summary" rows="3" @input="update(['summary'], $event.target.value)" /></label>
      <article v-for="(decision, index) in proposal.decisions || []" :key="decision.item_key" class="world-design-panel__entry">
        <label>作者决定<textarea :value="decision.text" rows="3" maxlength="600" @input="update(['decisions', index, 'text'], $event.target.value)" /></label>
        <label>处理方式<select :value="decision.disposition" @change="update(['decisions', index, 'disposition'], $event.target.value)"><option v-for="(label, key) in decisionLabel" :key="key" :value="key">{{ label }}</option></select></label>
      </article>
      <template v-for="(value, section) in proposal.changes" :key="section">
        <section v-if="entries(section, value).length">
          <h4>{{ sectionLabels[section] }}</h4>
          <article v-for="entry in entries(section, value)" :key="entry.key" class="world-design-panel__entry">
            <div class="world-design-panel__bar"><strong>{{ entry.title }}</strong><button class="btn btn-sm btn-ghost" type="button" @click="removeEntry(section, entry)">本轮不改这项</button></div>
            <p v-if="previous(section, entry)">原内容：{{ describe(previous(section, entry)) }}</p>
            <div class="world-design-panel__fields">
              <template v-for="(fieldValue, field) in entry.value" :key="field">
                <label v-if="fieldLabels[field] && (typeof fieldValue === 'string' || (Array.isArray(fieldValue) && fieldValue.every(item => typeof item === 'string')))">
                  {{ fieldLabels[field] }}
                  <p v-if="readOnly">{{ field === 'status' ? statusLabels[fieldValue] : Array.isArray(fieldValue) ? fieldValue.join('；') : fieldValue }}</p>
                  <select v-else-if="field === 'status'" :value="fieldValue" @change="updateEntry(section, entry, field, $event.target.value)"><option v-for="key in statusOptions(fieldValue)" :key="key" :value="key">{{ statusLabels[key] }}</option></select>
                  <textarea v-else :value="Array.isArray(fieldValue) ? fieldValue.join('\n') : fieldValue" rows="3" @input="updateEntry(section, entry, field, Array.isArray(fieldValue) ? $event.target.value.split('\n').filter(line => line.trim()) : $event.target.value)" />
                </label>
              </template>
            </div>
            <p v-if="entry.value.from">{{ referenceName(entry.value.from) }} → {{ referenceName(entry.value.to) }} · {{ dependencyLabels[entry.value.kind] }}</p>
            <p v-if="entry.value.evidence?.length">附有 {{ entry.value.evidence.length }} 项来源依据</p>
          </article>
        </section>
      </template>
      <label>保存阶段<select :value="proposal.depth || checkpoint.depth" @change="update(['depth'], $event.target.value)"><option value="seed">灵感种子</option><option value="candidate">候选世界</option><option value="instance">具体实例</option></select></label>
      <p>未列出的内容会继续保留；相关依赖和旧检查会在保存时重新核定。阶段深度不代表正式采用。</p>
      <button class="btn btn-primary" type="button" :disabled="busy || proposal.stale || !proposal.summary?.trim()" @click="$emit('save')">保存本轮阶段成果</button>
      <button class="btn btn-ghost" type="button" :disabled="busy" @click="$emit('discard')">放弃本轮修改</button>
    </fieldset>
  </section>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({ checkpoint: { type: Object, required: true }, proposal: Object, busy: Boolean, historical: Boolean, readOnly: Boolean, stateSections: { type: Array, default: () => [] } })
const emit = defineEmits(['prepare-suggestion', 'export', 'update:stateSections', 'fork', 'generate', 'save', 'discard', 'update:proposal'])
const sectionLabels = { premise: '世界前提', knowledge_layers: '知识与认知边界', rules: '规则与代价', reproduction_loops: '日常运转', facets: '世界各面向', coupling_chains: '跨系统因果', situated_tests: '生活推演', pressure_tests: '压力测试', actors: '人物', places: '地点', institutions: '制度', history: '历史', dependencies: '依赖关系', fiction_core: '下游创作状态', authority: '作者边界', change_log: '变更记录', audit: '检查状态' }
const groupLabels = { author_truth: '作者已知真相', expert_models: '专家解释', public_beliefs: '公众认知', reader_unknowns: '读者未知', material: '物质供给', population_care: '人口与照护', economic: '经济', institutional: '制度', knowledge: '知识传承', meaning_identity: '意义与身份', ordinary_tuesday: '普通一天', seven_day_failure: '七日故障', life_course: '一生', ten_year_feedback: '十年反馈', world: '世界', character: '人物', story: '故事', outline: '大纲', prose: '正文', editor: '审稿' }
const fieldLabels = { name: '名称', status: '状态', capability: '能够做到', impossibility: '无法做到', inputs: '需要投入（每行一项）', outputs: '产出（每行一项）', costs: '代价（每行一项）', losses: '损耗（每行一项）', access: '使用资格', visibility: '可见征兆', scale_limits: '规模边界', failure_modes: '故障', maintenance: '维护', countermeasures: '应对方法', claim: '认知内容', summary: '内容', core_difference: '核心差异', human_experience: '人的体验', scale: '范围', aesthetic_surface: '表面风貌', themes: '主题', chain: '运转链', gaps: '尚缺内容', reason: '说明', breaks: '断点', scenario: '具体情境', contradictions: '矛盾', result: '推演结果', failures: '失败点', notes: '备注' }
const statusLabels = { draft: '草稿', proposed: '候选', 'author-required': '需作者决定', deprecated: '已放弃', canon: '已有正式依据', gap: '尚缺', partial: '部分覆盖', covered: '有依据覆盖', 'not-applicable': '不适用', 'not-run': '尚未检查', pass: '通过本次检查', mixed: '部分通过', fail: '发现问题', 'not-started': '未开始', ready: '可继续', 'in-progress': '进行中', valid: '已验证', 'needs-review': '需复核', invalidated: '已失效', blocked: '待解决' }
const dependencyLabels = { requires: '依赖', informs: '提供依据', derives: '推导', contradicts: '矛盾' }
const decisionLabel = { locked: '继续保留', rejected: '明确放弃', open: '仍待决定' }
const editableSections = new Set(Object.keys(sectionLabels).filter(key => !['authority', 'change_log', 'audit'].includes(key)))
const focusSections = [...editableSections]
const depthLabel = computed(() => ({ seed: '灵感种子', candidate: '候选世界', instance: '具体实例' }[props.checkpoint.depth] || '阶段成果'))
function entries(section, value) {
  if (!value) return []
  if (Array.isArray(value)) return value.map((item, index) => ({ key: item.id || index, title: item.name || (section === 'dependencies' ? '依赖关系' : '条目'), value: item, path: [index] }))
  if (section === 'premise') return [{ key: 'premise', title: '世界前提', value, path: [] }]
  return Object.entries(value).flatMap(([key, item]) => Array.isArray(item)
    ? item.filter(entry => entry && typeof entry === 'object').map((entry, index) => ({ key: entry.id || `${key}-${index}`, title: entry.name || groupLabels[key] || '记录', value: entry, path: [key, index] }))
    : item && typeof item === 'object' ? [{ key, title: groupLabels[key] || '记录', value: item, path: [key] }] : [])
}
function describe(item) { return [item?.name, item?.capability, item?.impossibility, item?.summary, item?.claim, item?.scenario, item?.result, item?.reason, item?.core_difference, ...(item?.costs || []), item?.status ? statusLabels[item.status] : ''].filter(Boolean).join(' · ') || '尚无内容' }
function previous(section, entry) { return entries(section, props.checkpoint.world_state[section]).find(item => item.key === entry.key)?.value }
function referenceName(id) { return Object.entries(props.checkpoint.world_state).flatMap(([key, value]) => entries(key, value)).find(item => item.value.id === id)?.title || '本轮关联资料' }
function statusOptions(status) { return [['draft', 'proposed', 'author-required', 'deprecated'], ['gap', 'partial', 'covered', 'not-applicable'], ['not-run', 'pass', 'mixed', 'fail'], ['not-started', 'ready', 'in-progress', 'needs-review', 'invalidated', 'blocked']].find(group => group.includes(status)) || ['proposed', 'deprecated'] }
function draft() { return JSON.parse(JSON.stringify(props.proposal || { summary: '调整世界设计', changes: {}, decisions: [], depth: props.checkpoint.depth })) }
function update(path, value) { const next = draft(); let target = next; for (const key of path.slice(0, -1)) target = target[key]; target[path.at(-1)] = value; emit('update:proposal', next) }
function updateEntry(section, entry, field, value) { update(['changes', section, ...entry.path, field], value) }
function editEntry(section, entry) {
  const next = draft(); const value = JSON.parse(JSON.stringify(entry.value)); if (['canon', 'valid'].includes(value.status)) value.status = value.status === 'canon' ? 'proposed' : 'needs-review'
  if (section === 'premise') next.changes.premise = value
  else if (Array.isArray(props.checkpoint.world_state[section])) { next.changes[section] ||= []; const index = next.changes[section].findIndex(item => item.id === value.id && (item.id || (item.from === value.from && item.to === value.to))); if (index < 0) next.changes[section].push(value); else next.changes[section][index] = value }
  else { next.changes[section] ||= {}; const key = entry.path[0]; if (entry.path.length === 1) next.changes[section][key] = value; else { next.changes[section][key] ||= []; const index = next.changes[section][key].findIndex(item => item.id === value.id); if (index < 0) next.changes[section][key].push(value); else next.changes[section][key][index] = value } }
  emit('update:proposal', next)
}
function editDecision(decision) { const next = draft(); next.decisions ||= []; if (decision && next.decisions.some(item => item.item_key === decision.item_key)) return; next.decisions.push(decision ? JSON.parse(JSON.stringify(decision)) : { item_key: `author-${crypto.randomUUID()}`, text: '', disposition: 'open', source_keys: [] }); emit('update:proposal', next) }
function removeEntry(section, entry) { const next = draft(); if (!entry.path.length) delete next.changes[section]; else { let target = next.changes[section]; for (const key of entry.path.slice(0, -1)) target = target[key]; if (Array.isArray(target)) target.splice(entry.path.at(-1), 1); else delete target[entry.path.at(-1)] }; emit('update:proposal', next) }
</script>

<style scoped>
.world-design-panel { display: grid; gap: var(--space-4, 16px); }
.world-design-panel__bar { display: flex; justify-content: space-between; align-items: start; gap: var(--space-3, 12px); flex-wrap: wrap; }
.world-design-panel__entry { padding-block: var(--space-3, 12px); border-bottom: 1px solid var(--border); overflow-wrap: anywhere; }
.world-design-panel__fields { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 260px), 1fr)); gap: var(--space-3, 12px); }
.world-design-panel label { display: grid; gap: var(--space-2, 8px); min-width: 0; }
.world-design-panel fieldset { min-width: 0; border: 0; padding: 0; display: grid; gap: var(--space-3, 12px); }
.world-design-panel textarea, .world-design-panel select { width: 100%; min-height: 44px; }
.world-design-panel summary { cursor: pointer; min-height: 44px; display: flex; align-items: center; }
</style>
