<script setup>
import { ref } from 'vue'
import ThemePicker from '../vue/shell/components/ThemePicker.vue'
import WorkspaceDrawer from '../vue/components/WorkspaceDrawer.vue'
import { getThemeController } from '../vue/shell/composables/useTheme.js'
const theme = getThemeController()
theme.initialize()
const drawerOpen = ref(false)
</script>
<template>
  <main class="design-gallery">
    <header><span>NovelCraft / Design system</span><ThemePicker :model-value="theme.current.value" @update:model-value="theme.apply" /></header>
    <h1>留给文字的空间。</h1><p class="intro">现代简约 · 语义颜色、清晰层级、可恢复的交互</p>
    <section><h2>层级与状态</h2><div class="sample-row"><button class="btn btn-primary">继续写作</button><button class="btn">查看资料</button><button class="btn btn-ghost">稍后处理</button><button class="btn" disabled>正在保存…</button><button class="btn btn-danger">移入历史</button></div><div class="sample-row"><span class="badge">待处理</span><span class="badge badge-success">已采用</span><span class="badge">历史</span></div></section>
    <section><h2>输入与反馈</h2><div class="sample-grid"><label>作品名称<input type="text" class="form-input" value="海岸线以外"></label><label>资料类型<select class="form-select"><option>人物</option><option>地点</option></select></label><label>当前任务<textarea rows="3">写下这场相遇真正改变的事。</textarea></label></div><p class="error-card" role="alert">工作稿还没有保存。本地备份已保留，可以重试。</p><p class="sample-success" role="status">工作稿已保存，可以安心继续。</p></section>
    <section><h2>内容与留白</h2><article class="sample-prose"><small>第一章</small><h3>一封没有署名的信</h3><p>雨停的时候，街道还没有醒来。她推开窗，让纸页上最后一点墨迹在晨光里慢慢干透。</p></article></section>
    <section><h2>空态与按需展开</h2><div class="empty-state"><h3>从第一个人物开始</h3><p>记录一个名字，慢慢补全他的故事。</p><button class="btn btn-primary">新建人物</button></div><button class="btn" @click="drawerOpen = true">打开资料抽屉</button></section>
    <WorkspaceDrawer :mobile="true" :open="drawerOpen" title="本章资料" @close="drawerOpen = false"><h3>眼前的目标</h3><p>找到寄信人，确认这封信为何出现。</p><label>随手记录<textarea rows="5" /></label></WorkspaceDrawer>
  </main>
</template>
<style>
body:has(.design-gallery) { height: auto; overflow: auto; }
.design-gallery { max-width: 1120px; margin: 0 auto; padding: 40px 24px 80px; color: var(--nc-body); font-family: var(--font-ui); }
.design-gallery header { display: flex; justify-content: space-between; align-items: center; gap: 20px; }
.design-gallery h1 { font-size: clamp(32px, 5vw, 54px); color: var(--nc-ink); margin: 64px 0 16px; letter-spacing: -.045em; }
.design-gallery .intro { font-size: 18px; color: var(--nc-dim); }
.design-gallery section { margin-top: 40px; padding-top: 24px; border-top: var(--line-subtle); }
.design-gallery h2 { font-size: 20px; margin: 0 0 24px; }
.sample-row { display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 20px; }
.sample-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 20px; }
.design-gallery label { display: grid; gap: 8px; }
.sample-prose { max-width: 720px; background: var(--nc-surface); padding: 32px; border-radius: var(--radius-lg); }
.sample-prose p { font: 18px/1.85 var(--font-body); }
.design-gallery .empty-state { margin-bottom: 16px; }
.design-gallery .error-card { margin-top: 16px; }
.sample-success { color: var(--nc-success); }
</style>
