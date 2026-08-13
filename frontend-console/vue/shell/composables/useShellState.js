import { onBeforeUnmount, onMounted, reactive } from "vue"

const SHELL_STATE_KEYS = [
  "currentProjectId", "currentProject", "currentView", "currentSubView",
  "backendConnected",
]

export function useShellState(services) {
  const shellState = reactive(Object.fromEntries(
    SHELL_STATE_KEYS.map((key) => [key, services.state?.[key] ?? null]),
  ))
  let unsubscribe = () => {}

  onMounted(() => {
    unsubscribe = services.subscribeState((key, value) => {
      if (SHELL_STATE_KEYS.includes(key)) shellState[key] = value
    })
  })
  onBeforeUnmount(() => unsubscribe())

  return shellState
}
