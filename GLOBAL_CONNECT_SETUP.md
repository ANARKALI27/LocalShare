# Setting up Global Device ID Connect

This is a one-time setup, on your own free Google/Firebase account —
LocalShare cannot create this for you, and there is no way to make
Device-ID-only connections work over the internet without it (see the
"why this exists" note at the bottom if you're curious).

You do NOT need this for:
- Sharing on your local network (works with no setup at all)
- "Global" internet sharing itself (the Cloudflare tunnel already
  works with no account) — you only need this if you specifically
  want people to connect using just your Device ID, instead of you
  sending them the full address/QR code each time.

## Steps

1. Go to https://console.firebase.google.com and sign in with any
   Google account (free).
2. Click "Add project," give it any name (e.g. "my-localshare"), and
   finish the creation wizard. You can disable Google Analytics for
   this project — it isn't used.
3. In the left sidebar, go to **Build → Realtime Database**.
4. Click "Create Database." Choose any region. Start in **locked
   mode** (the default) — you'll replace the rules in the next step,
   don't leave it in test/fully-open mode.
5. Once created, note the database URL shown at the top of the page —
   it looks like `https://your-project-default-rtdb.firebaseio.com`
   or `https://your-project-default-rtdb.<region>.firebasedatabase.app`.
   This is what you'll paste into LocalShare.
6. Go to the **Rules** tab (next to Data, within Realtime Database)
   and replace the contents with:

   ```json
   {
     "rules": {
       "devices": {
         "$device_code": {
           ".read": true,
           ".write": "!data.exists() || data.child('write_token').val() === newData.child('write_token').val()"
         }
       }
     }
   }
   ```

   Click "Publish."

That's it. Paste the database URL from step 5 into LocalShare's
**Settings → Device → Connect Globally**.

## What these rules actually do (and don't do)

- **Anyone with your database URL can read the `devices` list.** This
  is required for Device ID lookups to work at all without every
  LocalShare user separately configuring authentication. It means
  someone who already knows a specific Device ID (and your database
  URL) could look up that device's current tunnel address. It does
  NOT mean they can access files — that's still gated by whatever PIN
  protection your Global share already has (Global mode requires a
  PIN automatically; there's no way to turn that off).
- **Only the original device can update its own entry.** Each device
  holds a private write_token (separate from its public Device ID,
  generated locally, never displayed or transmitted except in these
  writes) — an entry can only be overwritten by a write that includes
  the matching token. This prevents someone from squatting a Device ID
  that's already registered, redirecting it to a URL they control, or
  forcing an existing device offline early by writing garbage over its
  entry. Stopping Global sharing marks the entry offline immediately
  this same, token-checked way (a real write, not a delete) rather
  than only relying on the heartbeat timing out — deletes were
  deliberately avoided here, since a plain HTTP DELETE has no request
  body to carry the token in at all, and a rule permissive enough to
  allow token-less deletes would let anyone remove any entry.
- **This does not encrypt the tunnel URL itself in the database**, and
  the free Realtime Database tier has no built-in expiry, so stale
  entries persist until overwritten or manually deleted. Neither of
  these matters much in practice (a tunnel URL alone doesn't grant
  file access without the PIN, and a stale entry just reports as
  offline once its heartbeat lapses — see below) but are worth knowing
  about rather than assuming.

## Online / offline status

Each device sends a fresh heartbeat to its own entry every 30 seconds
while Global sharing is active, and is considered offline if none has
arrived in the last 90 seconds — a couple of missed heartbeats' worth
of slack, not an instant flip. Stopping Global sharing removes the
entry outright; if the app closes unexpectedly instead, the entry
simply ages out via this same timing rather than a device reading as
"online" forever.

## Why this needs any server at all

Connecting with just a Device ID means answering "where is this device
right now" — its address can change (different tunnel URL each time
Global sharing starts), so something has to track the current mapping.
LocalShare already has a free, zero-maintenance way to make a device
reachable from the internet (the Cloudflare Tunnel behind "Global"
sharing) — the only genuinely missing piece is this lookup step, which
is why the design here is a small managed database rather than a
custom relay/signaling server you'd have to rent and maintain
yourself.
