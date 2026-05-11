# Sync setup — connecting knowlet to Google Drive

> **Status**: ADR-0027 Slice 5.A–5.G + 2026-05-11 dogfood-pass closure.
> **Reference**: [ADR-0027](./decisions/0027-sync-via-drive-api.md).

knowlet ships sync as an **opt-in** feature. Single-device users don't
need it; nothing on disk changes until you complete the connect flow.

## The fast path (recommended)

knowlet bundles an OAuth client out of the box. Per Google's Desktop
OAuth guidance + RFC 8252, the `client_secret` for a native installed
app is **not** a real secret — it can ship with the binary, and the
worst-case abuse is brand spoofing / quota theft, not data exposure.

So the normal connect flow is:

1. Open **Settings → Drive sync** in the web UI.
2. Click **Connect to Drive**.
3. Your browser opens Google's consent screen. Approve.
4. Window flips to **Connected as you@example.com** within ~2 s.

That's it. The first connect triggers a one-time bootstrap:

- Any pre-existing notes on disk get queued for first-push.
- Any pre-existing attachments (`_attachments/*`) get queued too.
- The background drainer drains them over the next few minutes.

You can watch progress via the sync chip in the header (it surfaces a
running count of "N to push" until everything is up).

### CLI parity

```bash
knowlet sync connect           # equivalent to the Connect button
knowlet sync status            # check current state
knowlet sync disconnect        # remove local tokens (Drive grant
                               # stays active until revoked at
                               # https://myaccount.google.com/permissions)
knowlet sync push              # one-shot manual push (the background
                               # drainer normally does this for you)
knowlet sync pull              # one-shot manual pull
knowlet sync resolve           # interactive conflict resolver
```

## Advanced: bring your own OAuth client

If you want to scope the OAuth client to your own Google Cloud project
(quota isolation, full control of who can revoke), you can point
knowlet at your own `client_secret.json`. This is opt-in; most users
shouldn't need it.

### When to do this

- You're hitting Drive API quota limits on the shared client (very
  unlikely for personal use — Drive's per-user quota is 1000
  requests/100s, far above what knowlet's polling needs).
- You're auditing knowlet for an org and want every byte of OAuth
  to terminate in a project you control.
- You're hacking on knowlet itself and want to test scope changes
  without re-using the embedded client.

### Setup

1. Create a Google Cloud project at <https://console.cloud.google.com/projectcreate>.
2. Enable the Drive API:
   <https://console.cloud.google.com/apis/library/drive.googleapis.com>
   → **Enable**.
3. Configure the OAuth consent screen at
   <https://console.cloud.google.com/apis/credentials/consent>:
   - **User type**: External
   - **App name**: anything
   - **Test users**: add your own Gmail (so Google doesn't flag the
     unverified-app warning during connect)
4. Create the OAuth client:
   <https://console.cloud.google.com/apis/credentials> → **+ Create
   credentials** → **OAuth client ID** → **Desktop app** → **Download
   JSON**. Save it somewhere safe (it's tied to your Cloud project).
5. Tell knowlet to use it:

   ```bash
   knowlet config set sync.client_secrets_path \
     ~/.config/knowlet/google_oauth_client.json
   knowlet sync disconnect   # clear any previous embedded-client tokens
   knowlet sync connect
   ```

Override priority (first match wins):

1. `KNOWLET_OAUTH_CLIENT_JSON` env var (full JSON inline) — used by
   release builds to inject a production client.
2. `sync.client_secrets_path` config — points at a file on disk.
3. Embedded fallback — what the fast path above uses.

## Where files actually live on Drive

knowlet uses Google's **app-data folder** scope (`drive.appdata`), a
hidden per-app storage area inside your Drive:

- Your synced notes + attachments are **invisible** in Drive web UI,
  Drive search, and the Drive desktop client. You won't see them
  alongside your real Drive files.
- The Drive desktop client **does not mirror them** to your local
  `~/Google Drive/` folder — no duplicate copies, no second
  authority that could overwrite knowlet's.
- They still count against your Drive storage quota.
- Google's built-in version history (≈30 days) still applies and is
  reachable via API for recovery.
- knowlet can only see files knowlet itself created — even with the
  appdata scope, your real Drive content is invisible to it.

This was an explicit choice over `drive.file` (where files are visible
in Drive UI but the desktop client mirrors them, creating "two
equally authoritative copies" — exactly the failure mode
[ADR-0027](./decisions/0027-sync-via-drive-api.md) §"权威" rules out).

## Where the tokens live

- Default: `<vault>/.knowlet/sync_credentials.json` (file mode 0600).
- Override: `knowlet config set sync.token_path /path/to/tokens.json`.
- Disconnect clears the local tokens; revoke at
  <https://myaccount.google.com/permissions> to also kill the
  server-side grant.

## What gets synced

| Entity | First-push | Updates | Delete | Conflict |
|---|---|---|---|---|
| Notes (`*.md`) | ✅ on save / on first connect | ✅ via revisionId OCC | ✅ trash → Drive trash; purge → Drive hard delete | ✅ inline merge editor |
| Attachments (`_attachments/*`) | ✅ on paste / on first connect | N/A (immutable) | ⚠️ not auto-cleaned on local delete (see "known gaps") |  N/A (immutable) |
| Heartbeat (`.knowlet/heartbeat-*.json`) | ✅ periodic | ✅ periodic | — | — |

## Known gaps (2026-05-11)

These are tracked in [ADR-0027 § Status (2026-05-11)](./decisions/0027-sync-via-drive-api.md):

- **Attachment delete-sync**: deleting a local paste does not yet
  remove the Drive copy. Orphan attachments accumulate.
- **Multi-device scenario validation**: heartbeat + Auto→Strict
  auto-promotion are implemented but only single-device dogfood-tested.
- **Conflict UI polish**: merge editor lands the basics; some edge
  cases (e.g. "merged but not auto-pushed") still need cleanup.

## Troubleshooting

**Stuck at "Opening browser…" forever** — you closed the Google
consent tab before approving. Click **Cancel** in the dialog (or wait
~5 min for the auto-timeout); the Connect button will return.

**Chip says "N to push" and the count doesn't drop** — make sure the
background drainer is alive (it starts with the web server). The
drainer ticks every 5 s; the count should drain within ~1 min for a
small vault. If it stays stuck:

```bash
curl -s -X POST http://127.0.0.1:8000/api/sync/drain-now
curl -s http://127.0.0.1:8000/api/sync/push-errors | jq
```

The push-errors endpoint surfaces transient failures (network blips,
Drive 5xx, etc.). The chip lights up red when this list is non-empty.

**"Drive sync requires the optional `sync` extra"** — install with
`uv pip install -e ".[sync]"` from the knowlet repo. Single-device
users can skip this entirely.

**Browser shows "App is not verified"** — for the embedded client
this means knowlet's OAuth consent screen hasn't been through Google's
verification flow (that only matters for shipped consumer apps with
>100 users). Click **Advanced → Go to knowlet (unsafe)**. For
BYO-client setups, add yourself as a test user in step 3.

**OAuth flow times out** — your firewall blocks the loopback callback
port. Use a specific port:

```bash
# CLI path
knowlet sync connect --port 8765
```

Then add `http://localhost:8765` to the authorized redirect URIs in
the OAuth client settings (BYO-client only — the embedded client
already accepts arbitrary loopback ports).
