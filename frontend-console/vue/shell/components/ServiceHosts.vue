<template>
  <div id="toast-container" data-imperative-service-host="toast"></div>
  <div id="modal-overlay" class="hidden" data-imperative-service-host="modal" @click.self="close">
    <div id="modal-content" role="dialog" aria-modal="true" aria-labelledby="modal-title">
      <div id="modal-header"><span id="modal-title"></span><button id="modal-close" type="button" aria-label="关闭对话框" @click="close">×</button></div>
      <div id="modal-body"></div><div id="modal-footer"></div>
    </div>
  </div>
</template>

<script setup>
const props = defineProps({ services: { type: Object, required: true } })
function close(event) { if (props.services.modal.close(event) === false) { event.preventDefault(); event.stopPropagation() } }
</script>
