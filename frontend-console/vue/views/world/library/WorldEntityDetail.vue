<script setup>
import { computed, onBeforeUnmount, reactive, ref, watch } from "vue"
import { displayStateBadgeClass, worldAssetDisplay } from "../../../../shared/assetDisplayState.js"
import { getApi, getConfirm, getLocalDraftAccountScope, getLocalDraftStorage, getPublicDemoReadOnly, getRouter, getToast, openProjectAssistant } from "../../../bridge/index.js"
import { readWritingObjectReturn } from "../../../shared/writingObjectReturn.js"
import { clearLocalDraftBackup, readLocalDraftBackup, writeLocalDraftBackup } from "../../../shared/localDraftBackup.js"
import { updateEntityWithBaseline } from "../logic/worldEntityOps.js"
import { showRelationCreateForm, showRelationReviewEditForm, syncRelationsAliasesRegistry } from "../logic/worldRelationsAliasesOps.js"
import WorldEntityImage from "../components/WorldEntityImage.vue"
import WorldEntityRevisionHistory from "./WorldEntityRevisionHistory.vue"
import WorldObjectDossierEditor from "./WorldObjectDossierEditor.vue"
import WorldRelationMaintenance from "./WorldRelationMaintenance.vue"
import TargetedCompletionPanel from "../../../components/TargetedCompletionPanel.vue"
import StoryFactTimelinePanel from "../../outline/components/StoryFactTimelinePanel.vue"

const props = defineProps({
  entity: { type: Object, required: true },
  projectId: { type: String, required: true },
  typeLabel: { type: String, default: "人物或设定" },
  aliasesOpen: { type: Boolean, default: false },
  historyOpen: { type: Boolean, default: false },
  highlightRevisionId: { type: String, default: "" },
})
const emit = defineEmits(["back", "edit", "create-alias", "edit-alias", "create-task", "profile-dirty", "refresh", "impact-preview"])
const aliases = computed(() => (props.entity?.content_json?.aliases || []).map((item) => (
  typeof item === "string" ? { alias: item } : item
)).filter((item) => String(item?.alias || "").trim()))
const display = computed(() => worldAssetDisplay(props.entity))
const detailSection = ref(props.historyOpen ? 'history' : 'overview')
const detailSections = [{ key: 'overview', label: '概览' }, { key: 'dossier', label: '设定档案' }, { key: 'relations', label: '关系' }, { key: 'history', label: '经历与来源' }]
function onSectionKeydown(event, index) {
  const directions = { ArrowRight: (index + 1) % 4, ArrowLeft: (index + 3) % 4, Home: 0, End: 3 }
  if (!(event.key in directions)) return
  event.preventDefault()
  const next = directions[event.key]
  detailSection.value = detailSections[next].key
  event.currentTarget.parentElement.children[next]?.focus()
}
async function addRelation() {
  if (publicDemoReadOnly.value) return
  const id = props.entity.id || props.entity.entity_id
  const projectId = props.projectId
  try {
    const catalog = await getApi().world.getReviewTypeCatalog()
    if (projectId !== props.projectId || id !== (props.entity.id || props.entity.entity_id)) return
    await showRelationCreateForm(catalog, { source_id: id, source_name: props.entity.name })
  } catch (error) { getToast()(error.message || '暂时无法准备关系表单。', 'warning') }
}
function searchSourceMentions() {
  getRouter()?.navigate('rag', 'search', true, new URLSearchParams({ q: props.entity.name || '' }))
}
const writingReturn = computed(() => readWritingObjectReturn(props.projectId, props.entity.id || props.entity.entity_id))
function returnToWriting() {
  const location = writingReturn.value
  if (!location) return
  getRouter()?.navigate('writing', null, true, new URLSearchParams({ chapter_index: location.chapterIndex, return_from_object: location.entityId }))
}
const isCharacter = computed(() => props.entity?.entity_type === "character")
const related = ref([]), relatedError = ref(''), infoLoading = ref(false)
const showRemovedRelations = ref(false)
let infoEpoch = 0
async function loadInfo() {
  const token = ++infoEpoch
  infoLoading.value = true; relatedError.value = ''
  try {
    const id = props.entity.id || props.entity.entity_id
    const result = await getApi().world.getEntityRelations(id, props.projectId, { includeRemoved: showRemovedRelations.value })
    if (token !== infoEpoch) return
    related.value = result.items || []; syncRelationsAliasesRegistry({ relations: related.value })
  } catch (err) { if (token === infoEpoch) relatedError.value = err.message || '资料读取失败，请重新展开重试' }
  finally { if (token === infoEpoch) infoLoading.value = false }
}
function onRelationChanged(receipt) {
  if (receipt.action === 'remove') showRemovedRelations.value = true
  void loadInfo()
}
watch(() => [props.projectId, props.entity.id || props.entity.entity_id], () => { infoEpoch += 1; related.value = []; relatedError.value = ''; infoLoading.value = false; showRemovedRelations.value = false })
onBeforeUnmount(() => { infoEpoch += 1 })
const profileOpen = ref(false)
const worldDossierOpen = ref(false)
const worldDossierMounted = ref(false)
function toggleDossier(event) {
  worldDossierOpen.value = event.target.open
  if (event.target.open) worldDossierMounted.value = true
}
const dossierDirty = ref(false)
const publicDemoReadOnly = computed(() => getPublicDemoReadOnly())

async function askAboutEntity() {
  if (publicDemoReadOnly.value) return
  if (profileDirty.value || basicDirty.value || dossierDirty.value) {
    getToast()("先保存或取消未保存的资料，再按已保存版本打开助手讨论。", "warning")
    return
  }
  const id = props.entity?.id || props.entity?.entity_id
  if (!id || !props.entity?.updated_at) {
    getToast()("无法核对对象的已保存版本；请重新读取后再提问。", "warning")
    return
  }
  try {
    await openProjectAssistant({
      projectId: props.projectId,
      context: {
        page: "world",
        scope: "current",
        target: { target_type: "world_entity", target_id: id },
        focus_ref: { kind: "entity", entity_id: id, updated_at: props.entity.updated_at },
        focus_label: "对象：" + (props.entity.name || "未命名") + " · " + props.typeLabel,
      },
    })
  } catch (error) {
    getToast()(error?.message || "暂时无法打开对象讨论。", "error")
  }
}

async function askAboutRelation(relation) {
  if (publicDemoReadOnly.value) return
  if (profileDirty.value || basicDirty.value || dossierDirty.value) {
    getToast()("先保存或取消未保存的资料，再按已保存版本打开助手讨论。", "warning")
    return
  }
  const entityId = props.entity?.id || props.entity?.entity_id
  if (!entityId || !relation?.id || !relation?.updated_at) {
    getToast()("无法核对这条关系的已保存版本；请重新读取关系后再提问。", "warning")
    return
  }
  try {
    await openProjectAssistant({
      projectId: props.projectId,
      context: {
        page: "world",
        scope: "current",
        target: { target_type: "world_entity", target_id: entityId },
        focus_ref: {
          kind: "relation",
          entity_id: entityId,
          relation_id: relation.id,
          updated_at: relation.updated_at,
        },
        focus_label: "关系：" + (relation.source_name || "对象") + " → " + (relation.target_name || "相关对象"),
      },
    })
  } catch (error) {
    getToast()(error?.message || "暂时无法打开关系讨论。", "error")
  }
}
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
  ["weakness", "弱点", "可被利用或攻破的短板"],
  ["current_goal", "当前目标", "眼下正在推进的具体目标"],
  ["current_state", "当前状态", "此刻的处境与变化"],
  ["stance", "立场", "在核心冲突中站在哪一边"],
  ["voice_style", "语言风格", "说话节奏、措辞和习惯"],
  ["relationship_summary", "人际关系", "与关键人物的当前关系"],
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
const assistantContextReady = computed(() => !profileDirty.value && !basicDirty.value && !dossierDirty.value)
const basicBackupStatus = ref("")
const basicBackupError = ref("")
const basicBackupConflict = ref(null)
const basicBackupDraft = ref(null)
const basicBackupRecovering = ref(false)

function basicDraftScope() {
  const accountId = getLocalDraftAccountScope()
  const objectId = props.entity?.id || props.entity?.entity_id
  if (!accountId || !props.projectId || !objectId) return null
  return { accountId, projectId: String(props.projectId), objectId: String(objectId), section: "basic" }
}

function basicDraftPayload() {
  const baseline = JSON.parse(basicBaseline.value)
  return Object.fromEntries(BASIC_FIELDS
    .filter(([key]) => basicForm[key] !== baseline[key])
    .map(([key]) => [key, basicForm[key]]))
}

function applyBasicDraft(payload) {
  for (const [key] of BASIC_FIELDS) {
    if (typeof payload?.[key] === "string") basicForm[key] = payload[key]
  }
}

function persistBasicDraft() {
  const result = writeLocalDraftBackup(getLocalDraftStorage(), basicDraftScope(), basicBaselineUpdatedAt.value, basicDraftPayload())
  if (!result.ok) {
    basicBackupError.value = "本机草稿备份失败；当前输入仍留在页面中，请先复制需要保留的内容再离开。"
    basicBackupStatus.value = ""
    return
  }
  basicBackupDraft.value = result.draft
  basicBackupError.value = ""
  if (!basicBackupStatus.value) basicBackupStatus.value = "草稿已备份在此浏览器，尚未保存到作品。"
}

function clearBasicDraft(draft = basicBackupDraft.value) {
  if (!draft) return true
  const result = clearLocalDraftBackup(getLocalDraftStorage(), draft)
  if (!result.ok || result.changed) {
    basicBackupError.value = result.changed
      ? "本机草稿已在其他页面更新，因此没有清除；请重新读取后再处理。"
      : "作品已保存，但本机草稿未能清除；重新编辑时请核对版本。"
    return false
  }
  basicBackupDraft.value = null
  return true
}

function restoreBasicDraftOnEdit() {
  const result = readLocalDraftBackup(getLocalDraftStorage(), basicDraftScope())
  if (!result.ok) {
    basicBackupError.value = "无法读取此对象的本机草稿；原副本未删除。当前编辑仍可继续。"
    return
  }
  basicBackupError.value = ""
  if (!result.draft) {
    basicBackupDraft.value = null
    basicBackupStatus.value = "修改会自动备份在此浏览器；点击保存后才写入作品。"
    return
  }
  basicBackupDraft.value = result.draft
  if (result.draft.base_version === basicBaselineUpdatedAt.value) {
    applyBasicDraft(result.draft.payload)
    basicBackupStatus.value = "已恢复与当前服务器版本匹配的本机草稿；核对后点击保存。"
    return
  }
  basicBackupConflict.value = result.draft
  basicBackupStatus.value = "发现基于另一服务器版本的本机草稿，尚未覆盖当前资料。"
}

function startBasicEdit() {
  basicConflict.value = null
  basicError.value = ""
  basicBackupError.value = ""
  basicBackupStatus.value = ""
  basicBackupConflict.value = null
  fillBasicForm()
  basicEditing.value = true
  restoreBasicDraftOnEdit()
}

async function keepBasicBackup() {
  const draft = basicBackupConflict.value
  if (!draft || basicBackupRecovering.value) return
  const entityId = props.entity.id || props.entity.entity_id
  const projectId = props.projectId
  const generation = ++basicGeneration
  basicBackupRecovering.value = true
  basicBackupError.value = ""
  try {
    const server = await getApi().world.getEntity(entityId, projectId, { cache: "no-store" })
    if (generation !== basicGeneration || entityId !== (props.entity.id || props.entity.entity_id) || projectId !== props.projectId) return
    fillBasicForm(server)
    applyBasicDraft(draft.payload)
    basicBackupConflict.value = null
    basicBackupDraft.value = draft
    basicBackupStatus.value = "已保留本机输入并核对最新服务器版本；保存前仍可继续修改。"
  } catch (error) {
    if (generation === basicGeneration) basicBackupError.value = error?.message || "暂时无法核对服务器版本，本机草稿仍保留。"
  } finally {
    if (generation === basicGeneration) basicBackupRecovering.value = false
  }
}

function discardBasicBackup() {
  if (!basicBackupConflict.value) return
  if (!getConfirm()?.("确定放弃这份本机草稿吗？此操作不能撤销。")) return
  const removed = clearBasicDraft(basicBackupConflict.value)
  if (!removed) return
  basicBackupConflict.value = null
  basicBackupError.value = ""
  basicBackupStatus.value = "已放弃本机草稿；服务器资料保持不变。"
}

watch(basicForm, () => {
  if (!basicEditing.value || basicBackupConflict.value) return
  if (basicDirty.value) persistBasicDraft()
  else if (basicBackupDraft.value && clearBasicDraft()) basicBackupStatus.value = ""
}, { deep: true })

function cancelBasicEdit() {
  if (basicDirty.value && !getConfirm()?.("有未保存的修改，确定取消吗？")) return
  if (basicDirty.value) clearBasicDraft()
  basicEditing.value = false
  basicConflict.value = null
  basicBackupConflict.value = null
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
    if (clearBasicDraft() && !basicBackupError.value) basicBackupStatus.value = ""
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
  basicBackupConflict.value = null
  clearBasicDraft()
  if (!basicBackupError.value) basicBackupStatus.value = "已载入服务器版本；未保存内容仍须点击保存。"
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
  persistBasicDraft()
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

watch([profileDirty, basicDirty, dossierDirty], ([profile, basic, dossier]) => emit("profile-dirty", Boolean(profile || basic || dossier)), { immediate: true })
watch([() => props.projectId, () => props.entity?.id || props.entity?.entity_id], () => {
  detailSection.value = props.historyOpen ? 'history' : 'overview'
  basicGeneration += 1
  basicSaving.value = false
  basicEditing.value = false
  basicConflict.value = null
  basicError.value = ""
  basicBackupError.value = ""
  basicBackupStatus.value = ""
  basicBackupConflict.value = null
  basicBackupDraft.value = null
  basicBackupRecovering.value = false
  fillBasicForm()
  profileGeneration += 1
  profileOpen.value = false
  profileLoading.value = false
  profileSaving.value = false
  profileLoaded.value = false
  profileError.value = ""
  fillProfile()
  worldDossierOpen.value = false
  worldDossierMounted.value = false
  dossierDirty.value = false
})
onBeforeUnmount(() => { basicGeneration += 1; profileGeneration += 1; emit("profile-dirty", false) })
</script>

<template>
  <article class="world-entity-detail" aria-labelledby="world-entity-detail-title">
    <header class="world-entity-detail__header">
      <div>
        <button type="button" class="btn btn-sm btn-ghost world-entity-detail__back" @click="emit('back')">← 返回资料库</button>
        <button v-if="writingReturn" type="button" class="btn btn-sm" @click="returnToWriting">回到原文 · 第 {{ writingReturn.chapterIndex }} 章</button>
        <h2 id="world-entity-detail-title">{{ entity.name || '未命名人物或设定' }}</h2>
        <p><span>{{ typeLabel }}</span> · <span class="badge" :class="displayStateBadgeClass(display.displayState)">{{ display.label }}</span></p>
      </div>
      <div class="world-entity-detail__actions">
        <button type="button" class="btn btn-sm btn-ghost" data-action="world-entity-impact-preview" @click="emit('impact-preview')">影响预演</button>
        <button type="button" class="btn btn-sm" @click="emit('create-task')">添加到计划中的任务</button>
        <button type="button" class="btn btn-sm btn-primary" @click="emit('edit')">编辑资料</button>
        <button v-if="!publicDemoReadOnly" type="button" class="btn btn-sm" @click="askAboutEntity">问对象</button>
      </div>
    </header>
    <nav class="world-entity-sections" role="tablist" aria-label="对象资料分区">
      <button v-for="(section, index) in detailSections" :id="`entity-tab-${section.key}`" :key="section.key" type="button" role="tab" :aria-selected="detailSection === section.key" :aria-controls="`entity-panel-${section.key}`" :tabindex="detailSection === section.key ? 0 : -1" @click="detailSection = section.key" @keydown="onSectionKeydown($event, index)">{{ section.label }}</button>
    </nav>
    <section v-show="detailSection === 'overview'" id="entity-panel-overview" role="tabpanel" aria-labelledby="entity-tab-overview" tabindex="0">
    <div class="world-entity-overview">
    <WorldEntityImage :entity="entity" :project-id="projectId" />
    <section class="world-entity-basic" aria-label="基本资料">
      <header class="world-entity-basic__header">
        <h3>基本资料</h3>
        <button v-if="!basicEditing" type="button" class="btn btn-sm" data-action="world-entity-basic-edit" @click="startBasicEdit">就地编辑</button>
        <template v-else>
          <button type="button" class="btn btn-sm btn-ghost" data-action="world-entity-basic-cancel" :disabled="basicSaving" @click="cancelBasicEdit">取消</button>
          <button type="button" class="btn btn-sm btn-primary" data-action="world-entity-basic-save" :disabled="basicSaving || !basicDirty" @click="saveBasicEdit">{{ basicSaving ? '保存中…' : '保存' }}</button>
        </template>
      </header>
      <p v-if="basicBackupError" class="error-card" role="alert">{{ basicBackupError }}</p>
      <p v-if="basicBackupStatus" class="world-entity-basic__hint" role="status">{{ basicBackupStatus }}</p>

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
        <div v-if="basicBackupConflict" class="world-entity-basic__conflict" role="alert" data-conflict="basic-local-draft">
          <p>这份本机草稿基于 {{ basicBackupConflict.base_version || '未知' }} 版资料；当前服务器版本为 {{ basicBaselineUpdatedAt || '未知' }}。系统不会自动覆盖，请选择如何处理。</p>
          <div class="world-entity-basic__conflict-actions">
            <button type="button" class="btn btn-sm" :disabled="basicBackupRecovering" @click="keepBasicBackup">{{ basicBackupRecovering ? '核对中…' : '保留本机草稿' }}</button>
            <button type="button" class="btn btn-sm btn-ghost" :disabled="basicBackupRecovering" @click="discardBasicBackup">放弃本机草稿</button>
          </div>
        </div>
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
            :disabled="basicSaving || Boolean(basicBackupConflict)"
          ></textarea>
          <input
            v-else
            v-model="basicForm[key]"
            :data-basic-field="key"
            type="text"
            maxlength="255"
            :placeholder="hint"
            :disabled="basicSaving || Boolean(basicBackupConflict)"
          >
        </label>
        <p class="world-entity-basic__hint">保存需要明确点击“保存”；失焦不会修改已采用事实。本机副本含“作者秘密”，只保存在此浏览器；请勿在共用设备遗留。</p>
      </div>
    </section>
    </div>
    <TargetedCompletionPanel :project-id="projectId" :entity-id="entity.id || entity.entity_id" :initial-name="entity.name || ''" @applied="emit('refresh', entity.id || entity.entity_id)" />
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
    </section>
    <section v-show="detailSection === 'dossier'" id="entity-panel-dossier" role="tabpanel" aria-labelledby="entity-tab-dossier" tabindex="0">
    <details class="world-entity-dossier" @toggle="toggleDossier">
      <summary>对象档案 <span>稳定设定、有效范围与模板</span></summary>
      <WorldObjectDossierEditor
        v-if="worldDossierMounted"
        :entity="entity"
        :project-id="projectId"
        :read-only="publicDemoReadOnly"
        :assistant-context-ready="assistantContextReady"
        @dirty="dossierDirty = $event"
        @saved="emit('refresh', $event)"
      />
    </details>
    <section v-if="isCharacter" class="world-character-profile">
      <header><div><h3>人物旧档案字段</h3><p>保留既有人物字段；场景中的时点状态以 Story 记录为准。</p></div><button type="button" class="btn btn-sm" @click="profileOpen ? (profileOpen = false) : openProfile()">{{ profileOpen ? '收起' : '查看旧档案字段' }}</button></header>
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
    </section>
    <section v-show="detailSection === 'relations'" id="entity-panel-relations" role="tabpanel" aria-labelledby="entity-tab-relations" tabindex="0">
    <p v-if="relatedError" role="alert">{{ relatedError }}</p>
    <details :open="detailSection === 'relations' || undefined" @toggle="$event.target.open && loadInfo()">
      <summary>关系</summary>
      <button v-if="!publicDemoReadOnly" class="btn btn-sm" type="button" @click="addRelation">添加关系</button>
      <label><input v-model="showRemovedRelations" type="checkbox" @change="loadInfo">同时查看已移除关系与恢复记录</label>
      <p v-if="infoLoading">正在读取…</p>
      <p v-else-if="!related.length">尚无关联关系</p>
      <article v-for="relation in related" :key="relation.id">
        <strong>{{ relation.source_name }} → {{ relation.target_name }}</strong>
        <p>{{ relation.description || '已记录关联' }}</p>
        <p v-if="relation.status === 'deprecated'">此关系已移除；仍保留可用历史。</p>
        <button v-if="!publicDemoReadOnly && relation.status !== 'deprecated'" class="btn btn-sm" @click="showRelationReviewEditForm(relation.id)">编辑关系类型与端点</button>
        <button v-if="!publicDemoReadOnly && relation.status !== 'deprecated'" class="btn btn-sm" type="button" @click="askAboutRelation(relation)">问这条关系</button>
        <WorldRelationMaintenance v-if="!publicDemoReadOnly" :project-id="projectId" :relation="relation" @changed="onRelationChanged" />
      </article>
    </details>
    </section>
    <section v-show="detailSection === 'history'" id="entity-panel-history" role="tabpanel" aria-labelledby="entity-tab-history" tabindex="0">
      <p>这里展示对象改动历史和可追溯来源。剧情经历、场景时点状态仍由故事结构和场景资料维护，不在此复制为另一份事实。</p>
      <button type="button" class="btn btn-sm" @click="searchSourceMentions">查找原文提及</button>
      <p>以下经历按当前对象读取已记录事实，保留时间未知和待重验标记。尚未记录的经历不会自动补全；原文字面提及不等于已证实的剧情依赖。</p>
      <StoryFactTimelinePanel :project-id="projectId" :entity-id="entity.id || entity.entity_id" />
    <WorldEntityRevisionHistory
      :entity="entity"
      :project-id="projectId"
      :auto-open="historyOpen"
      :highlight-revision-id="highlightRevisionId"
      @restored="emit('refresh', entity.id || entity.entity_id)"
    />
    </section>

  </article>
</template>

<style scoped>
.world-entity-sections{display:flex;gap:8px;flex-wrap:wrap;border-bottom:1px solid var(--border-color,var(--border));padding-bottom:8px}
.world-entity-sections button{min-height:44px;border:0;border-radius:6px;background:transparent;color:var(--text-secondary);padding:8px 14px;cursor:pointer}
.world-entity-sections [aria-selected=true]{background:var(--bg-muted);color:var(--text-primary);font-weight:600}
.world-entity-sections button:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.world-entity-detail [role=tabpanel]{display:grid;gap:16px;min-width:0}

.world-entity-overview{display:grid;grid-template-columns:minmax(180px,260px) minmax(0,1fr);gap:24px;align-items:start}.world-entity-overview p{line-height:1.7}@media(max-width:700px){.world-entity-overview{grid-template-columns:minmax(0,1fr)}}
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
.world-entity-dossier { display: grid; gap: 12px; border: 1px solid var(--border-color, var(--border)); border-radius: var(--radius-md); padding: 12px; }
.world-entity-dossier > summary { cursor: pointer; font-weight: 650; }
.world-entity-dossier > summary span { margin-left: 6px; color: var(--text-secondary); font-size: 12px; font-weight: 400; }
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
