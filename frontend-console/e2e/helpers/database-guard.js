const DEDICATED_DATABASE_MARKER = /(?:^|[_-])(?:audit|e2e|test)(?:$|[_-])/i

export function validateE2EDatabaseEnvironment(profile, env = process.env) {
  const databaseUrl = String(env.DATABASE_URL || "").trim()
  if (!databaseUrl) {
    throw new Error(`${profile} requires an explicit dedicated PostgreSQL DATABASE_URL`)
  }

  let parsed
  try {
    parsed = new URL(databaseUrl)
  } catch {
    throw new Error(`${profile} requires a valid PostgreSQL DATABASE_URL`)
  }
  if (!/^postgres(?:ql)?(?:\+[a-z0-9._-]+)?:$/i.test(parsed.protocol)) {
    throw new Error(`${profile} requires PostgreSQL; received ${parsed.protocol || "unknown"}`)
  }

  const databaseName = decodeURIComponent(parsed.pathname.replace(/^\/+/, "")).trim()
  if (!databaseName || databaseName.includes("/") || !DEDICATED_DATABASE_MARKER.test(databaseName)) {
    throw new Error(`${profile} requires a dedicated audit/e2e/test database name`)
  }
  if (env.PW_REUSE_EXISTING_SERVER !== "0") {
    throw new Error(`${profile} requires PW_REUSE_EXISTING_SERVER=0 (fresh backend/frontend)`)
  }

  return Object.freeze({ databaseUrl, databaseName })
}
