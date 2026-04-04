import { defineConfig } from "vitest/config"
import react from "@vitejs/plugin-react-swc"
import path from "path"

// Use root workspace React so @testing-library/react and components share the same instance
const reactPath = path.resolve(__dirname, "../node_modules/react")
const reactDomPath = path.resolve(__dirname, "../node_modules/react-dom")

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    globals: true,
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
    alias: {
      "react": reactPath,
      "react-dom": reactDomPath,
      "react/jsx-runtime": path.join(reactPath, "jsx-runtime"),
      "react/jsx-dev-runtime": path.join(reactPath, "jsx-dev-runtime"),
    },
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
      "react": reactPath,
      "react-dom": reactDomPath,
      "react/jsx-runtime": path.join(reactPath, "jsx-runtime"),
      "react/jsx-dev-runtime": path.join(reactPath, "jsx-dev-runtime"),
    },
    dedupe: ["react", "react-dom", "react/jsx-runtime"],
  },
})
