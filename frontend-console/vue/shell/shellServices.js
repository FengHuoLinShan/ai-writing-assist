/**
 * Phase 6 shell bridge. Vue shell components only consume this object; access to
 * the still-stable hash router, command registry, modal/toast services and
 * imperative writing/workspace seams stays centralized here.
 */

import { forceAccountSafeReload } from "../../shared/accountStorage.js"

function fallbackRoute(name) {
  return { title: name || "项目", subViews: [] }
}

export function createShellServices(overrides = {}) {
  const state = overrides.state ?? globalThis.appState ?? globalThis.state ?? {}
  const router = overrides.router ?? globalThis.router ?? {}
  const commands = overrides.commands ?? globalThis.commands ?? {}
  const api = overrides.api ?? globalThis.api ?? {}
  const toast = overrides.toast ?? globalThis.toast ?? (() => {})
  const closeModal = overrides.closeModal ?? globalThis.closeModal ?? (() => true)
  const subscribeState = overrides.subscribeState ?? globalThis.onStateChange
  const reload = overrides.reload ?? (() => globalThis.location.reload())
  const invalidateAccount = (reason = "account-invalidated") => {
    api.clearCache?.()
    return forceAccountSafeReload({ reason, reload })
  }

  return {
    state,
    subscribeState(listener) {
      if (typeof subscribeState !== "function") return () => {}
      const unsubscribe = subscribeState(listener)
      return typeof unsubscribe === "function" ? unsubscribe : () => {}
    },
    router: {
      getRoute(name) { return router.getRoute?.(name) || fallbackRoute(name) },
      getSubViewTitle(view, subview) { return router.getSubViewTitle?.(view, subview) || subview || "" },
      getLastSubView(view) { return router.getLastSubView?.(view) || null },
      getCurrentQuery() { return router.getCurrentQuery?.() },
      navigate(...args) { return router.navigate?.(...args) },
      init() { return router.initRouter?.() },
    },
    commands: {
      execute(input) { return commands.execute?.(input) },
      getSuggestions(prefix) { return commands.getSuggestions?.(prefix) || [] },
    },
    modal: {
      close(event) { return closeModal(event) },
      isOpen() {
        const overlay = document.getElementById("modal-overlay")
        return Boolean(overlay && !overlay.classList.contains("hidden"))
      },
    },
    health: {
      check() { return api.healthCheck?.() ?? false },
    },
    account: {
      visible: globalThis.accountAuthConfig?.auth_mode === "public",
      current: globalThis.currentAccount ?? null,
      config: globalThis.accountAuthConfig ?? { auth_mode: "local", wechat_enabled: false },
      invalidate: invalidateAccount,
      async logout() {
        try {
          await api.auth?.logout?.()
        } finally {
          invalidateAccount("logout")
        }
      },
    },
    workspace: {
      triggerAction(action, host) {
        const button = host?.querySelector?.(`[data-action="${action}"]`)
        if (!button) return false
        button.click()
        return true
      },
      moveSelection(direction, host) {
        const rows = Array.from(host?.querySelectorAll?.(
          ".data-table tr.clickable, .data-table tr[data-id], .project-card[data-id], .list-row[data-id]",
        ) || [])
        if (!rows.length) return false
        const selectedId = state.selectedItem?.id || state.selectedItem?.value || null
        const current = rows.findIndex((row) => (row.dataset.id || row.dataset.value) === selectedId)
        const next = current < 0
          ? (direction > 0 ? 0 : rows.length - 1)
          : (current + direction + rows.length) % rows.length
        for (const row of rows) row.classList.remove("selected")
        rows[next].classList.add("selected")
        rows[next].scrollIntoView?.({ block: "nearest" })
        state.selectedItem = { id: rows[next].dataset.id || rows[next].dataset.value }
        return true
      },
      autosave(host) {
        const button = host?.querySelector?.("#btn-autosave")
        if (button) {
          button.click()
          return true
        }
        if (!host?.dispatchEvent) return false
        const event = new CustomEvent("shell:save-request", { bubbles: false, cancelable: true })
        host.dispatchEvent(event)
        return event.defaultPrevented
      },
      toggleOutlineFloat(host) {
        const button = host?.querySelector?.('[data-action="toggle-outline-float"]')
        if (button) {
          button.click()
          return true
        }
        if (!host?.dispatchEvent) return false
        const event = new CustomEvent("shell:toggle-outline-float", { bubbles: false, cancelable: true })
        host.dispatchEvent(event)
        return event.defaultPrevented
      },
    },
    toast(message, type = "info") { toast(message, type) },
  }
}
