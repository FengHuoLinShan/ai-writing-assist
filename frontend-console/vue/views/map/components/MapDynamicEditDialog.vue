<template>
  <Teleport to="body">
    <div v-if="editor.state.open" ref="overlayRef" class="vue-map-dialog-backdrop" role="presentation" @keydown="onKeydown" @focusin="onFocusin">
      <section ref="dialogRef" class="vue-map-dialog" role="dialog" aria-modal="true" aria-labelledby="map-dynamic-edit-title" :aria-busy="editor.state.saving" tabindex="-1">
        <header><h2 id="map-dynamic-edit-title">修改地图对象</h2><button type="button" class="btn btn-sm" aria-label="关闭" :disabled="editor.state.saving" @click="requestClose">×</button></header>
        <fieldset class="vue-map-dialog__body" :disabled="editor.state.saving" :inert="editor.state.saving || undefined">
          <div v-if="editor.state.error" class="alert alert-warning" role="alert">{{ editor.state.error }}</div>
          <div class="form-group"><label>对象</label><input class="form-input" :value="editor.state.item?.title || editor.state.targetName || '地图对象'" disabled /></div>
          <div class="form-group"><label>展示状态</label><select id="map-object-edit-status" v-model="editor.state.status" class="form-select"><template v-if="editor.state.isFact"><option value="confirmed">已采用</option><option value="rolled_back">历史（已回滚）</option><option value="deprecated">历史（已废弃）</option></template><template v-else><option value="candidate">待处理</option><option value="ignored">历史（已忽略）</option><option value="conflicted">待处理 · 存在冲突</option></template></select></div>
          <template v-if="!editor.state.isFact">
            <div class="form-group"><label>目标名称</label><input id="map-object-edit-target-name" v-model="editor.state.targetName" class="form-input" maxlength="255" /></div>
            <div class="form-group"><label>关联对象</label><select id="map-object-edit-target-entity" v-model="editor.state.targetEntityId" class="form-select"><option value="">未指定</option><option v-for="item in editor.state.entities" :key="item.id" :value="item.id">{{ item.name }} · {{ item.entityType || '对象' }}</option></select></div>
            <div class="map-observation-eligibility" :class="editor.state.item?.eligibility?.can_confirm ? 'is-ready' : 'is-missing'">{{ editor.state.item?.eligibility?.can_confirm ? '字段已完整，保存后可采用。' : `待补：${editor.state.item?.eligibility?.missing_item_labels?.join('、') || '请补全结构化字段'}` }}</div>
            <section class="map-spatial-anchor-editor">
              <div class="map-typed-dynamic-heading"><strong>地图落点预览</strong><span>{{ editor.state.item?.evidence_text ? '正文证据已锁定' : '缺少正文证据' }}</span></div>
              <p class="map-muted-text">{{ spatialMap.name || '当前地图' }} · {{ spatialMap.grid_width || '?' }}×{{ spatialMap.grid_height || '?' }} 格。落点只修改候选；采用前仍由服务端复核。</p>
              <div class="map-spatial-anchor-fields">
                <label>q 坐标<input id="map-object-edit-anchor-q" v-model="editor.state.anchorQ" class="form-input" inputmode="numeric" /></label>
                <label>r 坐标<input id="map-object-edit-anchor-r" v-model="editor.state.anchorR" class="form-input" inputmode="numeric" /></label>
                <button id="map-anchor-use-location" class="btn btn-sm" type="button" @click="editor.useLocationCenter">使用地点中心</button>
                <button id="map-anchor-clear" class="btn btn-sm" type="button" @click="editor.clearSpatialHex">清除精确格</button>
              </div>
              <div id="map-spatial-anchor-preview" class="map-spatial-anchor-preview" role="img" aria-label="候选地图落点预览">
                <svg viewBox="0 0 240 132" aria-hidden="true" preserveAspectRatio="none">
                  <rect x="1" y="1" width="238" height="130" rx="8" />
                  <circle v-for="point in locationPoints" :key="point.id" class="map-anchor-location-dot" :cx="point.x" :cy="point.y" r="2.5"><title>{{ point.name }}</title></circle>
                  <g v-if="candidatePoint" class="map-anchor-candidate"><circle :cx="candidatePoint.x" :cy="candidatePoint.y" r="6" /><text :x="candidatePoint.x + 9" :y="candidatePoint.y + 4">候选</text></g>
                </svg>
              </div>
              <p id="map-spatial-anchor-message" class="map-muted-text">{{ candidatePoint ? `候选落点 q:${editor.state.anchorQ}, r:${editor.state.anchorR}` : '尚未指定精确 hex；可以保留地点级锚点。' }}</p>
            </section>
            <div class="map-object-readonly-context" role="note" aria-label="来源信息（只读）"><div><strong>时间：</strong>{{ editor.state.item?.time_label || '时间未确定' }}</div><div><strong>位置：</strong>{{ editor.state.item?.location_label || editor.state.item?.spatial_anchor_label || '位置未确定' }}</div><div><strong>证据：</strong>{{ mapSourceText(editor.state.item?.evidence_text || editor.state.item?.source_summary || '未提供正文证据') }}</div><div><strong>来源：</strong>{{ mapSourceText(editor.state.item?.source_ref?.workflow || editor.state.item?.source_ref?.source || editor.state.item?.source_workflow || '来源工作流已记录') }}</div></div>
            <section v-if="editor.state.legacy" class="map-typed-dynamic-editor" role="note"><div class="map-typed-dynamic-heading"><strong>结构化动态</strong><span>旧版数据</span></div><p class="map-legacy-dynamic-note">该记录仍使用旧版格式，本批只读保留；请等待后续结构化迁移后再编辑动态值。</p></section>
            <section v-else class="map-typed-dynamic-editor">
              <div class="map-typed-dynamic-heading"><strong>结构化动态</strong><span>已结构化</span></div>
              <div class="form-group"><label>动态类型</label><select id="map-object-edit-value-type" v-model="editor.state.value.type" class="form-select"><option v-for="[value, label] in MAP_DYNAMIC_TYPES" :key="value" :value="value">{{ label }}</option></select></div>
              <template v-if="editor.state.value.type === 'location'"><div class="form-group"><label>所在地点</label><select id="map-typed-location-entity" v-model="editor.state.value.location_entity_id" class="form-select"><option :value="null">未指定地点</option><option v-for="item in locationOptions" :key="item.id" :value="item.id">{{ item.name }}</option></select></div><div v-if="editor.state.item?.proposal_type !== 'event_location'" class="form-group"><label>使用线路（可选）</label><select id="map-typed-location-path" v-model="editor.state.value.path_id" class="form-select"><option :value="null">未指定线路</option><option v-for="item in editor.state.paths" :key="item.id" :value="item.id">{{ item.name }}</option></select></div><div class="form-group"><label>移动方式</label><select id="map-typed-location-mode" v-model="editor.state.value.movement_mode" class="form-select"><option v-for="value in MOVEMENT_MODES" :key="value" :value="value">{{ movementLabel(value) }}</option></select></div><div class="form-group"><label>位置状态</label><input id="map-typed-location-state" v-model="editor.state.value.state" class="form-input" maxlength="64" /></div></template>
              <template v-else-if="editor.state.value.type === 'route_state'"><div class="form-group"><label>线路</label><select id="map-typed-route-path" v-model="editor.state.value.path_id" class="form-select"><option :value="null">未指定线路</option><option v-for="item in editor.state.paths" :key="item.id" :value="item.id">{{ item.name }}</option></select></div><div class="form-group"><label>线路状态</label><select id="map-typed-route-state" v-model="editor.state.value.state" class="form-select"><option value="open">开放</option><option value="restricted">受限</option><option value="blocked">阻断</option></select></div><div class="form-group"><label>原因（可选）</label><textarea id="map-typed-route-reason" v-model="editor.state.value.reason" class="form-textarea" rows="2" maxlength="1000" /></div></template>
              <template v-else-if="editor.state.value.type === 'status'"><div class="form-group"><label>状态字段</label><input id="map-typed-status-key" v-model="editor.state.value.field_key" class="form-input" maxlength="128" /></div><div class="map-typed-scalar-row"><div class="form-group"><label>值类型</label><select id="map-typed-status-value-type" v-model="editor.state.scalarType" class="form-select"><option value="string">文字</option><option value="number">数字</option><option value="boolean">是/否</option><option value="null">未设置</option></select></div><div class="form-group"><label>当前值</label><input id="map-typed-status-value" v-model="editor.state.value.value" class="form-input" /></div></div></template>
              <template v-else-if="editor.state.value.type === 'boundary'"><div class="form-group"><label>控制者</label><select id="map-typed-boundary-controller" v-model="editor.state.value.controller_entity_id" class="form-select"><option :value="null">请选择控制者</option><option v-for="item in editor.state.entities" :key="item.id" :value="item.id">{{ item.name }}</option></select></div><HexEditor v-model="editor.state.hexText" class="map-boundary-spatial-field" label="范围格（每行 q,r）" id="map-typed-boundary-hexes" /><p class="map-boundary-mobile-handoff">当前范围已保留；势力 hex 绘制与精修请在桌面端继续。</p></template>
              <template v-else-if="editor.state.value.type === 'resource'"><div class="form-group"><label>资源名称/键</label><input id="map-typed-resource-key" v-model="editor.state.value.resource_key" class="form-input" /></div><div class="form-group"><label>控制者（可选）</label><select id="map-typed-resource-controller" v-model="editor.state.value.controller_entity_id" class="form-select"><option :value="null">未指定</option><option v-for="item in editor.state.entities" :key="item.id" :value="item.id">{{ item.name }}</option></select></div><div class="form-group"><label>状态（可选）</label><input id="map-typed-resource-status" v-model="editor.state.value.status" class="form-input" /></div><div class="form-group"><label>数量（可选）</label><input id="map-typed-resource-amount" v-model="editor.state.value.amount" class="form-input" /></div></template>
              <template v-else-if="editor.state.value.type === 'terrain'"><div class="form-group"><label>地形名称/键</label><input id="map-typed-terrain-key" v-model="editor.state.value.terrain_key" class="form-input" /></div><div class="form-group"><label>地形状态</label><input id="map-typed-terrain-state" v-model="editor.state.value.state" class="form-input" /></div><HexEditor v-model="editor.state.hexText" label="影响范围格（每行 q,r）" id="map-typed-terrain-hexes" /></template>
              <template v-else-if="editor.state.value.type === 'crisis'"><div class="form-group"><label>危机名称/键</label><input id="map-typed-crisis-key" v-model="editor.state.value.crisis_key" class="form-input" /></div><div class="form-group"><label>危机强度（0–5）</label><input id="map-typed-crisis-severity" v-model="editor.state.value.severity" class="form-input" type="number" min="0" max="5" /></div><HexEditor v-model="editor.state.hexText" label="扩散范围格（每行 q,r）" id="map-typed-crisis-hexes" /></template>
              <template v-else-if="editor.state.value.type === 'semantic'"><div class="form-group"><label>关联类型</label><input id="map-typed-semantic-relation" v-model="editor.state.value.relation_type" class="form-input" /></div><div class="form-group"><label>相关对象</label><select id="map-typed-semantic-entities" v-model="editor.state.value.related_entity_ids" class="form-select" multiple><option v-for="item in editor.state.entities" :key="item.id" :value="item.id">{{ item.name }}</option></select></div><div class="form-group"><label>关联说明（可选）</label><textarea id="map-typed-semantic-summary" v-model="editor.state.value.summary" class="form-textarea" rows="3" maxlength="2000" /></div></template>
            </section>
          </template>
        </fieldset>
        <footer><button type="button" class="btn" :disabled="editor.state.saving" @click="requestClose">取消</button><button type="button" class="btn btn-primary" :disabled="editor.state.saving || editor.state.legacy" @click="editor.save">{{ editor.state.saving ? '保存中…' : '保存' }}</button></footer>
      </section>
    </div>
  </Teleport>
</template>

<script setup>
import { computed, defineComponent, h } from "vue"
import { useModalDialog } from "../../../composables/useModalDialog.js"
import { MAP_DYNAMIC_TYPES } from "../useMapDynamicEditor.js"
import { mapSourceText } from "../mapModel.js"
const props = defineProps({ editor: { type: Object, required: true } })
const requestClose = () => props.editor.close()
const { overlayRef, dialogRef, onKeydown, onFocusin } = useModalDialog({ isOpen: () => props.editor.state.open, requestClose, canClose: () => !props.editor.state.saving })
const MOVEMENT_MODES = ["walk", "ride", "vehicle", "rail", "water", "flight", "teleport", "unknown"]
function movementLabel(value) { return ({ walk: "步行", ride: "骑乘", vehicle: "载具", rail: "轨道", water: "水路", flight: "飞行", teleport: "传送", unknown: "未知" })[value] }
const locationOptions = computed(() => props.editor.state.entities.filter((item) => item.entityType === "location"))
const spatialMap = computed(() => props.editor.state.spatialContext?.map || {})
function point(value, max, extent) { return 8 + (Math.max(0, Math.min(Math.max(0, max - 1), Number(value))) / Math.max(1, max - 1)) * (extent - 16) }
const locationPoints = computed(() => (props.editor.state.spatialContext?.locationAnchors || []).slice(0, 80).map((item) => ({ id: item.location_entity_id, name: item.name || "地点", x: point(item.q, Number(spatialMap.value.grid_width || 1), 240), y: point(item.r, Number(spatialMap.value.grid_height || 1), 132) })))
const candidatePoint = computed(() => {
  const q = Number(props.editor.state.anchorQ)
  const r = Number(props.editor.state.anchorR)
  if (String(props.editor.state.anchorQ ?? "").trim() === "" || String(props.editor.state.anchorR ?? "").trim() === "" || !Number.isInteger(q) || !Number.isInteger(r)) return null
  return { x: point(q, Number(spatialMap.value.grid_width || 1), 240), y: point(r, Number(spatialMap.value.grid_height || 1), 132) }
})
const HexEditor = defineComponent({ props: { modelValue: String, label: String, id: String }, emits: ["update:modelValue"], setup(props, { emit }) { return () => h("div", { class: "form-group" }, [h("label", { for: props.id }, props.label), h("textarea", { id: props.id, class: "form-textarea", rows: 4, value: props.modelValue, onInput: (event) => emit("update:modelValue", event.target.value) })]) } })
</script>

<style scoped>
.vue-map-dialog-backdrop { position: fixed; inset: 0; z-index: 1100; display: grid; place-items: center; padding: 24px; background: rgba(2, 6, 23, .68); }
.vue-map-dialog { display: grid; grid-template-rows: auto minmax(0, 1fr) auto; width: min(94vw, 760px); max-height: 92vh; overflow: hidden; border: 1px solid var(--border-color); border-radius: var(--radius-lg); background: var(--surface-primary); box-shadow: var(--shadow-xl); }
.vue-map-dialog > header, .vue-map-dialog > footer { display: flex; align-items: center; justify-content: space-between; gap: var(--space-3); padding: var(--space-4); border-bottom: 1px solid var(--border-color); }
.vue-map-dialog > footer { justify-content: flex-end; border-top: 1px solid var(--border-color); border-bottom: 0; }
.vue-map-dialog__body { overflow: auto; padding: var(--space-4); min-inline-size: 0; border: 0; margin: 0; }
@media (max-width: 390px) {
  .vue-map-dialog > header .btn { min-width: 40px; min-height: 40px; }
  .vue-map-dialog > footer .btn { min-height: 44px; }
}
</style>
