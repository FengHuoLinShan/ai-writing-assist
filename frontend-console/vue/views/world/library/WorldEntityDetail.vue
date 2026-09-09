<script setup>
import { computed, onBeforeUnmount, reactive, ref, watch } from "vue"
import { displayStateBadgeClass, worldAssetDisplay } from "../../../../shared/assetDisplayState.js"
import { getApi, getConfirm, getToast } from "../../../bridge/index.js"
import { updateEntityWithBaseline } from "../logic/worldEntityOps.js"
import TargetedCompletionPanel from "../../../components/TargetedCompletionPanel.vue"

const props = defineProps({
  entity: { type: Object, required: true },
  projectId: { type: String, required: true },
  typeLabel: { type: String, default: "人物或设定" },
  aliasesOpen: { type: Boolean, default: false },
})
const emit = defineEmits(["back", "edit", "create-alias", "edit-alias", "create-task", "profile-dirty", "refresh", "impact-preview"])
const aliases = computed(() => (props.entity?.content_json?.aliases || []).map((item) => (
  typeof item === "string" ? { alias: item } : item
)).filter((item) => String(item?.alias || "").trim()))
const display = computed(() => worldAssetDisplay(props.entity))
const isCharacter = computed(() => props.entity?.entity_type === "character")
const profileOpen = ref(false)
const profileLoading = ref(false)
const profileSaving = ref(false)
const profileLoaded = ref(false)
const profileError = ref("")
const profileFields = [
  ["role", "角色定位", "例如：主角、导师或对手"],
  ["appearance", "外貌", "最容易被认出的外在特征"],
  ["personality", "性格", "稳定倾向与压力下的反应"],
  ["desire", "渴望／长期目标", "真正想获得或守住什么"],
  ["fear", "恐惧／软肋", "最害怕失去或面对什么"],
  ["secret", "秘密（仅作者可见）", "暂时不应交给读者或其他人物的信息"],
  ["current_state", "当前状态", "此刻的处境与变化"],
  ["voice_style", "语言风格", "说话节奏、措辞和习惯"],
]
const profileForm = reactive(Object.fromEntries(profileFields.map(([key]) => [key, ""])))
const profileBaseline = ref(JSON.stringify(profileForm))
const profileBaselineUpdatedAt = ref(null)
const profileDirty = computed(() => profileLoaded.value && JSON.stringify(profileForm) !== profileBaseline.value)
let profileGeneration = 0

// ---- 基本资料就地编辑：名称 / 概要 / 公开信息 / 作者秘密 ----
const BASIC_FIELDS = [
  ["name", "名称", "对象的名字"],
  ["summary", "概要", "一句话说明它是什么"],
  ["public_info", "公开信息", "读者与其他人物可以知道的内容"],
  ["hidden_truth", "作者秘密", "仅作者可见的真相或设定"],
]
const basicEditing = ref(false)
const basicSaving = ref(false)
const basicError = ref("")
const basicConflict = ref(null)
const basicForm = reactive(Object.fromEntries(BASIC_FIELDS.map(([key]) => [key, ""])))
const basicBaseline = ref(JSON.stringify(basicForm))
const basicBaselineUpdatedAt = ref(null)
let basicGeneration = 0

function fillBasicForm(entity = props.entity) {
  for (const [key] of BASIC_FIELDS) basicForm[key] = entity?.[key] || ""
  basicBaseline.value = JSON.stringify(basicForm)
  basicBaselineUpdatedAt.value = entity?.updated_at || null
}

const basicDirty = computed(() => basicEditing.value && JSON.stringify(basicForm) !== basicBaseline.value)

function startBasicEdit() {
  basicConflict.value = null
  basicError.value = ""
  fillBasicForm()
  basicEditing.value = true
}

function cancelBasicEdit() {
  if (basicDirty.value && !getConfirm()?.("有未保存的修改，确定取消吗？")) return
  basicEditing.value = false
  basicConflict.value = null
  basicError.value = ""
  fillBasicForm()
}

async function saveBasicEdit() {
  if (basicSaving.value || !basicDirty.value) return
  const generation = ++basicGeneration
  const entityId = props.entity.id || props.entity.entity_id
  basicSaving.value = true
  basicError.value = ""
  basicConflict.value = null
  try {
    const payload = {}
    for (const [key] of BASIC_FIELDS) payload[key] = basicForm[key]
    payload.expected_updated_at = basicBaselineUpdatedAt.value
    const updated = await updateEntityWithBaseline(
      { ...props.entity, updated_at: basicBaselineUpdatedAt.value },
      payload,
      props.projectId,
    )
    if (generation !== basicGeneration) return
    basicBaselineUpdatedAt.value = updated?.updated_at || null
    for (const [key] of BASIC_FIELDS) basicForm[key] = updated?.[key] ?? basicForm[key]
    basicBaseline.value = JSON.stringify(basicForm)
    basicEditing.value = false
    getToast()("基本资料已保存", "success")
    emit("refresh", entityId)
  } catch (error) {
    if (generation !== basicGeneration) return
    if (error?.status === 409 && ["edit_baseline_required", "edit_baseline_stale"].includes(error?.body?.error)) {
      try {
        const server = await getApi().world.getEntity(entityId, props.projectId, { cache: "no-store" })
        if (generation !== basicGeneration) return
        basicConflict.value = { server, message: error.message }
      } catch {
        if (generation === basicGeneration) basicConflict.value = { server: null, message: error.message }
      }
    } else {
      basicError.value = error?.message || "基本资料保存失败，输入已保留"
    }
  } finally {
    if (generation === basicGeneration) basicSaving.value = false
  }
}

function adoptServerEntity() {
  const server = basicConflict.value?.server
  basicConflict.value = null
  if (!server) {
    basicError.value = "暂时读不到服务器版本，请稍后重试"
    return
  }
  fillBasicForm(server)
  basicEditing.value = true
  getToast()("已载入服务器版本；在此基础上修改后再保存", "info")
}

function keepLocalEntity() {
  const server = basicConflict.value?.server
  if (!server) {
    basicError.value = "暂时读不到服务器版本，请稍后重试"
    return
  }
  basicBaselineUpdatedAt.value = server.updated_at || null
  basicConflict.value = null
  getToast()("已保留输入，再次保存将更新刚才核对的服务器版本", "info")
}

function fillProfile(value = {}) {
  for (const [key] of profileFields) profileForm[key] = value[key] || ""
  profileBaseline.value = JSON.stringify(profileForm)
  profileBaselineUpdatedAt.value = value?.updated_at || null
}

async function openProfile() {
  profileOpen.value = true
  if (profileLoaded.value || profileLoading.value) return
  const generation = ++profileGeneration
  profileLoading.value = true
  profileError.value = ""
  try {
    const value = await getApi().world.getCharacter(props.entity.id || props.entity.entity_id, props.projectId)
    if (generation === profileGeneration) {
      fillProfile(value)
      profileLoaded.value = true
    }
  } catch (error) {
    if (generation === profileGeneration) profileError.value = error?.message || "人物档案暂时无法读取"
  } finally {
    if (generation === profileGeneration) profileLoading.value = false
  }
}

async function saveProfile() {
  if (profileSaving.value) return
  const generation = ++profileGeneration
  profileSaving.value = true
  profileError.value = ""
  const submittedForm = JSON.stringify(profileForm)
  try {
    const payload = Object.fromEntries(profileFields.map(([key]) => [key, profileForm[key]]))
    payload.expected_updated_at = profileBaselineUpdatedAt.value
    const value = await getApi().world.updateCharacter(props.entity.id || props.entity.entity_id, payload, props.projectId)
    if (generation !== profileGeneration) return
    if (JSON.stringify(profileForm) === submittedForm) fillProfile(value)
    else {
      profileBaseline.value = JSON.stringify(Object.fromEntries(profileFields.map(([key]) => [key, value?.[key] ?? payload[key]])))
      profileBaselineUpdatedAt.value = value?.updated_at || null
    }
    getToast()(profileDirty.value ? "上一版人物档案已保存，新输入仍待保存" : "人物档案已保存", "success")
  } catch (error) {
    if (generation === profileGeneration) profileError.value = error?.message || "人物档案保存失败，输入已保留"
  } finally {
    if (generation === profileGeneration) profileSaving.value = false
  }
}

watch([profileDirty, basicDirty], ([profile, basic]) => emit("profile-dirty", Boolean(profile || basic)), { immediate: true })
watch(() => props.entity?.id || props.entity?.entity_id, () => {
  basicGeneration += 1
  basicSaving.value = false
  basicEditing.value = false
  basicConflict.value = null
  basicError.value = ""
  fillBasicForm()
  profileGeneration += 1
  profileOpen.value = false
  profileLoading.value = false
  profileSaving.value = false
  profileLoaded.value = false
  profileError.value = ""
  fillProfile()
})
onBeforeUnmount(() => { basicGeneration += 1; profileGeneration += 1; emit("profile-dirty", false) })
</script>

<template>
  <article class="world-entity-detail" aria-labelledby="world-entity-detail-title">
    <header class="world-entity-detail__header">
      <div>
        <button type="button" class="btn btn-sm btn-ghost world-entity-detail__back" @click="emit('back')">← 返回资料库</button>
        <h2 id="world-entity-detail-title">{{ entity.name || '未命名人物或设定' }}</h2>
        <p><span>{{ typeLabel }}</span> · <span class="badge" :class="displayStateBadgeClass(display.displayState)">{{ display.label }}</span></p>
      </div>
      <div class="world-entity-detail__actions">
        <button type="button" class="btn btn-sm btn-ghost" data-action="world-entity-impact-preview" @click="emit('impact-preview')">影响预演</button>
        <button type="button" class="btn btn-sm" @click="emit('create-task')">添加到计划中的任务</button>
        <button type="button" class="btn btn-sm btn-primary" @click="emit('edit')">编辑资料</button>
      </div>
    </header>
    <section class="world-entity-basic" aria-label="基本资料">
      <header class="world-entity-basic__header">
        <h3>基本资料</h3>
        <button v-if="!basicEditing" type="button" class="btn btn-sm" data-action="world-entity-basic-edit" @click="startBasicEdit">就地编辑</button>
        <template v-else>
          <button type="button" class="btn btn-sm btn-ghost" data-action="world-entity-basic-cancel" :disabled="basicSaving" @click="cancelBasicEdit">取消</button>
          <button type="button" class="btn btn-sm btn-primary" data-action="world-entity-basic-save" :disabled="basicSaving || !basicDirty" @click="saveBasicEdit">{{ basicSaving ? '保存中…' : '保存' }}</button>
        </template>
      </header>

      <template v-if="!basicEditing">
        <dl class="world-entity-basic__facts">
          <div><dt>名称</dt><dd>{{ entity.name || '未命名' }}</dd></div>
          <div><dt>概要</dt><dd>{{ entity.summary || entity.public_info || '还没有概要，可以编辑后补充。' }}</dd></div>
          <div v-if="entity.public_info"><dt>公开信息</dt><dd>{{ entity.public_info }}</dd></div>
          <div v-if="entity.hidden_truth" class="world-entity-basic__secret"><dt>作者秘密</dt><dd>{{ entity.hidden_truth }}</dd></div>
        </dl>
      </template>

      <div v-else class="world-entity-basic__form" :aria-busy="basicSaving">
        <p v-if="basicError" class="error-card" role="alert">{{ basicError }}</p>
        <div v-if="basicConflict" class="world-entity-basic__conflict" role="alert" data-conflict="basic">
          <p>{{ basicConflict.message }}</p>
          <dl v-if="basicConflict.server">
            <div><dt>服务器版本 · 名称</dt><dd>{{ basicConflict.server.name || '（空）' }}</dd></div>
            <div><dt>服务器版本 · 概要</dt><dd>{{ basicConflict.server.summary || '（空）' }}</dd></div>
            <div><dt>服务器版本 · 更新时间</dt><dd>{{ basicConflict.server.updated_at || '未知' }}</dd></div>
          </dl>
          <div class="world-entity-basic__conflict-actions">
            <button type="button" class="btn btn-sm" data-action="world-entity-basic-adopt-server" @click="adoptServerEntity">采用服务器版本</button>
            <button type="button" class="btn btn-sm btn-ghost" data-action="world-entity-basic-keep-mine" @click="keepLocalEntity">保留我的修改</button>
          </div>
        </div>
        <label v-for="[key, label, hint] in BASIC_FIELDS" :key="key" class="world-entity-basic__field">
          <span>{{ label }}</span>
          <textarea
            v-if="key !== 'name'"
            v-model="basicForm[key]"
            :data-basic-field="key"
            rows="2"
            :placeholder="hint"
            :disabled="basicSaving"
          ></textarea>
          <input
            v-else
            v-model="basicForm[key]"
            :data-basic-field="key"
            type="text"
            maxlength="255"
            :placeholder="hint"
            :disabled="basicSaving"
          >
        </label>
        <p class="world-entity-basic__hint">保存需要明确点击“保存”；失焦不会修改已采用事实。</p>
      </div>
    </section>
    <TargetedCompletionPanel :project-id="projectId" :entity-id="entity.id || entity.entity_id" :initial-name="entity.name || ''" @applied="emit('refresh', entity.id || entity.entity_id)" />
    <section v-if="isCharacter" class="world-character-profile">
      <header><div><h3>人物档案</h3><p>按需补充人物动机、状态和声音；名称与别名仍在基本资料中管理。</p></div><button type="button" class="btn btn-sm" @click="profileOpen ? (profileOpen = false) : openProfile()">{{ profileOpen ? '收起' : '完善人物档案' }}</button></header>
      <div v-if="profileOpen" class="world-character-profile__form" :aria-busy="profileLoading || profileSaving">
        <p v-if="profileLoading" role="status">正在读取人物档案…</p>
        <div v-else-if="profileError && !profileLoaded" class="error-card" role="alert">
          <p>{{ profileError }}</p>
          <button type="button" class="btn btn-sm" @click="openProfile">重新读取</button>
        </div>
        <template v-else-if="profileLoaded">
          <p v-if="profileError" class="field-error" role="alert">{{ profileError }}</p>
          <label v-for="field in profileFields" :key="field[0]"><span>{{ field[1] }}</span><textarea v-model="profileForm[field[0]]" rows="2" :placeholder="field[2]" /></label>
          <div class="world-character-profile__actions"><button type="button" class="btn btn-primary" :disabled="profileSaving || !profileDirty" @click="saveProfile">{{ profileSaving ? '保存中…' : '保存人物档案' }}</button></div>
        </template>
      </div>
    </section>
    <details :open="aliasesOpen || undefined" class="world-entity-detail__aliases">
      <summary>别名 <span>{{ aliases.length }}</span></summary>
      <ul v-if="aliases.length">
        <li v-for="item in aliases" :key="item.alias">
          <span>{{ item.alias }}</span>
          <button type="button" class="btn btn-sm btn-ghost" @click="emit('edit-alias', item.alias)">编辑</button>
        </li>
      </ul>
      <p v-else>还没有别名。别名会附着在这一对象上，不创建重复资料。</p>
      <button type="button" class="btn btn-sm" @click="emit('create-alias')">添加别名</button>
    </details>
  </article>
</template>

<style scoped>
.world-entity-detail { display: grid; gap: 20px; }
.world-entity-basic { display: grid; gap: 10px; }
.world-entity-basic__header { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.world-entity-basic__header h3 { margin: 0; }
.world-entity-basic__facts { display: grid; gap: 8px; margin: 0; }
.world-entity-basic__facts > div { display: grid; grid-template-columns: 88px minmax(0, 1fr); gap: 10px; }
.world-entity-basic__facts dt { color: var(--text-muted); }
.world-entity-basic__facts dd { margin: 0; white-space: pre-wrap; }
.world-entity-basic__secret dd { color: var(--text-secondary); }
.world-entity-basic__form { display: grid; gap: 10px; }
.world-entity-basic__field { display: grid; gap: 4px; }
.world-entity-basic__field span { color: var(--text-secondary); font-size: var(--text-sm); }
.world-entity-basic__field input, .world-entity-basic__field textarea { width: 100%; }
.world-entity-basic__hint { margin: 0; color: var(--text-muted); font-size: 12px; }
.world-entity-basic__conflict { display: grid; gap: 8px; border: 1px solid var(--border); border-radius: var(--radius-md); background: var(--bg-panel); padding: 10px 12px; }
.world-entity-basic__conflict p { margin: 0; }
.world-entity-basic__conflict dl { display: grid; gap: 4px; margin: 0; }
.world-entity-basic__conflict dl > div { display: grid; grid-template-columns: 140px minmax(0, 1fr); gap: 8px; }
.world-entity-basic__conflict dt { color: var(--text-muted); }
.world-entity-basic__conflict dd { margin: 0; }
.world-entity-basic__conflict-actions { display: flex; gap: 8px; flex-wrap: wrap; }
@media (max-width: 760px) {
  .world-entity-basic__header .btn, .world-entity-basic__conflict-actions .btn { min-height: 44px; }
  .world-entity-basic__field input, .world-entity-basic__field textarea { min-height: 44px; }
}
.world-entity-detail__header { display: flex; align-items: start; justify-content: space-between; gap: 20px; border-bottom: 1px solid var(--border); padding-bottom: 16px; }
.world-entity-detail__header h2 { margin: 12px 0 6px; }
.world-entity-detail__header p { margin: 0; color: var(--text-muted); }
.world-entity-detail__actions { display: flex; flex-wrap: wrap; justify-content: end; gap: 8px; }
.world-entity-detail__aliases { border: 1px solid var(--border); border-radius: var(--radius-md); padding: 12px; }
.world-entity-detail__aliases summary { cursor: pointer; font-weight: 600; }
.world-entity-detail__aliases ul { display: grid; gap: 6px; padding: 0; list-style: none; }
.world-entity-detail__aliases li { display: flex; min-height: 40px; align-items: center; justify-content: space-between; gap: 12px; }
.world-character-profile { border: 1px solid var(--border); border-radius: var(--radius-md); padding: 14px; }
.world-character-profile > header { display: flex; align-items: start; justify-content: space-between; gap: 16px; }
.world-character-profile h3, .world-character-profile p { margin: 0; }
.world-character-profile p { margin-top: 4px; color: var(--text-muted); }
.world-character-profile__form { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; margin-top: 16px; }
.world-character-profile__form > p, .world-character-profile__actions { grid-column: 1 / -1; }
.world-character-profile__form label { display: grid; gap: 6px; }
.world-character-profile__form textarea { width: 100%; min-height: 76px; }
.world-character-profile__actions { display: flex; justify-content: flex-end; }
@media (max-width: 760px) {
  .world-entity-detail__header { flex-direction: column; }
  .world-entity-detail__actions { width: 100%; justify-content: stretch; }
  .world-entity-detail__actions .btn, .world-entity-detail__aliases .btn { min-height: 44px; }
  .world-character-profile > header { flex-direction: column; }
  .world-character-profile > header .btn { width: 100%; min-height: 44px; }
  .world-character-profile__form { grid-template-columns: minmax(0, 1fr); }
  .world-character-profile__actions { grid-column: 1; }
  .world-character-profile__actions .btn { width: 100%; min-height: 44px; }
}
@media (max-width: 390px) {
  .world-entity-detail__back, .world-entity-detail__aliases summary { min-height: 44px; }
  .world-entity-detail__aliases summary { padding-block: 10px; }
}
</style>
