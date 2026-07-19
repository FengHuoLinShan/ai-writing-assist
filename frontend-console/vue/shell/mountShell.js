import { createPinia } from "pinia"
import { createApp } from "vue"
import ShellApp from "./ShellApp.vue"
import { createShellServices } from "./shellServices.js"

export async function mountShell({ target = "#app", services = createShellServices(), healthIntervalMs = 30_000 } = {}) {
  const root = typeof target === "string" ? document.querySelector(target) : target
  if (!root) throw new Error("Vue shell mount target is missing")
  const app = createApp(ShellApp, { services, healthIntervalMs })
  app.use(createPinia())
  const shell = app.mount(root)
  try {
    await services.router.init()
  } catch (error) {
    app.unmount()
    throw error
  }
  return {
    app,
    shell,
    getRouteHost: () => shell.getRouteHost(),
    updateWordcountDashboard: (value) => shell.updateWordcountDashboard(value),
    unmount: () => app.unmount(),
  }
}
