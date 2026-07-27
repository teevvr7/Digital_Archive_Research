import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  {
    rules: {
      // This app is a client-rendered SPA (every data page is "use client")
      // that fetches on mount / on tab or filter change — the textbook
      // "synchronizing with an external system" case React's own docs list
      // as a *valid* effect use, not an anti-pattern. eslint-plugin-react-hooks
      // 7.x's newer set-state-in-effect rule flags every one of these
      // (10+ instances across the app) toward a React-Compiler-era pattern
      // (external store / use() + Suspense) this codebase doesn't use.
      // Off project-wide rather than sprinkling a disable on every instance.
      "react-hooks/set-state-in-effect": "off",
    },
  },
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
  ]),
]);

export default eslintConfig;
