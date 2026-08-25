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
    // This editor intentionally leaves textarea values DOM-owned so save/rerender
    // does not reset the author's selection or cursor.
    files: ["vue/views/world/bible/WorldBibleTab.vue"],
    rules: {
      "vue/no-textarea-mustache": "off",
    },
  },
]
