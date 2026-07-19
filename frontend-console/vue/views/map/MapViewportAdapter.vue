<template>
  <div ref="host" class="map-root" :aria-busy="String(mounting)" />
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue"
import { createMapViewportController } from "./controllers/mapViewportController.js"

const props = defineProps({
  context: { type: Object, required: true },
  timelineProjection: { type: Object, default: null },
})
const emit = defineEmits(["mounted", "mount-error"])

const host = ref(null)
const mounting = ref(false)
const controller = createMapViewportController()
let mountGeneration = 0

const identityKey = computed(() => JSON.stringify({
  projectId: props.context.projectId || null,
  mapId: props.context.mapId || null,
  sceneId: props.context.sceneId || null,
  focusHexQ: props.context.focusHexQ ?? null,
  focusHexR: props.context.focusHexR ?? null,
  focusPathId: props.context.focusPathId || null,
  focusLayerNodeId: props.context.focusLayerNodeId || null,
  layers: props.context.layers || {},
}))
const presentationKey = computed(() => JSON.stringify({
  viewMode: props.context.viewMode || "live",
  lowMotion: Boolean(props.context.lowMotion),
  focusEntityId: props.context.focusEntityId || null,
}))

async function remount() {
  const element = host.value
  if (!element) return false
  const generation = ++mountGeneration
  mounting.value = true
  try {
    const didMount = await controller.mount(element, props.context)
    if (generation !== mountGeneration) return false
    if (didMount && props.timelineProjection) {
      controller.setTimelineProjection(props.timelineProjection)
    }
    emit("mounted", didMount)
    return didMount
  } catch (error) {
    if (generation === mountGeneration) emit("mount-error", error)
    return false
  } finally {
    if (generation === mountGeneration) mounting.value = false
  }
}

watch(identityKey, async () => {
  await nextTick()
  await remount()
})

watch(presentationKey, () => {
  controller.setPresentationContext({
    viewMode: props.context.viewMode || "live",
    lowMotion: Boolean(props.context.lowMotion),
    focusEntityId: props.context.focusEntityId || null,
  })
})

watch(() => props.timelineProjection, (projection) => {
  if (projection) controller.setTimelineProjection(projection)
  else controller.clearTimelineProjection()
}, { deep: true })

onMounted(remount)
onBeforeUnmount(() => {
  mountGeneration += 1
  controller.dispose()
})

defineExpose({
  canLeave: () => controller.canLeave(),
  remount,
  focusPath: (...args) => controller.focusPath(...args),
  focusTimelineAnchor: (...args) => controller.focusTimelineAnchor(...args),
  clearPathFocus: (...args) => controller.clearPathFocus(...args),
  selectInspectorObject: (...args) => controller.selectInspectorObject(...args),
  timelineEntityOptions: () => controller.timelineEntityOptions(),
  timelinePathOptions: () => controller.timelinePathOptions(),
  pathRevisionMismatch: (...args) => controller.pathRevisionMismatch(...args),
  setPresentationContext: (...args) => controller.setPresentationContext(...args),
  spatialContext: () => controller.spatialContext(),
})
</script>
