import { describe, expect, it, vi } from "vitest"

import { registerViewLoaders } from "../vue/viewLoaders.js"

describe("route-level island loader registration", () => {
  it("registers loader functions without loading business islands during public bootstrap", () => {
    const publicAuthRouter = { registerViewLoader: vi.fn() }
    const businessLoader = vi.fn(async () => {})

    registerViewLoaders(publicAuthRouter, { home: businessLoader })

    expect(publicAuthRouter.registerViewLoader).toHaveBeenCalledWith("home", businessLoader)
    expect(businessLoader).not.toHaveBeenCalled()
  })
})
