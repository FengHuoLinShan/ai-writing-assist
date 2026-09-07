<script setup>
import { computed, onBeforeUnmount, onMounted, ref, shallowRef } from 'vue'
import { getConfirm, getToast } from '../../bridge/index.js'
import { getThemeController, SHELL_THEMES } from '../../shell/composables/useTheme.js'
import { useModalDialog } from '../../composables/useModalDialog.js'
import { resolveVariant, variantVariables } from '../../theme/themeTokens.js'
import { deleteThemePackage, exportThemePackage, getThemePackage, listThemePackages, prepareThemeResources, readThemePackage, saveThemePackage } from '../../theme/themePackages.js'
import sampleUrl from '../../../themes/quiet-library.nctheme.zip?url'
import schemaUrl from '../../../themes/theme-package.schema.json?url'

const theme = getThemeController()
const toast = getToast()
const confirm = getConfirm()
const packages = ref([])
const busy = ref(false)
const saving = ref(false)
const error = ref('')
const preview = shallowRef(null)
const previewMode = ref('light')
let resources = null
let abort = null
let disposed = false
const open = computed(() => Boolean(preview.value))
const { overlayRef, dialogRef, onKeydown, onFocusin } = useModalDialog({ isOpen: () => open.value, requestClose: closePreview, canClose: () => !saving.value })
const previewStyle = computed(() => {
  const variant = resolveVariant(preview.value?.manifest, previewMode.value)
  const variables = variantVariables(variant)
  for (const [slot, css] of [['uiFont', '--font-ui'], ['bodyFont', '--font-body']]) {
    const font = resources?.fonts.get(variant[slot])
    if (font) variables[css] = `"${font.family}", system-ui, sans-serif`
  }
  for (const [slot, css] of [['background', '--theme-background'], ['texture', '--theme-texture'], ['emptyState', '--theme-empty-image']]) {
    const url = resources?.urls.get(variant[slot])
    if (url) variables[css] = `url("${url}")`
  }
  return variables
})
async function refresh() { packages.value = await listThemePackages() }
onMounted(() => refresh().catch(cause => { error.value = cause.message }))
function closePreview() {
  if (saving.value) return
  preview.value = null
  resources?.dispose()
  resources = null
}
async function importFile(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file || busy.value) return
  busy.value = true
  error.value = ''
  abort = new AbortController()
  try {
    const record = await readThemePackage(file, { signal: abort.signal })
    resources = await prepareThemeResources(record, { signal: abort.signal })
    if (disposed) { resources.dispose(); return }
    for (const font of resources.fonts.values()) document.fonts.add(font)
    previewMode.value = theme.resolved.value
    preview.value = record
  } catch (cause) { if (!disposed && cause.name !== 'AbortError') error.value = cause.message || '主题包无法读取' }
  finally { busy.value = false; abort = null }
}
async function install() {
  if (saving.value || !preview.value) return
  const record = preview.value
  const previous = packages.value.find(item => item.id === record.id)
  if (previous && !confirm(`此浏览器已有「${previous.name}」${previous.version}。替换为 ${record.manifest.version}？`)) return
  saving.value = true
  error.value = ''
  try {
    await saveThemePackage(record)
    if (disposed) return
    await theme.activate(record)
    if (disposed) return
    await refresh()
    toast(`「${record.manifest.name}」已导入此浏览器`, 'success')
    saving.value = false
    closePreview()
  } catch (cause) { if (!disposed) error.value = cause.message }
  finally { saving.value = false }
}
async function run(action) {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try { await action() }
  catch (cause) { if (!disposed) error.value = cause.message }
  finally { busy.value = false }
}
function applyPackage(id) {
  return run(async () => {
    const record = id === 'modern' ? null : await getThemePackage(id)
    if (disposed) return
    if (id !== 'modern' && !record) throw new Error('此主题已不可用，请重新导入')
    if (await theme.activate(record)) toast(`已应用「${theme.packageName.value}」`, 'success')
  })
}
function removePackage(item) {
  if (!confirm(`从此浏览器删除「${item.name}」？${theme.packageId.value === item.id ? '将恢复现代简约。' : ''}重新导入主题包可再次使用。`)) return
  return run(async () => {
    await deleteThemePackage(item.id)
    if (disposed) return
    if (theme.packageId.value === item.id) await theme.activate(null)
    await refresh()
    toast('主题已从此浏览器删除', 'success')
  })
}
function exportPackage(item) {
  return run(async () => {
    const record = await getThemePackage(item.id)
    if (disposed) return
    if (!record?.archive) throw new Error('找不到原主题包，请重新导入')
    exportThemePackage(record)
    toast('主题包已交给浏览器下载', 'success')
  })
}
onBeforeUnmount(() => { disposed = true; abort?.abort(); resources?.dispose() })
</script>

<template>
  <section class="appearance-settings" aria-labelledby="appearance-title" :aria-busy="busy || saving">
    <header class="appearance-heading">
      <div><h2 id="appearance-title">让创作空间适合你</h2><p>作者工作台与互动故事共用外观。主题仅保存在此浏览器，清除网站数据后需重新导入。</p></div>
      <label class="btn theme-import-button" :class="{ disabled: busy }">
        {{ busy ? '正在处理…' : '导入主题包' }}
        <input type="file" accept=".zip" aria-label="导入主题包" :disabled="busy || saving" @change="importFile">
      </label>
      <button v-if="busy && abort" type="button" class="btn" @click="abort.abort()">取消导入</button>
    </header>
    <p v-if="error || theme.error.value" class="error-card" role="alert">{{ error || theme.error.value }}</p>
    <fieldset class="appearance-modes"><legend>明暗模式</legend>
      <label v-for="mode in SHELL_THEMES" :key="mode.value"><input type="radio" name="appearance-mode" :value="mode.value" :checked="theme.current.value === mode.value" @change="theme.apply(mode.value)"><span>{{ mode.label }}</span></label>
    </fieldset>
    <div class="theme-gallery" aria-label="可用主题">
      <article class="theme-card" :class="{ 'is-selected': theme.packageId.value === 'modern' }">
        <div class="theme-card__sample" aria-hidden="true"><i /><span /><span /><b /></div>
        <div class="theme-card__copy"><h3>现代简约</h3><p>清晰、安静，专注文字本身。</p><span class="theme-card__meta">内置 · 浅色与深色</span></div>
        <button class="btn" :class="{ 'btn-primary': theme.packageId.value !== 'modern' }" :disabled="busy || theme.packageId.value === 'modern'" @click="applyPackage('modern')">{{ theme.packageId.value === 'modern' ? '正在使用' : '恢复默认' }}</button>
      </article>
      <article v-for="item in packages" :key="item.id" class="theme-card" :class="{ 'is-selected': theme.packageId.value === item.id }">
        <div class="theme-card__copy"><h3>{{ item.name }}</h3><p>{{ item.author || '本地主题包' }}</p><span class="theme-card__meta">版本 {{ item.version }} · 仅此浏览器</span></div>
        <div class="theme-card__actions"><button class="btn btn-primary" :disabled="busy || theme.packageId.value === item.id" @click="applyPackage(item.id)">{{ theme.packageId.value === item.id ? '正在使用' : '应用主题' }}</button><button class="btn" :disabled="busy" @click="exportPackage(item)">导出</button><button class="btn btn-ghost" :disabled="busy" :aria-label="`删除主题 ${item.name}`" @click="removePackage(item)">删除</button></div>
      </article>
    </div>
    <p class="appearance-note">主题包可包含字体、背景和插画，最大 30MiB。导入后先预览，确认应用才会改变当前外观。</p>
    <details class="appearance-note"><summary>制作自己的主题</summary><p>下载资源包示例，解压后修改 theme.json，再将配置和 assets 文件夹一起压缩。</p><a :href="sampleUrl" download="quiet-library.nctheme.zip">下载完整示例</a> · <a :href="schemaUrl" download="theme-package.schema.json">下载配置规范</a></details>
    <div v-if="preview" ref="overlayRef" class="modal-overlay theme-preview-overlay" @click.self="closePreview">
      <section ref="dialogRef" @keydown="onKeydown" @focusin="onFocusin" class="modal theme-preview-dialog" role="dialog" aria-modal="true" aria-labelledby="theme-preview-title" tabindex="-1">
        <header class="modal-header"><h2 id="theme-preview-title">预览「{{ preview.manifest.name }}」</h2><button class="btn btn-ghost" :disabled="saving" aria-label="关闭主题预览" @click="closePreview">关闭</button></header>
        <div class="theme-preview-modes"><button v-for="mode in ['light', 'dark']" :key="mode" class="btn" :aria-pressed="previewMode === mode" @click="previewMode = mode">{{ mode === 'light' ? '浅色' : '深色' }}</button></div>
        <div class="theme-preview" :style="previewStyle" :data-theme="previewMode">
          <aside><strong>我的作品</strong><span>写作</span><span>人物与世界</span><span>故事结构</span></aside>
          <main><small>第一章</small><h3>故事，从这里继续</h3><p class="theme-preview__prose">窗外的风停了。她翻开笔记，终于找到昨夜留在纸页间的那句话。</p><div class="theme-preview__controls"><button class="btn btn-primary">继续写作</button><button class="btn">查看资料</button><label>章节标题<input value="新的开始" aria-label="预览章节标题"></label><p role="status">工作稿已保存</p></div><div class="theme-preview__empty" aria-hidden="true" /></main>
        </div>
        <p v-if="error" class="error-card" role="alert">{{ error }}</p>
        <footer class="modal-footer"><span>当前页面外观尚未改变</span><button class="btn" :disabled="saving" @click="closePreview">取消</button><button class="btn btn-primary" :disabled="saving" @click="install">{{ saving ? '正在保存…' : '导入并应用' }}</button></footer>
      </section>
    </div>
  </section>
</template>
