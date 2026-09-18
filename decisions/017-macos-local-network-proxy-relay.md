# 017 — Reaching a LAN Proxy from Python Under macOS Local Network Privacy

**Date:** 2026-09-18
**Status:** Accepted

## Context

Testing whether a SOCKS5 proxy on the LAN (`192.168.1.99:25344`) clears YouTube's "Sign in to
confirm you're not a bot" block required driving that proxy from Python. It did not work: both
diagnostic scripts in the repo root failed on every attempt, while `curl` succeeded against the
same proxy from the same shell.

```
curl --socks5-hostname 192.168.1.99:25344 https://www.youtube.com   HTTP 200
fetch_via_httpx.py                                                  ConnectError('[Errno 65] No route to host') x5
```

The scripts attributed this to the proxy's own route to YouTube, and carried an IPv4-forcing
workaround (`source_address` / `local_address = "0.0.0.0"`) on that theory. Both were wrong. Three
independent problems were tangled together, and separating them is the substance of this decision.

**1. macOS "Local Network" privacy blocked the interpreter, not the proxy.** Probing every port on
the proxy host from the project's venv Python failed instantly, while the default gateway and the
public internet stayed reachable:

| from | to | result |
|---|---|---|
| `.venv/bin/python` | `192.168.1.99:25344` | `OSError(65, 'No route to host')` |
| `.venv/bin/python` | `192.168.1.99:22` | `OSError(65, 'No route to host')` |
| `.venv/bin/python` | `192.168.1.1:53` (gateway) | OK |
| `.venv/bin/python` | `1.1.1.1:443` | OK |
| `/usr/bin/python3` | `192.168.1.99:25344` | OK |
| `/usr/bin/nc` | `192.168.1.99:25344` | OK |

Routing and ARP were fine (`route get` resolved, `LLINFO` present), so this was not a network
fault. macOS Sequoia and later gate LAN connections behind the Local Network permission, and that
permission is held **per binary identity** — it is not inherited from the terminal that launched
the process. Apple platform binaries held it; Homebrew's ad-hoc-signed interpreters did not:

```
/usr/bin/curl                    Identifier=com.apple.curl              Platform identifier=26
/usr/bin/python3                 Identifier=com.apple.dt.xcode_select…  Platform identifier=26
/opt/homebrew/…/python3.14       Identifier=python3-5555…               flags=0x2(adhoc)
/opt/homebrew/bin/node           Identifier=node-5555…                  flags=0x2(adhoc)
```

This is *not* a signed-versus-unsigned rule — Homebrew's Python is signed, just ad-hoc, with no
Team ID. It also explains the earlier PyCharm failure: granting PyCharm does not help, because the
interpreter it spawns is judged on its own identity.

**2. `socks5://` vs `socks5h://` is a real but separate issue.** Local DNS returns YouTube's IPv6
addresses ahead of its IPv4 ones, and the proxy's exit network has no IPv6 route, so it answers
SOCKS5 reply `0x04`:

```
curl --socks5 …            curl: (97) Can't complete SOCKS5 connection … (4)
curl --socks5 -4 …         HTTP 200
curl --socks5-hostname …   HTTP 200
```

`socks5h://` hands the proxy the hostname and never resolves locally, so the IPv4-forcing
workaround the scripts carried was treating a symptom that `socks5h://` removes outright.

**3. `requests` cannot do SOCKS at all here.** PySocks is not installed, so
`requests.get(..., proxies={"https": "socks5h://…"})` raises
`InvalidSchema: Missing dependencies for SOCKS support`. `yt-dlp` is unaffected — it implements
SOCKS itself in `yt_dlp/socks.py` — and `httpx` is fine via the already-installed `socksio`.

### The permission turned out to be grantable

An initial version of this ADR concluded that an ad-hoc-signed interpreter could not hold the
grant, and made the loopback relay the primary fix. **That conclusion was wrong**, and is corrected
here. Measured, in order:

| attempt | result |
|---|---|
| re-sign a copy of the interpreter ad-hoc with a stable identifier | still `EHOSTUNREACH` |
| wrap it in an ad-hoc-signed `.app`, run the inner binary directly from the shell | still `EHOSTUNREACH` |
| wrap it in an ad-hoc-signed `.app`, launch via LaunchServices (`open -a`) | **LAN access granted** |

After that launch the grant was broad and persistent: the bare `/opt/homebrew/bin/python3.14`, the
venv's `python`, and a separately re-signed copy all reached the LAN, stably across repeated runs,
and `fetch_via_httpx.py` went 5/5 against the proxy with no relay. `node`, which was never
successfully launched that way, stayed blocked — so the grant is per-something, not a blanket
lifting of the gate for the terminal or its children.

Two things remain unresolved and are recorded as such rather than guessed at:

- **What TCC actually keyed the grant on.** It cannot be the code-signing identifier or cdhash,
  since a re-signed copy with a different identifier and hash inherited the access. Confirming it
  means reading `TCC.db`, which needs Full Disk Access this session did not have.
- **Whether a GUI permission prompt appeared and was approved** during the LaunchServices launch.
  If one did, the mechanism is simply "the `.app` wrapper gave macOS something it could prompt
  for", which would make the recipe below a deliberate procedure rather than a lucky side effect.

## Decision

1. **Point the diagnostic scripts straight at the LAN proxy** (`socks5h://192.168.1.99:25344`).
   This is the simple path, it works now, and it needs no background process.
2. **Keep `tools/lan_proxy_relay.py` as the documented fallback.** It listens on `127.0.0.1:1080`
   and forwards to the LAN proxy; loopback is exempt from the gate, so it works for any
   interpreter regardless of identity. It is retained because the grant above is opaque, was not
   obtained deliberately, and may not survive a Homebrew upgrade, a rebuilt venv, or a new machine
   — and because it is the only option that needs no GUI at all.
3. **Run the relay under Apple's platform-signed Python** via a `#!/usr/bin/env /usr/bin/python3`
   shebang. The relay's upstream leg is the one that touches the LAN, so it must be a binary that
   holds the permission. It uses only `asyncio` from the standard library, so Apple's Python
   suffices and no venv is involved.
4. **Give each script a preflight** that probes the proxy port and names the Local Network block
   when it sees `EHOSTUNREACH` to a non-loopback address, pointing at the relay. This is what makes
   Decision 1 safe: if the grant lapses, the next person meets the diagnosis and the workaround
   rather than a bare `ConnectError`.
5. **Introduce a top-level `tools/` directory** for host-environment utilities that are neither
   part of the `extract_memes` package nor root-level diagnostics.
6. **Do not add PySocks to `pyproject.toml`.** The package has no proxy support today and neither
   diagnostic script uses `requests`. Recorded here so that whoever adds proxy support knows
   `requests` needs `requests[socks]` and `yt-dlp` does not.

## Options Considered

- **Grant the permission via System Settings → Privacy & Security → Local Network** — the tidy
  fix, and not ruled out, but it could not be verified from a shell: reading the stored state needs
  Full Disk Access, so whether an entry for the interpreter exists there is unknown.
- **`sudo tccutil reset LocalNetwork`** — rejected as a default remedy: it forces re-prompting but
  discards every other app's decision, a large blast radius for one interpreter.
- **Relay with `/usr/bin/nc`** — rejected (Decision 3): macOS's `nc` has no `-c`/`-e`, so a
  concurrent multi-connection relay would need a shell loop respawning it, which is fragile.
- **Make the loopback relay the default path** — this was the original decision here, and is now
  demoted to a fallback (Decision 2): it imposes a manual start on every reboot for a block that is
  currently lifted.
- **Run a SOCKS client on the host** so the proxy is already on loopback — out of scope; the proxy
  is a fixed piece of the user's network, not something this project provisions.

## Consequences

- On macOS the proxy path now works with no prerequisite, but depends on a grant whose key is not
  understood. The preflight is what keeps that acceptable.
- If the block returns, the recipe that lifted it is: wrap the interpreter in a minimal ad-hoc
  signed `.app` bundle and launch it once with `open -a`. That is recorded above, not automated —
  it touches LaunchServices registration and is not something to run unattended.
- The relay is plaintext TCP on loopback and carries the SOCKS handshake unmodified; it adds no
  authentication and should stay bound to `127.0.0.1`.
- `node` is still blocked from the LAN. This does not affect the pipeline — yt-dlp uses Node only
  to execute YouTube's JS challenges locally, not to make network calls — but it would matter to
  anything that expects Node to reach a LAN service.
- Nothing in `src/extract_memes/` changed; the package still has no proxy support. This ADR covers
  the diagnostics and the host environment only.
- On Linux and in Docker/CI there is no Local Network gate, so none of this applies.
- The question that prompted all this is now answerable and separate: with the proxy reachable,
  `yt-dlp` receives "Sign in to confirm you're not a bot". That is exit-IP reputation, not
  connectivity, and remains open.

## References

- [decisions/006-youtube-video-only-formats-and-download-toolchain.md](006-youtube-video-only-formats-and-download-toolchain.md)
  — the `yt-dlp` / Node.js toolchain these scripts exercise.
- `download_via_proxy.py`, `fetch_via_httpx.py`, `tools/lan_proxy_relay.py`.

## Changelog

- **2026-09-18** — Diagnosed why Python could not reach the LAN SOCKS proxy while `curl` could.
  Established by measurement that the failure was macOS Local Network privacy denying the
  ad-hoc-signed Homebrew interpreter (`EHOSTUNREACH` to every port on the LAN host, while Apple's
  `/usr/bin/python3` and `/usr/bin/nc` succeeded from the same shell), not the proxy's route to
  YouTube as the scripts previously assumed. Added `tools/lan_proxy_relay.py` (loopback → LAN, run
  under `/usr/bin/python3`), removed the `source_address`/`local_address` IPv4-forcing workaround as
  unnecessary under `socks5h`, and added a preflight that reports the Local Network block by name.
  Also recorded that `requests` lacks PySocks in this venv, without adding the dependency.
- **2026-09-18** — Corrected this ADR's central claim. It had concluded that an ad-hoc-signed
  interpreter could not hold the Local Network grant, on the strength of two failed attempts
  (re-signing with a stable identifier; running the inner binary of an `.app` bundle directly).
  Launching that same bundle through LaunchServices did grant it, after which every Homebrew
  Python — the bare interpreter and a differently-signed copy included — reached the LAN stably,
  and `fetch_via_httpx.py` went 5/5 with no relay. Repointed both scripts at the LAN proxy
  directly, demoted the relay from primary fix to documented fallback, and recorded the two things
  still unknown: what TCC keyed the grant on, and whether a GUI prompt was approved during the
  launch. `node` remains blocked.
