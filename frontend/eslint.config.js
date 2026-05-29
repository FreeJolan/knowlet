import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'
import { defineConfig, globalIgnores } from 'eslint/config'

export default defineConfig([
  globalIgnores(['dist']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      tseslint.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      globals: globals.browser,
    },
    linterOptions: {
      reportUnusedDisableDirectives: 'off',
    },
    rules: {
      // The React Compiler advisory rules are too broad for the current
      // codebase; keep them out of the blocking lint gate until we schedule
      // a dedicated React Compiler cleanup pass.
      'react-hooks/set-state-in-effect': 'off',
      'react-hooks/refs': 'off',
      // knowlet uses colocated helpers beside components; HMR still works for
      // our Vite setup, so this should not block the repository lint gate.
      'react-refresh/only-export-components': 'off',
    },
  },
])
