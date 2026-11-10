import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// 브라우저는 같은 출처의 /subscriptions/... 를 부르고 Vite가 anf-api로 넘긴다 (대시보드 설계 결정 1).
// anf-api에는 CORS가 없다. 127.0.0.1에만 바인딩한다 (NFR-07).
// 메트릭은 /prometheus/... 로 불러 Prometheus의 /api/v1/... 로 넘긴다 (메트릭 설계 §3).
const proxy = {
  "/subscriptions": process.env.ANF_API_URL ?? "http://127.0.0.1:8080",
  "/prometheus": {
    target: process.env.ANF_PROMETHEUS_URL ?? "http://127.0.0.1:9090",
    rewrite: (path: string) => path.replace(/^\/prometheus/, ""),
  },
};

export default defineConfig({
  plugins: [react()],
  server: { host: "127.0.0.1", port: 5173, strictPort: true, proxy },
  preview: { host: "127.0.0.1", port: 4173, strictPort: true, proxy },
  test: { environment: "jsdom", restoreMocks: true },
});
