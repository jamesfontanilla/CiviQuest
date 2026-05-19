import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: "autoUpdate",
      workbox: {
        globPatterns: ["**/*.{js,css,html,ico,png,svg,woff2}"],
        runtimeCaching: [
          {
            urlPattern: /\/v1\/modules/,
            handler: "StaleWhileRevalidate",
            options: { cacheName: "content-modules" },
          },
          {
            urlPattern: /\/v1\/topics\/.*/,
            handler: "StaleWhileRevalidate",
            options: { cacheName: "content-topics" },
          },
          {
            urlPattern: /\/v1\/subtopics\/.*\/lesson/,
            handler: "StaleWhileRevalidate",
            options: { cacheName: "content-lessons" },
          },
          {
            urlPattern: /\/v1\/users\/me/,
            handler: "NetworkOnly",
          },
          {
            urlPattern: /\/v1\/progress\/snapshot/,
            handler: "NetworkOnly",
          },
          {
            urlPattern: /\/v1\/leaderboards\/.*/,
            handler: "NetworkOnly",
          },
        ],
      },
      manifest: false,
    }),
  ],
  server: {
    proxy: {
      "/v1": "http://localhost:8000",
    },
  },
});
