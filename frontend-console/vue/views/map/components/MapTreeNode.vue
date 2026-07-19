<template>
  <ul v-if="items.length" class="map-tree">
    <li v-for="map in items" :key="map.id">
      <button class="link-button" data-action="map-open" :data-id="map.id" @click="$emit('open', map)">{{ map.name }}</button>
      <button class="btn btn-xs" data-action="map-archive" :data-id="map.id" @click="$emit('archive', map)">归档</button>
      <MapTreeNode :items="children.get(map.id) || []" :children="children" @open="$emit('open', $event)" @archive="$emit('archive', $event)" />
    </li>
  </ul>
</template>

<script setup>
defineProps({ items: { type: Array, default: () => [] }, children: { type: Map, required: true } })
defineEmits(["open", "archive"])
</script>
