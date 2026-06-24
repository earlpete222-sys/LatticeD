# LatticeD from your phone

LatticeD runs on your home computer. Your phone connects to it as a client over your private network. The compute stays on your hardware; the phone is just the window.

## Architecture

```
[ Phone (browser/PWA) ]  --Tailscale (private)-->  [ Home PC running LatticeD + Ollama ]
```

Your phone never talks to the public internet to reach LatticeD, and LatticeD is never exposed to the public internet.

## One-time home machine setup

1. **Bind LatticeD to all network interfaces** so phones on your private network can reach it. From the directory where you run LatticeD:

   PowerShell:
   ```powershell
   $env:LATTICED_HOST = "0.0.0.0"
   python latticed/latticed.py
   ```
   Bash:
   ```bash
   LATTICED_HOST=0.0.0.0 python latticed/latticed.py
   ```

2. **Set a real `LATTICED_SECRET`** before doing step 1. The default `local_dev_secret_123` is intentionally public — anyone on your private network could call the API with it.
   ```powershell
   $env:LATTICED_SECRET = "<paste a 32+ character random string here>"
   ```

3. **Install Tailscale** on the home machine: <https://tailscale.com/download>. Sign in. Your machine now has a stable `100.x.x.x` IP that's only reachable from devices in your tailnet.

## One-time phone setup

1. Install the **Tailscale** app on your phone (iOS App Store or Google Play). Sign in with the same account. Confirm the home machine shows up in the device list.

2. In your phone's browser, open `http://<home-machine-tailscale-ip>:8000`. You should see the LatticeD login screen.

3. Pair the device (no need to type the long shared secret):
   - On the **home machine** browser: Settings → "Pair new device" → copy the 6-digit code.
   - On the **phone**: tap "Pair This Device" on the login screen → enter the code → name the device (e.g. "Earl's iPhone").
   - The phone receives a per-device token, stored in browser storage. You won't need to re-enter anything on future visits.

4. **Add to Home Screen** for a near-native app feel:
   - **iOS Safari**: Share → Add to Home Screen
   - **Android Chrome**: ⋮ menu → Install app / Add to Home Screen

   The PWA launches fullscreen with the LatticeD icon, no browser chrome.

## Revoking a paired device

If a phone is lost or you no longer want it connected: on the home machine, Settings → Paired Devices → Revoke. The phone's stored token stops working immediately and the user is forced back through pairing.

## Security model

- LatticeD is **never** exposed to the public internet. All traffic is over Tailscale's WireGuard mesh.
- The `LATTICED_SECRET` lives only on the home machine; phones use per-device tokens that you can revoke individually.
- Pairing codes are valid for 10 minutes and single-use.
- All data — beliefs, memories, cache, conversations — stays on your home machine. Nothing leaves your tailnet.

## Trying the v2 engine (beta) on your phone

Once paired, the chat header has an engine selector:

- **engine v1** — the default. Legacy 13-node pipeline.
- **engine v2 (beta)** — the typed pipeline (kstore + perception + strategies + reviewer). Doesn't fabricate dates, doesn't say "we talked", doesn't invent details — these are structurally prevented, not patched after the fact.

Toggle is per-device and persists across sessions. Switch any time without losing thread history. v2 stores its own knowledge in `v2_kstore.db`; the first time you use v2 it imports what v1 knew about you.

If a v2 reply ever looks too short or off, tap **Settings → v2 Engine → Run reflection now** to push recent turns through the distiller and grow the knowledge store.

## What does NOT work yet

- Public internet exposure (intentionally — use Tailscale).
- Multi-user isolation (single-user only; tokens authenticate as the same user).
- Offline inference on the phone itself (phone is a client, not a runtime).
- Push notifications (planned for a later sprint).
