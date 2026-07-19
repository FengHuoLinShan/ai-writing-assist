<template>
  <svg class="nav-icon" viewBox="0 0 24 24" aria-hidden="true">
    <template v-if="name === 'project'"><path d="M3 7v10a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-6l-2-2H5a2 2 0 0 0-2 2z" /></template>
    <template v-else-if="name === 'writing'"><path d="M12 20h9" /><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z" /></template>
    <template v-else-if="name === 'world'"><circle cx="12" cy="12" r="10" /><path d="M2 12h20" /><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" /></template>
    <template v-else-if="name === 'map'"><path d="M9 18l-6 3V6l6-3 6 3 6-3v15l-6 3-6-3z" /><path d="M9 3v15" /><path d="M15 6v15" /></template>
    <template v-else-if="name === 'search'"><circle cx="11" cy="11" r="8" /><path d="m21 21-4.35-4.35" /></template>
    <template v-else-if="name === 'outline'"><path d="M4 4h16v16H4z" /><path d="M8 9h8M8 12h8M8 15h5" /></template>
    <template v-else-if="name === 'generate'"><path d="m13 2-10 12h9l-1 8 10-12h-9z" /></template>
    <template v-else-if="name === 'project-settings'"><path d="M20 7h-9M14 17H5" /><circle cx="17" cy="17" r="3" /><circle cx="7" cy="7" r="3" /><path d="M14 17a3 3 0 0 0 3-3M7 7a3 3 0 0 0-3 3" /></template>
    <template v-else><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-2.82 1.18V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 7.3 19.73l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 3.29 14H3a2 2 0 0 1 0-4h.29a1.65 1.65 0 0 0 1.18-2.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 10 3.17V3a2 2 0 0 1 4 0v.17a1.65 1.65 0 0 0 2.9 1.18l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 20.71 10H21a2 2 0 0 1 0 4h-.29A1.65 1.65 0 0 0 19.4 15z" /></template>
  </svg>
</template>

<script setup>
defineProps({ name: { type: String, required: true } })
</script>
