<script setup>
import { onBeforeUnmount, ref } from "vue"
import { getApi, getAppState, getRouter, getToast } from "../../bridge/index.js"

const props = defineProps({ selectionOnly: { type: Boolean, default: false } })
const emit = defineEmits(["select"])
const openingAuthor = ref(false)
let lifecycleGeneration = 0
let disposed = false

function ownsAuthorRequest(state, projectId, generation) {
  return !disposed
    && generation === lifecycleGeneration
    && state?.currentView === "home"
    && state?.currentProjectId === projectId
}

async function enterAuthor() {
  if (props.selectionOnly) {
    emit("select", "author")
    return
  }
  if (openingAuthor.value) return
  const state = getAppState()
  const projectId = state?.currentProjectId || null
  if (!projectId) {
    getRouter().navigate("project")
    return
  }
  const generation = ++lifecycleGeneration
  openingAuthor.value = true
  try {
    const project = await getApi().projects.get(projectId)
    if (!ownsAuthorRequest(state, projectId, generation)) return
    state.currentProjectId = project.id
    state.currentProject = project
    await getRouter().navigate("today")
  } catch {
    if (!ownsAuthorRequest(state, projectId, generation)) return
    state.currentProjectId = null
    state.currentProject = null
    getToast()("上次打开的作品已不可用，请重新选择。", "info")
    await getRouter().navigate("project")
  } finally {
    if (ownsAuthorRequest(state, projectId, generation)) openingAuthor.value = false
  }
}

function enterRp() {
  if (props.selectionOnly) {
    emit("select", "rp")
    return
  }
  lifecycleGeneration += 1
  openingAuthor.value = false
  getRouter().navigate("journeys")
}

onBeforeUnmount(() => {
  disposed = true
  lifecycleGeneration += 1
})
</script>

<template>
  <main class="entry-choice">
    <div class="entry-choice__heading">
      <span class="entry-choice__brand"><i aria-hidden="true">◆</i> NovelCraft</span>
      <h1>今天想怎样进入故事？</h1>
      <p>创作一部小说，或直接走进熟悉的幻想世界。</p>
    </div>
    <div class="entry-choice__grid" aria-label="选择使用方式">
      <button class="entry-card entry-card--author" type="button" data-entry="author" :disabled="openingAuthor" @click="enterAuthor">
        <span class="entry-card__eyebrow">WRITE</span>
        <strong>我是作家</strong>
        <span>整理世界、大纲与正文，继续现有创作项目。</span>
        <i aria-hidden="true">{{ openingAuthor ? '正在打开上次作品…' : '进入创作 →' }}</i>
      </button>
      <button class="entry-card entry-card--rp" type="button" data-entry="rp" @click="enterRp">
        <span class="entry-card__eyebrow">ROLE PLAY</span>
        <strong>进入互动故事</strong>
        <span>用自然语言开始角色扮演（RP），从喜欢的世界、身份和起点出发。</span>
        <i aria-hidden="true">尽情游玩吧 →</i>
      </button>
    </div>
  </main>
</template>
