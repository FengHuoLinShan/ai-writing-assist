import js from "@eslint/js"
import pluginVue from "eslint-plugin-vue"
import globals from "globals"

export default [
  {
    ignores: [
      "coverage/**",
      "dist/**",
      "e2e/**/*-snapshots/**",
      "node_modules/**",
      "playwright-report/**",
      "test-results/**",
    ],
  },
  js.configs.recommended,
  ...pluginVue.configs["flat/essential"],
  {
    files: ["**/*.{js,mjs,vue}"],
    languageOptions: {
      ecmaVersion: "latest",
      sourceType: "module",
      globals: {
        ...globals.browser,
        ...globals.es2026,
        API_HOST: "readonly",
        api: "readonly",
        closeModal: "readonly",
        confirmAction: "readonly",
        esc: "readonly",
        onStateChange: "readonly",
        refreshModalFormBaseline: "readonly",
        router: "readonly",
        routes: "readonly",
        showModal: "readonly",
        showModalHtml: "readonly",
        showToastNotification: "readonly",
        state: "readonly",
        toast: "readonly",
      },
    },
    rules: {
      "no-control-regex": "off",
      "no-empty": "off",
      "no-unused-vars": ["error", {
        argsIgnorePattern: "^_",
        caughtErrorsIgnorePattern: "^_",
        varsIgnorePattern: "^_",
      }],
      "no-useless-assignment": "off",
      "preserve-caught-error": "off",
      "vue/multi-word-component-names": "off",
      "vue/no-mutating-props": ["error", { shallowOnly: true }],
      // P1 规避项：零 v-html 从两处局部测试断言升级为全局 lint 门。
      "vue/no-v-html": "error",
    },
  },
  {
    files: [
      "*.config.js",
      "e2e/**/*.{js,mjs}",
      "eslint.config.js",
      "scripts/**/*.{js,mjs}",
      "vite.config.js",
    ],
    languageOptions: {
      globals: globals.node,
    },
  },
  {
    files: ["tests/**/*.{js,mjs,vue}"],
    languageOptions: {
      globals: {
        ...globals.node,
        ...globals.vitest,
      },
    },
    rules: {
      "no-constant-condition": "off",
      "require-yield": "off",
    },
  },
  {
    files: ["e2e/fixtures.js"],
    rules: {
      "no-empty-pattern": "off",
    },
  },
  {
    files: ["shared/esc.js", "ui/toast.js"],
    rules: {
      "no-unused-vars": "off",
    },
  },
  {
    // These components keep raw props under `props` and expose composable refs
    // with the same field names; the bindings do not collide at runtime.
    files: [
      "vue/views/outline/story/OutlineStoryTab.vue",
      "vue/views/scene/SceneWorkbenchView.vue",
    ],
    rules: {
      "vue/no-dupe-keys": "off",
    },
  },
  {
    // B2 跨模块 import 守护门（前端）：vue/** 内禁用基建裸全局，基建访问
    // 只经 vue/bridge/index.js（no-restricted-imports 限制直接 import 相对
    // 路径逃逸 bridge；全局只读声明继续服务旧式页面脚本）。
    // AO-14 补充：no-restricted-globals 只拦裸标识符，拦不住 globalThis.x /
    // window.x 的旁路读取，故追加 no-restricted-properties 封堵；
    // vue/bridge/index.js 是唯一被授权触碰基建全局的桥接层（行内豁免）。
    files: ["vue/**/*.{js,mjs,vue}"],
    rules: {
      "no-restricted-globals": ["error",
        { name: "api", message: "vue/** 内请从 ../../bridge/index.js 获取 getApi()" },
        { name: "state", message: "vue/** 内请从 bridge 获取 state 访问" },
        { name: "router", message: "vue/** 内请从 bridge 获取 getRouter()" },
        { name: "toast", message: "vue/** 内请从 bridge 获取 getToast()" },
        { name: "esc", message: "vue/** 内请从 bridge 获取转义工具" },
      ],
      "no-restricted-imports": ["error", {
        patterns: [{
          group: ["*/shared/esc.js", "**/shared/esc.js", "*/ui/toast.js", "**/ui/toast.js", "*/api.js", "**/api.js", "*/state.js", "**/state.js", "*/router.js", "**/router.js"],
          message: "基建访问只经 vue/bridge/index.js（B2 守护门）",
        }],
      }],
      "no-restricted-properties": ["error",
        { object: "globalThis", property: "api", message: "vue/** 内请从 vue/bridge/index.js 获取 getApi()" },
        { object: "globalThis", property: "appState", message: "vue/** 内请从 vue/bridge/index.js 获取 getAppState()" },
        { object: "globalThis", property: "router", message: "vue/** 内请从 vue/bridge/index.js 获取 getRouter()" },
        { object: "globalThis", property: "toast", message: "vue/** 内请从 vue/bridge/index.js 获取 getToast()" },
        { object: "window", property: "api", message: "vue/** 内请从 vue/bridge/index.js 获取 getApi()" },
        { object: "window", property: "appState", message: "vue/** 内请从 vue/bridge/index.js 获取 getAppState()" },
        { object: "window", property: "router", message: "vue/** 内请从 vue/bridge/index.js 获取 getRouter()" },
        { object: "window", property: "toast", message: "vue/** 内请从 vue/bridge/index.js 获取 getToast()" },
      ],
    },
  },
  {
    // This editor intentionally leaves textarea values DOM-owned so save/rerender
    // does not reset the author's selection or cursor.
    files: ["vue/views/world/bible/WorldBibleTab.vue"],
    rules: {
      "vue/no-textarea-mustache": "off",
    },
  },
]
