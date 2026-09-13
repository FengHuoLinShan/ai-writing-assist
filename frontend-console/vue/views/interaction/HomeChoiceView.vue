<script setup>
import { onBeforeUnmount, ref } from "vue"
import "./rp-redesign.css"
import { getApi, getAppState, getRouter, getToast } from "../../bridge/index.js"

const props = defineProps({
  selectionOnly: { type: Boolean, default: false },
  demo: { type: Object, default: null },
})
const emit = defineEmits(["select", "demo"])
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

function enterDemo(target) {
  emit("demo", target)
}

onBeforeUnmount(() => {
  disposed = true
  lifecycleGeneration += 1
})
</script>

<template>
  <main class="entry-choice">
    <div class="entry-choice__heading">
      <span class="entry-choice__brand"><i class="entry-choice__brand-mark" aria-hidden="true">N</i><span>NovelCraft</span></span>
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
    <section v-if="demo?.enabled" class="entry-choice__public-demo" aria-label="无需登录的演示">
      <span>先看看实际作品与互动故事</span>
      <div>
        <button type="button" data-demo-entry="workspace" @click="enterDemo('workspace')">查看演示项目</button>
        <button v-if="demo.rp_enabled" type="button" data-demo-entry="rp" @click="enterDemo('rp')">进入演示 RP</button>
      </div>
    </section>
  </main>
</template>

<style scoped>
.entry-choice__public-demo{display:grid;gap:10px;width:min(100%,720px);margin:18px auto 0;padding:16px 18px;border:1px solid var(--border);border-radius:14px;background:var(--bg-panel);color:var(--text-body)}.entry-choice__public-demo>span{font-size:14px;color:var(--text-secondary)}.entry-choice__public-demo>div{display:flex;gap:10px;flex-wrap:wrap}.entry-choice__public-demo button{min-height:40px;padding:8px 14px;border:1px solid var(--nc-primary);border-radius:9px;background:transparent;color:var(--nc-primary);font:inherit;cursor:pointer}@media(max-width:520px){.entry-choice__public-demo>div{display:grid;grid-template-columns:1fr}.entry-choice__public-demo button{width:100%}}
</style>
