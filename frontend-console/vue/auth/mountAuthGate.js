import { createApp } from "vue"
import AuthGate from "./AuthGate.vue"

export function mountAuthGate({ config, account = null, onAuthenticated, onLogout }) {
  const root = document.querySelector("#app")
  if (!root) throw new Error("Auth mount target is missing")
  const app = createApp(AuthGate, {
    config,
    initialAccount: account,
    onAuthenticated,
    onLogout,
  })
  app.mount(root)
  return { unmount: () => app.unmount() }
}
