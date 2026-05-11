import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";
// Tauri expects a fixed dev port and disables polling watchers on Windows.
export default defineConfig({
    plugins: [react()],
    resolve: {
        alias: {
            "@": path.resolve(__dirname, "./src"),
        },
    },
    clearScreen: false,
    server: {
        port: 5173,
        strictPort: true,
        watch: { ignored: ["**/src-tauri/**", "**/backend/**"] },
    },
    envPrefix: ["VITE_", "TAURI_"],
    build: {
        target: "es2022",
        sourcemap: true,
    },
});
