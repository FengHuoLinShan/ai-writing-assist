<script setup>
import { computed, onBeforeUnmount, reactive, ref, watch } from "vue"
import { displayStateBadgeClass, worldAssetDisplay } from "../../../../shared/assetDisplayState.js"
import { getApi, getToast } from "../../../bridge/index.js"

const props = defineProps({
  entity: { type: Object, required: true },
  projectId: { type: String, required: true },
  typeLabel: { type: String, default: "人物或设定" },
  aliasesOpen: { type: Boolean, default: false },
})
const emit = defineEmits(["back", "edit", "create-alias", "edit-alias", "create-task", "profile-dirty"])
const aliases = computed(() => (props.entity?.content_json?.aliases || []).map((item) => (
  typeof item === "string" ? { alias: item } : item
)).filter((item) => String(item?.alias || "").trim()))
const display = computed(() => worldAssetDisplay(props.entity))
const isCharacter = computed(() => props.entity?.entity_type === "character")
const profileOpen = ref(false)
const profileLoading = ref(false)
const profileSaving = ref(false)
const profileError = ref("")
const profileBaseline = ref("")
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
const profileDirty = computed(() => profileOpen.value && Boolean(profileBaseline.value) && JSON.stringify(profileForm) !== profileBaseline.value)
let profileGeneration = 0

function fillProfile(value = {}) {
  for (const [key] of profileFields) profileForm[key] = value[key] || ""
  profileBaseline.value = JSON.stringify(profileForm)
}

async function openProfile() {
  profileOpen.value = true
  if (profileBaseline.value || profileLoading.value) return
  const generation = ++profileGeneration
  profileLoading.value = true
  profileError.value = ""
  try {
    const value = await getApi().world.getCharacter(props.entity.id || props.entity.entity_id, props.projectId)
    if (generation === profileGeneration) fillProfile(value)
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
  try {
    const payload = Object.fromEntries(profileFields.map(([key]) => [key, profileForm[key]]))
    const value = await getApi().world.updateCharacter(props.entity.id || props.entity.entity_id, payload, props.projectId)
    if (generation !== profileGeneration) return
    fillProfile(value)
    getToast()("人物档案已保存", "success")
  } catch (error) {
    if (generation === profileGeneration) profileError.value = error?.message || "人物档案保存失败，输入已保留"
  } finally {
    if (generation === profileGeneration) profileSaving.value = false
  }
}

watch(profileDirty, (dirty) => emit("profile-dirty", dirty), { immediate: true })
watch(() => props.entity?.id || props.entity?.entity_id, () => {
  profileGeneration += 1
  profileOpen.value = false
  profileLoading.value = false
  profileSaving.value = false
  profileError.value = ""
  fillProfile()
})
onBeforeUnmount(() => { profileGeneration += 1; emit("profile-dirty", false) })
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
        <button type="button" class="btn btn-sm" @click="emit('create-task')">添加到计划中的任务</button>
        <button type="button" class="btn btn-sm btn-primary" @click="emit('edit')">编辑资料</button>
      </div>
    </header>
    <section>
      <h3>概要</h3>
      <p>{{ entity.summary || entity.public_info || '还没有概要，可以编辑后补充。' }}</p>
    </section>
    <section v-if="isCharacter" class="world-character-profile">
      <header><div><h3>人物档案</h3><p>按需补充人物动机、状态和声音；名称与别名仍在基本资料中管理。</p></div><button type="button" class="btn btn-sm" @click="profileOpen ? (profileOpen = false) : openProfile()">{{ profileOpen ? '收起' : '完善人物档案' }}</button></header>
      <div v-if="profileOpen" class="world-character-profile__form" :aria-busy="profileLoading || profileSaving">
        <p v-if="profileLoading" role="status">正在读取人物档案…</p>
        <template v-else>
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
