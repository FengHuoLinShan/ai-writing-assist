import { onBeforeUnmount, onMounted } from "vue"

function isFormControl(target) {
  return ["INPUT", "TEXTAREA", "SELECT"].includes(target?.tagName)
    || Boolean(target?.isContentEditable)
}

export function useShellShortcuts({
  services,
  shellState,
  getRouteHost,
  command,
  help,
  focusSidebar,
}) {
  const report = (prefix) => (err) => services.toast(`${prefix}：${err?.message || "未知错误"}`, "error")

  function trigger(action) {
    return services.workspace.triggerAction(action, getRouteHost())
  }

  function onKeydown(event) {
    const key = event.key
    const actionKey = key.length === 1 ? key.toLowerCase() : key
    const mod = event.ctrlKey || event.metaKey

    if (isFormControl(event.target)) {
      if (key === "Escape") {
        event.target.blur?.()
        services.state.mode = "NORMAL"
      }
      return
    }

    const overlayOpen = command.isOpen() || help.isOpen() || services.modal.isOpen()
    if (overlayOpen) {
      if (key === "Escape") {
        if (command.isOpen()) command.close()
        else if (services.modal.isOpen()) services.modal.close(event)
        else if (help.isOpen()) help.close()
      }
      return
    }

    if (mod && key.toLowerCase() === "s") {
      event.preventDefault()
      if (!services.workspace.autosave(getRouteHost())) trigger("save")
      return
    }
    if (mod && event.shiftKey && key.toLowerCase() === "o") {
      if (shellState.currentView === "writing") {
        event.preventDefault()
        services.workspace.toggleOutlineFloat(getRouteHost())
      }
      return
    }

    if (event.altKey || event.ctrlKey || event.metaKey) return

    if (key === "?") {
      event.preventDefault()
      help.open()
    } else if (key === ":" || key === "/") {
      event.preventDefault()
      command.open(key)
    } else if (key === "Escape") {
      if (shellState.currentSubView) {
        Promise.resolve(services.router.navigate(shellState.currentView, null)).catch(report("导航失败"))
      }
    } else if (["n", "e", "g", "x"].includes(actionKey)) {
      trigger(({ n: "new", e: "edit", g: "generate", x: "delete" })[actionKey])
    } else if (actionKey === "s") {
      if (!services.workspace.autosave(getRouteHost()) && !trigger("save")) services.toast("没有可保存的内容", "info")
    } else if (actionKey === "j" || actionKey === "k") {
      event.preventDefault()
      services.workspace.moveSelection(actionKey === "j" ? 1 : -1, getRouteHost())
    } else if (actionKey === "h") {
      event.preventDefault()
      focusSidebar()
    } else if (key === "Enter") {
      trigger("select")
    }
  }

  onMounted(() => document.addEventListener("keydown", onKeydown))
  onBeforeUnmount(() => document.removeEventListener("keydown", onKeydown))

  return { onKeydown }
}
