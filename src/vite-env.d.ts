/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly TAURI_FINCOACH_PORT?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
