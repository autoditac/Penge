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
