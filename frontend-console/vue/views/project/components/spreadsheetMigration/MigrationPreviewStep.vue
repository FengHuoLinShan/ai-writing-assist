<script setup>
/**
 * 表格迁移 — 第四步：预览与冲突处理。
 * 分页签（人物与设定 / 关系 / 大纲结构 / 冲突 / 仅参考）；逐条决策；
 * 确认采用（confirmed + preview_hash）；409 过期自动取回新预览。
 */
import { computed, ref } from "vue"
import {
  PREVIEW_TABS,
  actionLabel,
  conflictItems,
  decisionLabel,
  referenceOnlyItems,
} from "../../logic/spreadsheetMigration.js"

const props = defineProps({
  session: { type: Object, required: true },
  applying: { type: Boolean, default: false },
  savingDecisions: { type: Boolean, default: false },
})
const emit = defineEmits(["apply", "decide"])

const tab = ref("world_items")
const confirmed = ref(false)
const decisions = ref({})
const dirty = ref(false)

const preview = computed(() => props.session.preview)

const tabs = computed(() =>
  PREVIEW_TABS.map((entry) => ({ ...entry, count: itemsOf(entry.key).length })),
)

function itemsOf(key) {
  if (!preview.value) return []
  if (key === "conflicts") return conflictItems(preview.value)
  if (key === "reference_only") return referenceOnlyItems(preview.value)
  return preview.value[key] || []
}

function currentItems() {
  return itemsOf(tab.value)
}

function decisionOf(itemKey) {
  return decisions.value[itemKey]?.action || "auto"
}

function setDecision(itemKey, action) {
  decisions.value = { ...decisions.value, [itemKey]: { action } }
  dirty.value = true
}

async function saveDecisions() {
  const payload = Object.entries(decisions.value).map(([itemKey, value]) => ({
    item_key: itemKey,
    action: value.action || "auto",
  }))
  await emit("decide", payload)
  dirty.value = false
}

function apply() {
  emit("apply", {
    expected_preview_hash: preview.value?.preview_hash,
  })
}

const counts = computed(() => preview.value?.counts || {})
const outlineRow = computed(() => preview.value?.outline)
</script>

<template>
  <div class="sm-preview" data-testid="sm-preview">
    <div v-if="!preview" class="sm-preview__empty" role="status">
      预览尚未生成。请先在上一步保存表格映射。
    </div>
    <template v-else>
      <div class="sm-preview__summary" data-testid="sm-preview-counts">
        <span>新建 {{ counts.create || 0 }}</span>
        <span>补全 {{ counts.fill || 0 }}</span>
        <span>已存在 {{ counts.existing || 0 }}</span>
        <span>关系 {{ counts.relations || 0 }}</span>
        <span>大纲结构 {{ counts.structures || 0 }}</span>
        <span class="sm-preview__conflict-count">冲突 {{ counts.conflict || 0 }}</span>
        <span>跳过 {{ counts.skip || 0 }}</span>
      </div>
      <p v-if="preview.validation_policy_active" class="alert alert-warning" role="alert">
        本项目开启了世界设定校验策略：本次迁移会被拦截，不会写入任何内容。请先在项目设置中调整策略。
      </p>
      <div class="sm-preview__outline" v-if="outlineRow" data-testid="sm-outline-row">
        总纲：{{ outlineRow.action === "create" ? "将创建" : "将替换现有总纲" }}
        <template v-if="outlineRow.title">（{{ outlineRow.title }}）</template>
      </div>

      <div class="sm-preview__tabs" role="tablist">
        <button
          v-for="entry in tabs"
          :key="entry.key"
          type="button"
          role="tab"
          class="sm-preview__tab"
          :class="{ 'sm-preview__tab--active': tab === entry.key }"
          :aria-selected="tab === entry.key"
          :data-action="`sm-tab-${entry.key}`"
          @click="tab = entry.key"
        >{{ entry.label }}（{{ entry.count }}）</button>
      </div>

      <div class="sm-preview__list" :data-tab="tab">
        <p v-if="currentItems().length === 0" class="sm-preview__empty">这一类没有条目。</p>
        <div
          v-for="item in currentItems()"
          :key="item.item_key"
          class="sm-preview__item"
          :data-item="item.item_key"
        >
          <div class="sm-preview__item-head">
            <strong>{{ item.label || item.source_label || "（未命名）" }}</strong>
            <span v-if="item.type_label" class="sm-preview__muted">{{ item.type_label }}</span>
            <span class="sm-preview__action" :data-action-label="item.action">{{ actionLabel(item.action) }}</span>
            <span v-if="item.kind_guessed" class="sm-preview__muted">关系类型为推测</span>
            <span v-if="item.ai_available" class="sm-preview__muted">
              AI 建议{{ item.ai_passed === false ? "（未通过复核，不可采用）" : "" }}
            </span>
          </div>
          <p v-if="item.target_label" class="sm-preview__muted">→ {{ item.target_label }}</p>
          <p v-if="item.fills && item.fills.length" class="sm-preview__muted">补全：{{ item.fills.join("、") }}</p>
          <ul v-if="item.conflicts && item.conflicts.length" class="sm-preview__conflicts">
            <li v-for="conflict in item.conflicts" :key="conflict.field_label">
              <strong>{{ conflict.field_label }}</strong>：已有「{{ conflict.current_excerpt }}」≠ 表格「{{ conflict.incoming_excerpt }}」
            </li>
          </ul>
          <p v-if="item.reason" class="sm-preview__reason">{{ item.reason }}</p>
          <div v-if="item.similar && item.similar.length" class="sm-preview__similar">
            与已有对象相似：{{ item.similar.map((s) => s.label).join("、") }}
          </div>
          <div class="sm-preview__decision">
            <select
              :value="decisionOf(item.item_key)"
              :data-action="`sm-decision-${item.item_key}`"
              @change="setDecision(item.item_key, $event.target.value)"
            >
              <option value="auto">按建议处理</option>
              <option value="different_object">是不同对象，新建</option>
              <option value="append_note">冲突处追加到备注</option>
              <option value="skip">跳过这条</option>
            </select>
            <span class="sm-preview__muted">{{ decisionLabel(decisionOf(item.item_key)) }}</span>
            <span class="sm-preview__source">{{ item.source_sheet_name }} 第 {{ item.source_row }} 行</span>
          </div>
        </div>
      </div>

      <div class="sm-preview__actions">
        <button
          v-if="dirty"
          type="button"
          class="btn btn-ghost"
          data-action="sm-save-decisions"
          :disabled="savingDecisions"
          @click="saveDecisions"
        >{{ savingDecisions ? "正在保存…" : "保存调整" }}</button>
        <label class="sm-preview__confirm">
          <input v-model="confirmed" type="checkbox" data-action="sm-apply-confirm" />
          我已核对以上预览，确认采用（同名只补空字段，冲突项不会写入）
        </label>
        <button
          type="button"
          class="btn"
          data-action="sm-apply"
          :disabled="applying || !confirmed"
          @click="apply"
        >{{ applying ? "正在导入…" : "确认采用" }}</button>
      </div>
    </template>
  </div>
</template>

<style scoped>
.sm-preview { display: flex; flex-direction: column; gap: 12px; }
.sm-preview__summary { display: flex; flex-wrap: wrap; gap: 12px; font-size: 13px; }
.sm-preview__conflict-count { color: #b45309; font-weight: 600; }
.sm-preview__outline { font-size: 13px; color: var(--text-muted, #6b7280); }
.sm-preview__tabs { display: flex; flex-wrap: wrap; gap: 4px; }
.sm-preview__tab { border: 1px solid var(--border-color, #e5e7eb); background: transparent; border-radius: 6px 6px 0 0; padding: 4px 10px; font-size: 13px; cursor: pointer; }
.sm-preview__tab--active { background: var(--bg-subtle, #f3f4f6); font-weight: 600; }
.sm-preview__list { display: flex; flex-direction: column; gap: 8px; }
.sm-preview__item { border: 1px solid var(--border-color, #e5e7eb); border-radius: 8px; padding: 8px 12px; display: flex; flex-direction: column; gap: 4px; }
.sm-preview__item-head { display: flex; flex-wrap: wrap; gap: 8px; align-items: baseline; }
.sm-preview__muted { color: var(--text-muted, #6b7280); font-size: 13px; }
.sm-preview__action { font-size: 13px; font-weight: 600; color: var(--accent, #2563eb); }
.sm-preview__conflicts { margin: 0; padding-left: 18px; font-size: 13px; color: #92400e; }
.sm-preview__reason { margin: 0; font-size: 13px; color: var(--text-muted, #6b7280); }
.sm-preview__similar { font-size: 13px; color: #92400e; }
.sm-preview__decision { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; font-size: 13px; }
.sm-preview__source { color: var(--text-muted, #6b7280); }
.sm-preview__actions { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; border-top: 1px solid var(--border-color, #e5e7eb); padding-top: 10px; }
.sm-preview__confirm { font-size: 13px; }
.sm-preview__empty { color: var(--text-muted, #6b7280); }
@media (max-width: 640px) {
  .sm-preview__item { padding: 8px; }
  .sm-preview__decision { flex-direction: column; align-items: stretch; }
}
</style>
