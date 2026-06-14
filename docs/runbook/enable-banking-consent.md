# Enable Banking consent (production)

The PSD2 connectors ([GLS](../connectors/gls.md),
[Evangelische Bank](../connectors/evangelische-bank.md),
[Lunar](../connectors/lunar.md)) obtain account access through Enable
Banking's PSU-driven consent flow.
Enable Banking's **production** application rejects
`http://localhost:8765/callback` because production redirect URLs must
use HTTPS.

Penge runs behind `https://penge.eigmueller.de` (TLS terminated by
nginx on the NAS, all application routes gated by oauth2-proxy with
Google OIDC).
The consent redirect is served from a dedicated **un-gated** path.

## Why the callback is un-gated

After the PSU approves consent at the bank, the ASPSP redirects the
browser to the registered redirect URL with `?code=<CODE>&state=...`.
This is a top-level navigation initiated by the bank, so it can arrive
without a Penge/Google session cookie.
If the callback sat behind the Google auth gate, the redirect would be
bounced to a Google login and the `code` would be lost.

The callback therefore lives at a single un-gated location:

```text
https://penge.eigmueller.de/eb/callback
```

It serves a static landing page only.
The page reads the `code` query parameter and displays it for
copy/paste; it never exchanges the code.
Exposing the page without auth is safe: the authorization code is
single-use, short-lived, and useless without the connector's private
RSA key, which lives only on the machine that runs the CLI.

The remaining routes (`/`, `/accounts`, the SPA assets, the API) stay
behind the Google login wall.

## Registering the redirect URL

In the Enable Banking **production** application, add this exact value
to the allowed redirect URLs:

```text
https://penge.eigmueller.de/eb/callback
```

The Enable Banking application is shared across all PSD2 connectors, so
this single redirect URL covers GLS, Evangelische Bank, and Lunar.

## Running the consent flow

Run the connector CLI from the machine that holds the Enable Banking
private key (the workstation), passing the hosted callback:

```fish
penge-gls link --redirect-url https://penge.eigmueller.de/eb/callback --days 180
# → prints { "consent_url": "...", "authorization_id": "..." }
```

1. Open `consent_url` in a browser and approve at the bank.
2. The bank redirects to `https://penge.eigmueller.de/eb/callback?code=<CODE>&state=...`.
3. The callback page shows `<CODE>` with a copy button.
4. On the CLI machine, exchange it:

   ```fish
   penge-gls authorize --code <CODE>
   ```

5. Save the printed `session_id` and sync:

   ```fish
   set -gx GLS_SESSION_ID <session_id>
   penge-gls sync --entity-name "Your Name" --days 365
   ```

Substitute `penge-ebank` or `penge-lunar` for the other ASPSPs; the
redirect URL is identical.

## nginx configuration

The un-gated location is defined in
`/etc/nginx/conf.d/penge.eigmueller.de.conf` on the NAS:

```nginx
location = /eb/callback {
    root  /var/www/penge-eb;
    try_files /index.html =404;
    add_header X-Robots-Tag "noindex, nofollow" always;
    add_header Cache-Control "no-store" always;
    # The redirect carries a single-use ?code=... in the query string;
    # keep it out of the access log.
    access_log off;
}
```

It is declared **before** the auth-gated `location /` so the exact
match wins and the page is reachable without a Google session.
The landing page lives at `/var/www/penge-eb/index.html`.
Access logging is disabled for this location and a `no-store` cache
header is sent, which reduces how often the `code` in the query string
is persisted on the server side. These are mitigations, not
guarantees: `no-store` is an advisory caching directive and does not
affect logging, and the full callback URL should still be treated as
sensitive — browser history, upstream proxies, and the bank's own logs
may record it. The `code` is single-use and short-lived, so the
practical exposure is small, but do not paste the URL into shared
tools.

## In-app consent flow (Penge UI)

The same dance is available from the **Connections** page in the Penge
UI (ADR-0040). It removes the need to run a CLI on the workstation and,
crucially, **persists the EB session** so re-syncs do not require fresh
SCA until the consent expires (~180 days).

Flow on the page:

1. **Start a consent** — pick the bank and the person the accounts
   belong to. Penge returns the bank's `consent_url`, the `state`, and
   the `valid_until` date.
2. Open the consent URL, approve at the bank, and copy the `code` (and
   `state`) shown on the un-gated `/eb/callback` page.
3. **Authorize** — paste the `code` (and `state`). Penge exchanges it
   for a session and stores it in the `bank_connection` table.
4. **Sync now** — pull transactions and balances into Postgres. Re-syncs
   reuse the stored session; no new consent is needed until it expires.

Every failed link/authorize/sync records a sanitised `last_error`
(step, status code, EB error code, message, timestamp) that is shown
inline on the connection card — so a `422 ALREADY_AUTHORIZED` is never
silent.

### Will every import require consent?

No. Consent (SCA) is required only the first time and again when the
stored session expires or is revoked. Normal re-syncs reuse the
persisted session id.

## Enabling the feature on the NAS

The connections surface is **feature-gated**. The Enable Banking RSA
private key signs every request, so it must live where the API runs.
The read-only NAS API ships **without** the key, so the endpoints return
`503` and the UI shows a "disabled in this deployment" note until the
key is mounted.

To enable on the NAS:

1. Mount the EB private key into the `penge-api` container as a podman
   secret (do **not** bake it into the image):

   ```bash
   podman secret create penge-eb-key 09a4a71a-....pem
   ```

   and reference it from the `penge-api.container` quadlet:

   ```ini
   Secret=penge-eb-key,type=mount,target=/run/secrets/penge-eb-key,mode=0400
   ```

2. Set the connection environment on the API container:

   ```ini
   Environment=ENABLEBANKING_APPLICATION_ID=09a4a71a-1646-41e7-97b1-b79eea6e9d8a
   Environment=ENABLEBANKING_KEY_PATH=/run/secrets/penge-eb-key
   Environment=PENGE_EB_REDIRECT_URL=https://penge.eigmueller.de/eb/callback
   ```

3. The API also needs a **write** database URL (the connections surface
   writes accounts, transactions, and snapshots), not the read-only
   role used for the analytics marts.

4. Restart the container (`systemctl --user restart penge-api`). The
   Connections page should now list the available banks instead of the
   disabled note.

To keep the public instance off regardless of key presence, set
`PENGE_CONNECTIONS_ENABLED=false`.
