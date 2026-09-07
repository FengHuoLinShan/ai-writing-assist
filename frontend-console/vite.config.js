import { defineConfig } from "vite"
import vue from "@vitejs/plugin-vue"
import { chmod, copyFile, mkdir, readFile, writeFile } from "node:fs/promises"
import { dirname, resolve } from "node:path"
import { fileURLToPath } from "node:url"

const frontendPort = Number.parseInt(process.env.FRONTEND_PORT || "8080", 10)
const backendPort = Number.parseInt(process.env.BACKEND_PORT || "8000", 10)
const frontendRoot = dirname(fileURLToPath(import.meta.url))
const isProductionBuild = process.argv.includes("build")
const apiProxyTarget = process.env.API_PROXY_TARGET
  || `http://127.0.0.1:${Number.isNaN(backendPort) ? 8000 : backendPort}`
const legacyRuntimeAssets = [
  "theme-preload.js",
  "shared/esc.js",
  "ui/toast.js",
  "ui/modal.js",
  "stateSlices.js",
  "state.js",
  "apiContracts.js",
  "router.js",
  "commands.js",
]
const thirdPartyLicenseAssets = [{ source: resolve(frontendRoot, 'node_modules/fflate/LICENSE'), destination: 'licenses/fflate.txt' }]
const contentSecurityPolicy = [
  "default-src 'self'",
  "script-src 'self'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "connect-src 'self' http://localhost:* http://127.0.0.1:* ws://localhost:* ws://127.0.0.1:*",
  "object-src 'none'",
  "base-uri 'self'",
  "frame-ancestors 'none'",
].join("; ")

export const frontendSecurityHeaders = Object.freeze({
  "Content-Security-Policy": contentSecurityPolicy,
  "X-Frame-Options": "DENY",
})

export async function copyReadableRuntimeFile(source, destination) {
  await mkdir(dirname(destination), { recursive: true })
  await copyFile(source, destination)
  await chmod(destination, 0o644)
}

function copyLegacyRuntimeAssets() {
  return {
    name: "copy-legacy-runtime-assets",
    apply: "build",
    async writeBundle(outputOptions) {
      const outputRoot = resolve(frontendRoot, outputOptions.dir || "dist")
      await Promise.all(legacyRuntimeAssets.map(async (assetPath) => {
        const destination = resolve(outputRoot, assetPath)
        await copyReadableRuntimeFile(resolve(frontendRoot, assetPath), destination)
      }))
    },
  }
}

function copyThirdPartyLicenses() {
  return {
    name: "copy-third-party-licenses",
    apply: "build",
    async writeBundle(outputOptions) {
      const outputRoot = resolve(frontendRoot, outputOptions.dir || "dist")
      await Promise.all(thirdPartyLicenseAssets.map(({ source, destination }) => (
        copyReadableRuntimeFile(source, resolve(outputRoot, destination))
      )))
    },
  }
}

export default defineConfig({
  // Production is served through the same OpenResty origin as /api. Development
  // keeps the existing localhost fallback in api.js.
  define: isProductionBuild ? { API_HOST: JSON.stringify("") } : {},
  plugins: [vue(), copyLegacyRuntimeAssets(), copyThirdPartyLicenses(), {
    name: 'register-theme-worker-asset',
    apply: 'build',
    async writeBundle(options, bundle) {
      const worker = Object.keys(bundle).find(path => /^assets\/themeArchive\.worker-[\w-]+\.js$/.test(path))
      if (!worker) throw new Error('Theme archive worker is missing from the build')
      const path = resolve(frontendRoot, options.dir || 'dist', 'asset-manifest.json')
      const manifest = JSON.parse(await readFile(path, 'utf8'))
      manifest['licenses/fflate.txt'] = { file: 'licenses/fflate.txt' }
      manifest['vue/theme/themeArchive.worker.js'] = { file: worker, src: 'vue/theme/themeArchive.worker.js', isEntry: true }
      await writeFile(path, JSON.stringify(manifest, null, 2))
    },
  }],
  build: isProductionBuild ? { manifest: "asset-manifest.json" } : undefined,
  server: {
    host: "0.0.0.0",
    port: Number.isNaN(frontendPort) ? 8080 : frontendPort,
    strictPort: true,
    headers: frontendSecurityHeaders,
    proxy: {
      "^/api(?:/|$)": {
        target: apiProxyTarget,
        changeOrigin: true,
      },
    },
    watch: {
      // Test sources and Playwright artifacts are not application inputs.
      // Watching them can reload a page while an E2E flow is still running.
      ignored: [
        "**/tests/**",
        "**/e2e/**",
        "**/test-results/**",
        "**/playwright-report/**",
      ],
    },
  },
  preview: {
    headers: frontendSecurityHeaders,
  },
})
