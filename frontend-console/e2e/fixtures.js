import { expect, request, test as base } from "@playwright/test"

import { cleanupProject, createProject } from "./helpers/api-client.js"
import { openWorkbench } from "./helpers/workbench.js"

export const test = base.extend({
  browserErrors: [async ({ page }, use, testInfo) => {
    const errors = []
    const onConsole = (message) => {
      if (message.type() === "error") {
        errors.push({ kind: "console", text: message.text() })
      }
    }
    const onPageError = (error) => {
      errors.push({ kind: "pageerror", text: error?.stack || error?.message || String(error) })
    }
    const onResponse = (response) => {
      if (response.status() >= 500) {
        errors.push({ kind: "response", status: response.status(), url: response.url() })
      }
    }

    page.on("console", onConsole)
    page.on("pageerror", onPageError)
    page.on("response", onResponse)
    await use(errors)

    page.off("console", onConsole)
    page.off("pageerror", onPageError)
    page.off("response", onResponse)
    if (testInfo.status !== testInfo.expectedStatus && errors.length > 0) {
      await testInfo.attach("browser-errors", {
        body: Buffer.from(JSON.stringify(errors, null, 2)),
        contentType: "application/json",
      })
    }
  }, { auto: true }],

  projectFactory: async ({}, use) => {
    const projectIds = []
    await use(async (payload = {}) => {
      const project = await createProject({
        title: `E2E ${Date.now()} ${projectIds.length + 1}`,
        language: "zh",
        ...payload,
      })
      projectIds.push(project.id)
      return project
    })
    for (const projectId of projectIds.reverse()) {
      try { await cleanupProject(projectId) } catch {}
    }
  },

  openProjectWorkbench: async ({ page }, use) => {
    await use((project, view = "writing", subview = null) => (
      openWorkbench(page, project, view, subview)
    ))
  },
})

export { expect, request }
