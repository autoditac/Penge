/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Base URL of the Penge read API (defaults to http://127.0.0.1:8000). */
  readonly VITE_PENGE_API_URL?: string;
  /** Set to "true" to serve deterministic synthetic fixtures instead of the API. */
  readonly VITE_PENGE_DEMO?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
