<script setup>
import NavIcon from '../../vue/shell/components/NavIcon.vue'
defineProps({ name: { type: String, required: true } })
const paths = {
  sidebar: 'M4 4h16v16H4zM9 4v16',
  inspector: 'M4 4h16v16H4zM15 4v16',
  focus: 'M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5',
  clock: 'M12 7v5l3 2',
  sparkles: 'm12 3 2.7 6.3L21 12l-6.3 2.7L12 21l-2.7-6.3L3 12l6.3-2.7Z',
  down: 'm7 10 5 5 5-5',
  forward: 'm9 5 7 7-7 7',
  back: 'm15 5-7 7 7 7',
  arrow: 'M4 12h15m-6-6 6 6-6 6',
  close: 'm6 6 12 12M6 18 18 6',
  plus: 'M12 5v14M5 12h14',
  check: 'm5 12 4 4L19 6',
  type: 'M3 18 8 5l5 13M5 13h6m5 5 3-8 3 8m-5-3h4',
  moon: 'M20 14.3A8 8 0 0 1 9.7 4 8 8 0 1 0 20 14.3Z',
  sun: 'M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.4 1.4m11.2 11.2L19 19M5 19l1.4-1.4M17.6 6.4 19 5',
  book: 'M12 6c-3-2-6-2-9-1v14c3-1 6-1 9 1 3-2 6-2 9-1V5c-3-1-6-1-9 1Zm0 0v14',
  person: 'M4 21c0-8 16-8 16 0',
}
</script>
<template>
  <svg v-if="paths[name]" class="rd-icon" viewBox="0 0 24 24" aria-hidden="true"><Transition name="rd-symbol"><g :key="name" :data-symbol="name"><path :d="paths[name]" :pathLength="name === 'check' ? 1 : undefined"/><circle v-if="name === 'clock'" cx="12" cy="12" r="9"/><circle v-if="name === 'sun'" cx="12" cy="12" r="4"/><circle v-if="name === 'person'" cx="12" cy="7" r="4"/></g></Transition></svg>
  <NavIcon v-else :name="name"/>
</template>
