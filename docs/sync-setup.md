# Sync setup — connecting knowlet to Google Drive

> **Status**: Phase 2 E Slice 5.A — connect-only.
> **Reference**: [ADR-0027](./decisions/0027-sync-via-drive-api.md).

knowlet ships sync as an **opt-in** feature. Single-device users don't
need it; nothing on disk changes until you complete the connect flow.
This document walks through the one-time setup.

## Why you provide your own OAuth client

knowlet **does not** ship a shared Google OAuth client. Every user
brings their own. Reasons:

- **Trust**: a shared client secret is a single point of compromise.
  The OAuth tokens it would unlock are tied to your Drive account, and
  we don't want maintaining knowlet to imply maintaining a custodial
  fleet of those tokens.
- **No project-side server**: per ADR-0027, the project doesn't run
  any backend. There's nothing for a shared client to talk to —
  knowlet runs locally and uses Google's Drive API directly.
- **Quota isolation**: your Drive API quota lives in your own GCP
  project; you're not contending with other users.

Tradeoff: 5-10 minutes of one-time setup for you. Pay it once.

## Step-by-step

### 1. Create a Google Cloud project

1. Go to <https://console.cloud.google.com/projectcreate>.
2. Name it anything (`knowlet-sync` works). Hit **Create**.

### 2. Enable the Drive API

1. With the project selected, open <https://console.cloud.google.com/apis/library/drive.googleapis.com>.
2. Click **Enable**.

### 3. Configure the OAuth consent screen

1. Open <https://console.cloud.google.com/apis/credentials/consent>.
2. Select **External** (this is for personal Google accounts).
3. Fill in the minimum:
   - **App name**: `knowlet` (or whatever you like — only you see it)
   - **User support email**: your own email
   - **Developer contact**: your own email
4. **Scopes**: skip (we'll declare them in the client itself).
5. **Test users**: add your own Gmail address. Without this you'll
   get a "this app is not verified" warning during connect — clicking
   **Advanced → Go to knowlet (unsafe)** also works, but adding
   yourself as a test user is cleaner.
6. Save.

### 4. Create the OAuth client

1. Open <https://console.cloud.google.com/apis/credentials>.
2. **+ Create credentials** → **OAuth client ID**.
3. **Application type**: **Desktop app**.
4. Name: `knowlet desktop` (anything).
5. Hit **Create**, then **Download JSON**.
6. Save the downloaded file somewhere stable (it's a secret — keep
   it out of git). e.g. `~/.config/knowlet/google_oauth_client.json`.

### 5. Point knowlet at the file + connect

```bash
# Tell knowlet where to find the client secret. Path can be absolute
# or relative to your vault root.
knowlet config set sync.client_secrets_path ~/.config/knowlet/google_oauth_client.json

# Run the OAuth flow. Browser will open; approve consent.
knowlet sync connect

# Verify.
knowlet sync status
# → Connected · you@example.com (Your Name)
```

### 6. Where the tokens live

- Default: `<vault>/.knowlet/sync_credentials.json`. File mode 0600 (you only).
- Override: `knowlet config set sync.token_path /path/to/tokens.json`.
- Disconnect: `knowlet sync disconnect`. **Locally** removes the
  tokens; the OAuth grant on Google's side is still active until you
  visit <https://myaccount.google.com/permissions> and revoke it.

## Where files actually live in your Drive

knowlet uses Google's **app-data folder** scope (`drive.appdata`),
which is a hidden per-app storage area inside your Drive:

- Your synced notes are **invisible** in Drive web UI / search /
  Drive desktop client. You won't see them in your file list.
- The Drive desktop client **doesn't mirror them** to your local
  `~/Google Drive/` folder, so there's no risk of duplicate copies.
- They still count against your Drive storage quota and Google's
  built-in version history (≈30 days) is available via API for
  recovery.
- They live alongside your real Drive content but are sandboxed —
  knowlet can only see files knowlet itself created.

This was an explicit choice over `drive.file` (where files are
visible in Drive UI but the desktop client mirrors them, creating
"two equally authoritative copies" — the exact failure mode
[ADR-0027](./decisions/0027-sync-via-drive-api.md) §"权威" rules
out). Slice 5.C.1 locks this in.

If you're reading this in a future where you want to inspect the
files manually, use Drive's API:

```bash
# Lists every knowlet file you have on Drive (only knowlet can see them).
knowlet sync pull --reset-token  # bootstrap a fresh changes cursor
```

A future `knowlet sync ls` will surface this directly.

## Upgrading from an earlier scope

If you ran `knowlet sync connect` on a build before Slice 5.C.1, your
stored token has `drive.file` scope (notes were uploaded to your Drive
root, visible). Slice 5.C.1 needs `drive.appdata` instead.

Upgrade procedure:

```bash
# 1. Optional but recommended — clean up the old visible files in
#    your Drive UI. Trash any 01KR... .md files knowlet created.
# 2. Disconnect and reconnect to switch scopes.
knowlet sync disconnect
knowlet sync connect

# 3. Re-push your notes; they'll now land in the hidden appdata folder.
knowlet sync push
```

`knowlet sync status` warns you inline if the stored token's scopes
are stale. Push / pull / resolve commands refuse to run until you
reconnect.

## What this does NOT do (yet)

Slice 5.A is **connect-only**. After `knowlet sync connect` succeeds,
nothing else changes:

- Saving notes still goes through the local-only path.
- No data is written to Drive yet.
- Disconnect leaves your vault untouched (it was never uploaded).

The actual sync write/read flow ships in Slices 5.B–5.G per
[ADR-0027 §8](./decisions/0027-sync-via-drive-api.md). The connect
step exists separately so we can verify your OAuth setup works
**before** any data flows over the wire — and so we can ship the
foundation without committing to a sequence yet.

## Troubleshooting

**"sync.client_secrets_path is empty"** — Step 5 wasn't run, or the
config path doesn't match where you saved the JSON.

**"Drive sync requires the optional `sync` extra"** — install with
`uv pip install -e ".[sync]"` from the knowlet repo. Single-device
users can skip this entire section.

**Browser shows "App is not verified"** — you skipped step 3.5. Go
back to the consent screen and add yourself as a test user, OR click
through **Advanced → Go to knowlet (unsafe)**. This is normal for
unpublished apps; Google's verification flow is for shipped consumer
apps with > 100 users, not personal tools.

**OAuth flow times out** — your firewall blocks the loopback callback.
Use `knowlet sync connect --port 8765` (or any free port your
firewall lets through) and add `http://localhost:8765` to the
authorized redirect URIs in the OAuth client settings.
