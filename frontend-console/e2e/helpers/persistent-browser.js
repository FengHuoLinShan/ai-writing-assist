import { mkdtemp, rm } from "node:fs/promises"
import { tmpdir } from "node:os"
import path from "node:path"

/**
 * Launches a real persistent browser profile that can be closed and reopened.
 * Each launch owns its browser process; the generated profile is removed only
 * by dispose(), after every context using it has been closed.
 */
export async function createPersistentBrowserProfile(browserType, options = {}) {
  const profileDir = await mkdtemp(path.join(tmpdir(), "ai-writing-e2e-browser-"))
  let activeContext = null

  async function launch() {
    if (activeContext) throw new Error("persistent browser profile is already open")
    activeContext = await browserType.launchPersistentContext(profileDir, {
      headless: process.env.PW_HEADED !== "1",
      ...options,
    })
    return activeContext
  }

  async function close() {
    if (!activeContext) return
    const context = activeContext
    activeContext = null
    await context.close()
  }

  async function dispose() {
    await close()
    await rm(profileDir, { recursive: true, force: true })
  }

  return { profileDir, launch, close, dispose }
}
