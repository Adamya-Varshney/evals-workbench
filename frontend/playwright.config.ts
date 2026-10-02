import { defineConfig } from "@playwright/test";
import { existsSync } from "node:fs";
import { join } from "node:path";

const win = process.platform === "win32";
const venvPy = join("..", "backend", ".venv", win ? "Scripts/python.exe" : "bin/python");
const py = existsSync(venvPy) ? venvPy : "python";

export default defineConfig({
  testDir: "e2e",
  timeout: 90_000,
  use: { baseURL: "http://127.0.0.1:5174", viewport: { width: 1440, height: 900 } },
  webServer: [
    { command: `"${py}" ../backend/e2e_server.py 8011`, url: "http://127.0.0.1:8011/api/meta", reuseExistingServer: false, timeout: 60_000 },
    {
      command: "npx vite --host 127.0.0.1 --port 5174 --strictPort",
      url: "http://127.0.0.1:5174",
      reuseExistingServer: false,
      timeout: 60_000,
      env: { VITE_API_TARGET: "http://127.0.0.1:8011", VITE_PORT: "5174" },
    },
  ],
});
