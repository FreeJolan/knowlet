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
- Digest Source configs and Raw Info inbox JSON files are queued too.
- The background drainer drains them over the next few minutes.

You can watch progress via the sync chip in the header (it surfaces a
running count of "N to push" until everything is up).

## New device: restore an existing remote Vault

Vault identity is the stable `.knowlet/vault.json` id, not the folder
name. Creating a local Vault with the same display name creates a new
sync identity; it does **not** bind to the old remote data.

On the desktop app's **Manage Vaults** screen, use **Restore from
Drive** instead:

1. Connect the same Google Drive account.
2. Choose one of the remote Vaults listed from Drive appData.
3. Pick an empty local folder location and confirm **Restore and Open**.
4. Knowlet writes the selected remote `vault_id` locally, copies the
   Drive credentials into that Vault, pulls the scoped appData files,
   then opens the restored Vault.

New builds publish a small account-level appData registry so another
device can list remote Vaults. Older synced Vaults are still discoverable
by scanning existing scoped names such as `vault-<id>__note__...`.

## Sync modes

After Drive is connected, knowlet defaults to **Realtime multi-device**.
The older Auto / Strict / Quiet setting no longer exists.

| Mode | Behavior | Best for |
|---|---|---|
| Realtime multi-device | On app open and long foreground resumes, knowlet runs a lightweight Drive Changes freshness probe. The probe itself does not block. If it finds remote updates, knowlet shows a blocking sync gate and runs preflight/pull/conflict handling before normal work continues. | Multiple devices used in rotation |
| Data backup only | No freshness gate. Local reads/writes stay local-first; the drainer uploads changes in the background. | One main device plus Drive backup |

Legacy stored values migrate automatically: `auto` / `strict` become
`realtime`; `lax` becomes `backup`.

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
knowlet sync vaults --json     # list remote Vaults in this Drive account
knowlet sync restore-vault \
  --remote-vault-id <id> \
  --to ~/Documents/MyVault     # bind + restore a remote Vault locally
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
| Attachments (`_attachments/*`) | ✅ on paste / on first connect | N/A (immutable) | ✅ missing local file → Drive hard delete |  N/A (immutable) |
| Digest Source configs (`.knowlet/digest/sources/*.json`) | ✅ on create / first connect | ✅ appData JSON revision sync | ✅ delete → Drive hard delete | ⚠️ no merge UI; latest clean remote revision auto-pulls |
| Raw Info inbox (`.knowlet/digest/items/*.json`) | ✅ on pull / first connect | ✅ appData JSON revision sync | N/A (items are status-marked, not unlinked) | ⚠️ no merge UI; latest clean remote revision auto-pulls |
| Heartbeat (`.knowlet/heartbeat-*.json`) | ✅ periodic | ✅ periodic | — | — |

### Digest auto-pull in multi-device mode

Digest pulls run locally, so realtime sync must happen before the daily
auto-pull decision. The current mitigation is:

- Digest sources and Raw Info items sync through Drive appData.
- Realtime freshness gate runs before the user is unblocked after a stale
  foreground/open.
- `item_key` and source success state dedupe after remote Raw Info arrives.

This is not a global atomic lease. Two devices that start the same source
pull at exactly the same time before seeing each other's appData writes may
still race; that is the remaining edge case to revisit if dogfood shows real
duplicates.

## Known gaps (2026-05-31)

These are tracked in [ADR-0027 § Status (2026-05-11)](./decisions/0027-sync-via-drive-api.md):

- **Digest global lease**:source/item sync lowers duplicate pulls, but there is
  no Drive-side atomic lease yet.
- **Non-note JSON conflict UI**:Digest Source / Raw Info files auto-pull clean
  remote revisions; if both devices edit the same JSON before syncing, we do
  not yet have a user-facing merge UI for those files.
- **Conflict UI polish**:merge editor lands the basics; some edge cases
  (e.g. "merged but not auto-pushed") still need cleanup.

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
