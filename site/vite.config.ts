import { defineConfig } from "vite";

export default defineConfig({
  root: ".",
  base: process.env.GITHUB_PAGES === "1" ? "/s7bb/" : "/",
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
  server: {
    fs: {
      allow: [".."],
    },
  },
});
