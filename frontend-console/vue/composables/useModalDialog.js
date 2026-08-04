import { nextTick, onBeforeUnmount, ref, watch } from "vue"

const inertLeases = new Map()
const FOCUSABLE = "a[href], button, input, select, textarea, summary, [contenteditable]:not([contenteditable='false']), [tabindex]"

function isServiceHost(element) { return element?.matches?.("[data-imperative-service-host]") }

function lease(elements) {
  const owned = new Set()
  for (const element of elements) {
    if (!element || isServiceHost(element)) continue
    const entry = inertLeases.get(element)
    if (entry) entry.count += 1
    else {
      inertLeases.set(element, { count: 1, wasInert: element.hasAttribute("inert") })
      if (!element.hasAttribute("inert")) element.setAttribute("inert", "")
    }
    owned.add(element)
  }
  return owned
}

function release(owned) {
  for (const element of owned) {
    const entry = inertLeases.get(element)
    if (!entry) continue
    entry.count -= 1
    if (entry.count <= 0) {
      inertLeases.delete(element)
      if (!entry.wasInert) element.removeAttribute("inert")
    }
  }
  owned.clear()
}

function backgroundSiblings(overlay) {
  const boundary = overlay?.closest(".vue-shell-root") || document.body
  const targets = []
  for (let branch = overlay; branch && branch !== boundary; branch = branch.parentElement) {
    const parent = branch.parentElement
    if (!parent) break
    for (const sibling of parent.children) {
      if (sibling !== branch && !sibling.contains(overlay)) targets.push(...nonServiceBranches(sibling))
    }
  }
  if (boundary === document.body && overlay === document.body) return targets
  return targets
}

function nonServiceBranches(element) {
  if (!element || isServiceHost(element)) return []
  if (!element.querySelector?.("[data-imperative-service-host]")) return [element]
  return Array.from(element.children).flatMap(nonServiceBranches)
}

function hiddenByClosedDetails(element) {
  const details = element.closest("details:not([open])")
  return Boolean(details && element !== details.querySelector(":scope > summary"))
}

function disabledByFieldset(element) {
  const fieldset = element.closest("fieldset[disabled]")
  if (!fieldset) return false
  const firstLegend = fieldset.querySelector(":scope > legend")
  return !firstLegend?.contains(element)
}

function isFocusable(element, boundary) {
  if (!(element instanceof HTMLElement) || element.hidden || element.disabled === true || element.matches(":disabled") || disabledByFieldset(element)) return false
  if (element.getAttribute("aria-hidden") === "true" || element.closest("[aria-hidden='true'], [inert]")) return false
  if (element.getAttribute("contenteditable") === "false" || hiddenByClosedDetails(element)) return false
  for (let current = element; current && current !== boundary.parentElement; current = current.parentElement) {
    const style = getComputedStyle(current)
    if (style.display === "none" || style.visibility === "hidden") return false
    if (current === boundary) break
  }
  return element.tabIndex >= 0 || element.tagName === "SUMMARY"
}

function focusables(dialog) {
  return dialog ? Array.from(dialog.querySelectorAll(FOCUSABLE)).filter((element) => isFocusable(element, dialog)) : []
}

function validOrigin(element) {
  return Boolean(element?.isConnected && isFocusable(element, document.body))
}

function focusGlobalModal() {
  const content = document.getElementById("modal-content")
  if (!content) return
  content.setAttribute("tabindex", "-1")
  content.focus()
}

export function useModalDialog({ isOpen, requestClose, canClose = () => true }) {
  const overlayRef = ref(null)
  const dialogRef = ref(null)
  const origin = ref(null)
  const lastDialogFocus = ref(null)
  const backgroundLease = new Set()
  const nestedLease = new Set()
  let generation = 0
  let observer = null
  let originObserver = null
  let restoreFrame = null
  let expectedOriginInertMutations = 0
  let originBecameInert = false

  function observeOriginInert() {
    originObserver?.disconnect()
    originObserver = null
    expectedOriginInertMutations = 0
    originBecameInert = false
    if (!origin.value || typeof MutationObserver === "undefined") return
    originObserver = new MutationObserver((records) => {
      for (const record of records) {
        if (record.attributeName !== "inert") continue
        if (expectedOriginInertMutations > 0) {
          expectedOriginInertMutations -= 1
        } else if (origin.value?.hasAttribute("inert")) {
          originBecameInert = true
        }
      }
    })
    originObserver.observe(origin.value, { attributes: true, attributeFilter: ["inert"] })
  }

  function focusInitial() {
    const dialog = dialogRef.value
    if (!dialog) return
    const candidates = focusables(dialog)
    const body = dialog.querySelector(".modal-body, .vue-map-dialog__body")
    const footer = dialog.querySelector(".modal-footer, footer")
    const target = candidates.find((element) => element.hasAttribute("autofocus"))
      || candidates.find((element) => body?.contains(element))
      || candidates.find((element) => footer?.contains(element))
      || candidates[0]
      || dialog
    if (target === dialog) dialog.setAttribute("tabindex", "-1")
    target.focus()
  }

  function globalVisible() {
    const globalOverlay = document.getElementById("modal-overlay")
    return Boolean(globalOverlay && !globalOverlay.classList.contains("hidden"))
  }

  function queueGlobalFocus(currentGeneration) {
    void nextTick(() => {
      if (currentGeneration !== generation || !isOpen() || !globalVisible()) return
      const globalOverlay = document.getElementById("modal-overlay")
      if (globalOverlay && !globalOverlay.contains(document.activeElement)) focusGlobalModal()
    })
  }

  function cancelDeferredRestore() {
    if (restoreFrame != null && typeof cancelAnimationFrame === "function") cancelAnimationFrame(restoreFrame)
    restoreFrame = null
  }

  function restoreAfterRender(currentGeneration, restore) {
    const run = () => {
      restoreFrame = null
      if (currentGeneration !== generation || !isOpen() || globalVisible()) return
      if (restore && validOrigin(restore) && dialogRef.value?.contains(restore)) restore.focus()
      else focusInitial()
    }
    if (typeof requestAnimationFrame === "function") restoreFrame = requestAnimationFrame(run)
    else run()
  }

  function syncNestedModal() {
    const currentGeneration = generation
    if (!isOpen()) return
    const globalOverlay = document.getElementById("modal-overlay")
    if (globalVisible()) {
      cancelDeferredRestore()
      if (!nestedLease.size && overlayRef.value) {
        if (dialogRef.value?.contains(document.activeElement)) lastDialogFocus.value = document.activeElement
        for (const element of lease([overlayRef.value])) nestedLease.add(element)
      }
      if (globalOverlay && !globalOverlay.contains(document.activeElement)) queueGlobalFocus(currentGeneration)
      return
    }
    if (!nestedLease.size) return
    release(nestedLease)
    // The control that opened a global confirmation can still be disabled
    // until its async continuation clears `saving`.  Preserve the connected
    // in-dialog candidate now, then validate after Vue has flushed that
    // continuation rather than discarding it while it is temporarily inert.
    const restore = lastDialogFocus.value?.isConnected && dialogRef.value?.contains(lastDialogFocus.value)
      ? lastDialogFocus.value : null
    void nextTick(() => {
      if (currentGeneration !== generation || !isOpen() || globalVisible()) return
      restoreAfterRender(currentGeneration, restore)
    })
  }

  function observeNestedModal() {
    observer?.disconnect()
    const globalOverlay = document.getElementById("modal-overlay")
    if (!globalOverlay) return
    observer = new MutationObserver(syncNestedModal)
    observer.observe(globalOverlay, { attributes: true, attributeFilter: ["class"] })
    syncNestedModal()
  }

  function releaseAll() {
    cancelDeferredRestore()
    release(backgroundLease)
    release(nestedLease)
    observer?.disconnect()
    observer = null
    originObserver?.disconnect()
    originObserver = null
  }

  function onFocusin(event) {
    if (dialogRef.value?.contains(event.target)) lastDialogFocus.value = event.target
  }

  function onKeydown(event) {
    event.stopPropagation()
    if (event.key === "Escape") {
      event.preventDefault()
      if (canClose()) requestClose()
      return
    }
    if (event.key !== "Tab") return
    const dialog = dialogRef.value
    const items = focusables(dialog)
    if (!items.length) {
      event.preventDefault()
      dialog?.focus()
      return
    }
    const active = document.activeElement
    const first = items[0]
    const last = items[items.length - 1]
    if (event.shiftKey && (active === first || !items.includes(active))) {
      event.preventDefault()
      last.focus()
    } else if (!event.shiftKey && (active === last || !items.includes(active))) {
      event.preventDefault()
      first.focus()
    }
  }

  watch(isOpen, (open) => {
    const currentGeneration = ++generation
    if (!open) {
      const blockedOrigin = originBecameInert
      releaseAll()
      const previous = origin.value
      origin.value = null
      void nextTick(() => {
        if (currentGeneration === generation && !isOpen() && !globalVisible() && !blockedOrigin && validOrigin(previous)) previous.focus()
      })
      return
    }
    origin.value = document.activeElement instanceof HTMLElement ? document.activeElement : null
    observeOriginInert()
    void nextTick(() => {
      if (currentGeneration !== generation || !isOpen() || !overlayRef.value || !dialogRef.value) return
      const backgrounds = backgroundSiblings(overlayRef.value)
      if (backgrounds.includes(origin.value) && !origin.value?.hasAttribute("inert")) expectedOriginInertMutations += 1
      for (const element of lease(backgrounds)) backgroundLease.add(element)
      focusInitial()
      observeNestedModal()
    })
  }, { flush: "post", immediate: true })

  onBeforeUnmount(() => {
    ++generation
    releaseAll()
  })

  return { overlayRef, dialogRef, onKeydown, onFocusin }
}
