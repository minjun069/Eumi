import { fileURLToPath, URL } from "node:url"
import { defineConfig } from "vite"
import react from "@vitejs/plugin-react"
import tailwindcss from "@tailwindcss/vite"

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  server: {
    port: 5173,
    proxy: {
      // 기본은 실제 backend(8080). 가짜 API(8081)로 붙을 때만 VITE_API_TARGET을 준다 (README '실행')
      "/api": { target: process.env.VITE_API_TARGET ?? "http://localhost:8080", changeOrigin: true },
    },
  },
})