/** In-memory demo store for the WebUI-triggered dbt refresh (demo mode only).
 *
 * Mirrors the `/meta/refresh` outcome deterministically — always succeeds
 * immediately with a fixed timestamp — so the refresh button is exercisable
 * without dbt, a database, or the shared lock/marker (issue #285). Loaded
 * only via dynamic import when `VITE_PENGE_DEMO=true`.
 */

import type { MetaRefreshResponse } from "../api/schemas";

const DEMO_COMPLETED_AT = "2026-06-01T09:00:00Z";

export function demoMetaRefresh(): MetaRefreshResponse {
  return { status: "succeeded", completed_at: DEMO_COMPLETED_AT };
}
