<script setup>
/**
 * ImageExportPanel — G4b 作者手动导出图片包区块。
 *
 * 与“导出作品”区分：导出作品是文字、服务端生成；图片包由浏览器在本机
 * 打包，用于日后恢复（恢复须由作者把 ZIP 交给部署方，chmod 600 后经
 * restore_objects.sh 恢复）。文案只陈述事实：图片包已生成（N 张），
 * 不写“已备份”；“校验通过”仅指点下的地图页与服务端记录的摘要、大小
 * 一致，世界对象图与蒙版为本机自算摘要且可解码，不声称与历史存储对账。
 */
import { computed, onMounted, ref } from "vue"
import { getApi, getConfirm } from "../../../bridge/index.js"
import {
  buildExportFileName,
  buildImagePackages,
  ExportAbortedError,
} from "../logic/imagePackageExport.js"

const props = defineProps({
  projectId: { type: String, required: true },
  projectTitle: { type: String, default: "" },
})

const manifest = ref(null)
const manifestLoading = ref(false)
const manifestError = ref("")
const phase = ref("idle") // idle | packing | retry | done | cancelled | error
const progress = ref({ done: 0, total: 0, packages: 0 })
const failures = ref([])
const accumulatedPackages = ref([])
const result = ref(null)
const exportError = ref("")
let cancelled = false
let activeController = null

const secureContextAvailable = computed(() => Boolean(globalThis.crypto?.subtle))

const CATEGORY_LABELS = {
  map_page: "地图页",
  map_mask: "蒙版",
  world_full: "世界对象图",
  world_thumbnail: "世界对象图",
}

const categoryCounts = computed(() => {
  const counts = { map_page: 0, map_mask: 0, world_full: 0, world_thumbnail: 0 }
  for (const item of manifest.value?.objects || []) {
    counts[item.category] = (counts[item.category] || 0) + 1
  }
  return counts
})
const totalObjects = computed(() => manifest.value?.objects?.length || 0)
const busy = computed(() => phase.value === "packing")
const failureCount = computed(() => failures.value.length)

async function loadManifest() {
  if (!props.projectId || manifestLoading.value) return
  manifestLoading.value = true
  manifestError.value = ""
  try {
    manifest.value = await getApi().world.imageExportManifest(props.projectId)
  } catch (error) {
    manifestError.value = error?.message || "导出清单读取失败，请稍后重试。"
  } finally {
    manifestLoading.value = false
  }
}

function fetchItemBytes(signal) {
  const world = getApi().world
  return async (item) => {
    let blob
    if (item.category === "map_page") {
      blob = await world.fetchMapAtlasImage(props.projectId, item.page_id, { signal })
    } else if (item.category === "map_mask") {
      blob = await world.fetchMapAtlasMask(props.projectId, item.page_id, { signal })
    } else {
      blob = await world.fetchEntityImage(item.entity_id, props.projectId,
        item.category === "world_full" ? "full" : "thumbnail",
        { expectedVersion: item.image_version, signal })
    }
    return new Uint8Array(await blob.arrayBuffer())
  }
}

function downloadBlob(fileName, blob) {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement("a")
  anchor.href = url
  anchor.download = fileName
  anchor.click()
  setTimeout(() => URL.revokeObjectURL(url), 30000)
}

/* 部分失败语义（用户裁定）：失败项不入包；作者重试后仍失败时，确认生成
 * 不完整的包：清单只含成功行，文件名标明整轮缺几张。 */
function finishDownload() {
  const packages = accumulatedPackages.value
  if (!packages.length) {
    exportError.value = "没有可写入图片包的图片，未下载任何文件。"
    phase.value = "error"
    accumulatedPackages.value = []
    failures.value = []
    return
  }
  const missingCount = failures.value.length
  const stamp = packages[packages.length - 1].timestamp
  const baseName = buildExportFileName(props.projectTitle || "作品", stamp, missingCount)
  packages.forEach((pkg, index) => {
    const indexed = packages.length > 1
      ? baseName.replace(/\.zip$/, `-${index + 1}.zip`)
      : baseName
    downloadBlob(indexed, pkg.blob)
  })
  result.value = {
    count: packages.reduce((sum, pkg) => sum + pkg.objectCount, 0),
    packages: packages.length,
    missing: missingCount,
  }
  accumulatedPackages.value = []
  failures.value = []
  phase.value = "done"
}

async function runExport(items) {
  phase.value = "packing"
  progress.value = { done: 0, total: items.length, packages: 0 }
  cancelled = false
  activeController = new AbortController()
  exportError.value = ""
  try {
    const outcome = await buildImagePackages({
      items,
      fetchBytes: fetchItemBytes(activeController.signal),
      onUpdate: (update) => { progress.value = update },
      isCancelled: () => cancelled,
    })
    accumulatedPackages.value.push(...outcome.packages)
    if (outcome.failures.length) {
      failures.value = outcome.failures
      phase.value = "retry"
      return
    }
    failures.value = []
    finishDownload()
  } catch (error) {
    accumulatedPackages.value = []
    failures.value = []
    if (error instanceof ExportAbortedError) {
      phase.value = "cancelled"
      return
    }
    exportError.value = error?.message || "图片包生成失败，未下载任何文件。"
    phase.value = "error"
  } finally {
    activeController = null
  }
}

async function startExport() {
  if (!manifest.value) await loadManifest()
  if (manifestError.value || !totalObjects.value) return
  accumulatedPackages.value = []
  failures.value = []
  await runExport(manifest.value.objects)
}

async function retryFailures() {
  const failedItems = failures.value.map(failure => failure.item)
  if (!failedItems.length || busy.value) return
  await runExport(failedItems)
}

function confirmIncompleteExport() {
  if (!failures.value.length || busy.value) return
  const names = failures.value.slice(0, 5)
    .map(failure => failure.item.title || failure.item.key).join("、")
  const more = failures.value.length > 5 ? ` 等 ${failures.value.length} 张` : ""
  if (!getConfirm()(`仍有 ${failures.value.length} 张图片导出失败（${names}${more}）。确认生成不完整的图片包？清单只包含已成功的图片。`)) return
  finishDownload()
}

function cancelExport() {
  cancelled = true
  activeController?.abort()
}

defineExpose({ busy })

onMounted(() => {
  void loadManifest()
})
</script>

<template>
  <div class="settings-section image-export-panel" data-testid="image-export-panel">
    <h3>导出图片包</h3>
    <p class="settings-section-hint">
      「导出作品」导出的是文字，由服务端生成；这里的图片包由浏览器在本机打包，包含地图册页面、编辑蒙版和世界对象图片，用于日后恢复，不会自动上传到任何地方。
    </p>
    <p v-if="!secureContextAvailable" class="settings-save-state is-error" role="alert">
      当前浏览器环境无法计算图片校验值（缺少加密接口）。请通过 https 或本机开发地址打开本页后再导出。
    </p>
    <p v-if="manifestError" class="settings-save-state is-error" role="alert">{{ manifestError }}</p>
    <template v-if="manifestLoading">
      <p role="status">正在读取可导出的图片清单…</p>
    </template>
    <template v-else-if="manifest">
      <p role="status">
        当前作品可导出 {{ totalObjects }} 个图片文件：地图页 {{ categoryCounts.map_page }} 张、编辑蒙版 {{ categoryCounts.map_mask }} 张、世界对象图 {{ categoryCounts.world_full + categoryCounts.world_thumbnail }} 张（含已归档对象）。
      </p>
      <p v-if="!totalObjects" class="settings-section-hint">这个作品还没有可导出的图片；生成地图页或上传世界对象图片后再来导出。</p>
      <div class="settings-actions">
        <button
          type="button"
          class="btn btn-sm btn-primary"
          :disabled="!totalObjects || busy || !secureContextAvailable"
          data-testid="image-export-start"
          @click="startExport"
        >{{ busy ? "正在打包…" : "生成图片包" }}</button>
        <button
          v-if="busy"
          type="button"
          class="btn btn-sm"
          data-testid="image-export-cancel"
          @click="cancelExport"
        >取消</button>
      </div>
      <p v-if="busy" role="status" data-testid="image-export-progress">
        正在逐张核对并打包：{{ progress.done }}/{{ progress.total }}{{ progress.packages ? `，已分 ${progress.packages} 包` : "" }}。导出期间请保持本页打开；取消或离开不会留下半成品文件。
      </p>
      <div v-if="phase === 'retry'" class="image-export-failures" role="alert" data-testid="image-export-failures">
        <p>以下 {{ failureCount }} 张图片未能导出，未写入图片包（网络失败、内容校验不一致或无法解码都按失败处理）。可以先重试；仍失败时可确认生成缺少这些图片的包。</p>
        <ul>
          <li v-for="failure in failures" :key="failure.item.key">
            {{ failure.item.title || failure.item.key }}（{{ CATEGORY_LABELS[failure.item.category] }}）：{{ failure.reason }}
          </li>
        </ul>
        <div class="settings-actions">
          <button type="button" class="btn btn-sm" :disabled="busy" @click="retryFailures">重试失败项</button>
          <button type="button" class="btn btn-sm" :disabled="busy" @click="confirmIncompleteExport">仍要生成（缺 {{ failureCount }} 张）</button>
        </div>
      </div>
      <p v-else-if="phase === 'done' && result" role="status" data-testid="image-export-done">
        图片包已生成（{{ result.count }} 张）{{ result.packages > 1 ? `，共 ${result.packages} 个文件，请全部保存` : "" }}{{ result.missing > 0 ? `，缺少 ${result.missing} 张（这些图片未写入图片包）` : "" }}。校验通过指点下地图页与服务端记录的摘要、大小一致，世界对象图与蒙版为本机计算摘要且可解码；这不等于已备份，请把文件妥善保存到本机。
      </p>
      <p v-else-if="phase === 'cancelled'" role="status">已取消导出，未下载任何文件。</p>
      <p v-if="phase === 'error' && exportError" class="settings-save-state is-error" role="alert">{{ exportError }}</p>
    </template>
  </div>
</template>
