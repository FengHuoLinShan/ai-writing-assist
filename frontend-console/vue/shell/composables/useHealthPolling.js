import { onBeforeUnmount, onMounted, ref } from "vue"

export function useHealthPolling(services, { intervalMs = 30_000 } = {}) {
  const connected = ref(Boolean(services.state?.backendConnected))
  let interval = null
  let generation = 0
  let disposed = false

  async function checkNow() {
    const scope = ++generation
    let result = false
    try { result = Boolean(await services.health.check()) } catch {}
    if (disposed || scope !== generation) return connected.value
    connected.value = result
    services.state.backendConnected = result
    return result
  }

  function stop() {
    disposed = true
    generation += 1
    if (interval !== null) clearInterval(interval)
    interval = null
  }

  onMounted(() => {
    disposed = false
    checkNow()
    interval = setInterval(checkNow, intervalMs)
  })
  onBeforeUnmount(stop)

  return { connected, checkNow, stop }
}
