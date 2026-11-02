# dramabox.aivora.agency — operator-only runbook (NOT executed by T046)

T046 stages the owner app privately (loopback-only, authenticated). Making it
reachable at the proposed domain is a separate deployment decision with steps
only the operator performs. Nothing below has been run.

## Preconditions (evidence, not optimism)

- The staging drills pass: `bash deployment/staging/drill.sh` (restart
  durability, backup/restore, worker/janitor evidence).
- You accept that the served composition is OFFLINE_MOCK (labeled mock
  envelopes, fake providers, no paid/public effects). A LIVE composition
  requires T045 acceptance + T031 authorization first — the app refuses
  non-offline modes until then.

## Steps (in order, operator-executed)

1. **Decide the exposure.** Recommended: keep the app loopback-only and expose
   it through the host's existing Traefik (Coolify proxy) instead of opening a
   port. The compose file publishes `127.0.0.1:${STAGING_APP_PORT:-8093}`.
2. **DNS.** Create the `dramabox.aivora.agency` record (Cloudflare, same zone
   practice as `mc.aivora.agency`) pointing at the host. Do not proxy through
   Cloudflare until TLS is confirmed end-to-end.
3. **Traefik dynamic config.** Add a router+service for the domain in
   `/data/coolify/proxy/dynamic/` forwarding to `127.0.0.1:8093` (same pattern
   as the SPECTRE waitlist). Use an internal-only middleware chain: no public
   signup; the app's own owner accounts + sessions are the auth layer.
4. **TLS.** Let the existing ACME/resolver setup issue the certificate; verify
   `https://dramabox.aivora.agency/health` returns the health view and the
   certificate chain is valid.
5. **Flip secure cookies.** Restart the app with `MICRODRAMA_COOKIE_SECURE=1`
   (session cookies then require HTTPS — test login again after the flip).
6. **Backup coverage.** Add the staging PostgreSQL volume + object-store
   volume to the nightly restic set (see AIVORA infrastructure rules), or run
   the drill's backup step on a timer.
7. **Observability.** `docker compose logs app worker` for now; OTel wiring
   follows Mission Control practice when the app leaves staging.

## Rollback

Remove the Traefik dynamic file, reload Traefik, delete the DNS record. The
loopback staging stack keeps running independently of the domain.
