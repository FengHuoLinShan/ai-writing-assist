import { describe, expect, it } from "vitest"

import { redactSensitiveValue } from "../../shared/redactSensitive.js"

describe("redactSensitiveValue", () => {
  it("redacts secrets while safely replacing circular references", () => {
    const value = { api_key: "secret", safe: "visible" }
    value.self = value

    expect(redactSensitiveValue(value)).toEqual({
      api_key: "[REDACTED]",
      safe: "visible",
      self: "[Circular]",
    })
  })
})
