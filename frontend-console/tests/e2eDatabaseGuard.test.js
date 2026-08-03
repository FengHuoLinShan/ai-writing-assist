import { describe, expect, it } from "vitest"

import { validateE2EDatabaseEnvironment } from "../e2e/helpers/database-guard.js"

const validEnvironment = {
  DATABASE_URL: "postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/ai_writing_browser_e2e_test",
  PW_REUSE_EXISTING_SERVER: "0",
}

describe("E2E 数据库 guard", () => {
  it("接受 asyncpg PostgreSQL URL 并返回冻结的规范结果", () => {
    const result = validateE2EDatabaseEnvironment("browser smoke", validEnvironment)

    expect(result).toEqual({
      databaseUrl: validEnvironment.DATABASE_URL,
      databaseName: "ai_writing_browser_e2e_test",
    })
    expect(Object.isFrozen(result)).toBe(true)
  })

  it.each([
    ["missing", {}],
    ["malformed", { ...validEnvironment, DATABASE_URL: "not a database url" }],
  ])("rejects %s database URLs", (_label, env) => {
    expect(() => validateE2EDatabaseEnvironment("browser smoke", env)).toThrow(
      /requires an explicit dedicated PostgreSQL DATABASE_URL|requires a valid PostgreSQL DATABASE_URL/,
    )
  })

  it("rejects non-PostgreSQL URLs", () => {
    expect(() => validateE2EDatabaseEnvironment("browser smoke", {
      ...validEnvironment,
      DATABASE_URL: "mysql://localhost/ai_writing_e2e_test",
    })).toThrow("requires PostgreSQL; received mysql:")
  })

  it.each([
    "postgresql://localhost/production",
    "postgresql://localhost/contest",
    "postgresql://localhost/ai_writing_e2eproduction",
    "postgresql://localhost/ai_writing_e2e_test/nested",
  ])("rejects unsafe or non-standalone database name %s", (databaseUrl) => {
    expect(() => validateE2EDatabaseEnvironment("browser smoke", {
      ...validEnvironment,
      DATABASE_URL: databaseUrl,
    })).toThrow("requires a dedicated audit/e2e/test database name")
  })

  it.each([undefined, "", "1", "false", " 0"])(
    "rejects PW_REUSE_EXISTING_SERVER=%j unless it is exactly 0",
    (reuseExistingServer) => {
      expect(() => validateE2EDatabaseEnvironment("browser smoke", {
        ...validEnvironment,
        PW_REUSE_EXISTING_SERVER: reuseExistingServer,
      })).toThrow("requires PW_REUSE_EXISTING_SERVER=0 (fresh backend/frontend)")
    },
  )
})
