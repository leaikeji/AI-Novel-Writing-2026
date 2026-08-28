# T4-K fixed browser observer

Status: fixed author/operator browser observer for the personal, local,
single-user T4 path. It does not contain a trust root, private key, signer or
validation token. The former SSHSIG/public-root design is retained only as a
non-blocking experimental path; it is not a prerequisite for this observer,
the local operator report or T4-GATE. The author has already accepted the
voice baseline: narrator `onnx.Zhiming`, Shen Chuan `onnx.Junhao`, Lin Wan
`onnx.Xiaoyu`.

The production CLI has no arguments. It reads one canonical request from stdin,
and reads the validation capability only from fixed inherited file descriptor
3. FD 3 must contain exactly one newline-terminated 43–128 character
`[A-Za-z0-9_-]` token. The capability is never accepted from argv, environment,
stdin JSON or URL and is never emitted, hashed or recorded. The browser context
removes any existing case variant and injects exactly one
`X-AI-Novel-TTS-Validation` header into fixed-loopback HTTP(S) requests; external
HTTP(S) requests are blocked without injection.
It always starts the fixed system Edge executable, visits the fixed loopback
QwenPaw workbench route, and captures the four approved viewport/assistant
combinations. Callers cannot supply a URL, selector, browser path, module,
payload, viewport, or observation.

Every capture also contains the exact count-only `layout_observation` fields:
`tracked_visible_region_count`, `nonzero_overlap_pair_count`, and
`horizontal_overflow_px`. The observer measures viewport-clipped rectangles for
the visible chapter editor, chapter player, optional script-review shell and
native assistant root, but never records or reports their coordinates. Overlap
comparison uses a fixed top-level mutually-exclusive pair list: editor/player,
editor/assistant, player/assistant and script-review/assistant. The script-review
shell intentionally overlays central editor/player content, so those two pairs
are excluded. Editor/player overlap is excluded only for the shipped sticky
player structure: the editor and player must have the exact direct-sibling
relationship, the player must be sticky, the shell must be vertically
scrollable, and both the scroll content and actual CodeMirror/textarea surface
must reserve at least the player height plus sticky inset as bottom padding.
Missing padding, a changed relationship, non-sticky positioning, generic
parent/child containment or any assistant overlap fails closed. Horizontal
overflow is the non-negative `documentElement.scrollWidth - innerWidth` pixel
count.

## Runtime

`bootstrap_node_runtime.py verify` checks both fixed repository-external
components:

```text
~/Library/Application Support/AI小说世界2026/controller-runtime/node-v24.19.0-darwin-<arch>/bin/node
~/Library/Application Support/AI小说世界2026/controller-runtime/observer-dependencies-playwright-core-1.62.1/node_modules/playwright-core
```

`bootstrap_node_runtime.py install-runtime` is the only networked mode. It downloads a
fixed archive from the Node.js release service, verifies the official SHA-256,
extracts it without following unsafe archive links, and installs atomically.
The 2026-08-27 AUTH-3 preparation ran this fixed installer and then verified
the resulting receipt. It never installs system or Homebrew Node and never
discovers or accepts a Codex runtime path.

Dependency preparation is deliberately offline. An operator must first place
the exact official npm tarball at this fixed path (the bootstrap has no URL or
path argument):

```text
~/Library/Application Support/AI小说世界2026/controller-runtime/offline-cache/playwright-core-1.62.1.tgz
```

Then run `bootstrap_node_runtime.py prepare-dependencies`. It verifies the
tarball against the exact registry SHA-512 copied into both `runtime-lock.json`
and `pnpm-lock.yaml`, rejects links/devices/duplicate paths/oversized archives,
extracts owner-only files into the fixed `node_modules`, records a canonical
receipt, and atomically publishes the directory. It does not run pnpm, npm,
Corepack, lifecycle scripts, or any browser download. `verify-dependencies`
subsequently checks the fixed path, owner/mode/link/hardlink policy, exact
package name/version, every installed file hash, and the receipt-bound tree
digest. The committed `package.json` and `pnpm-lock.yaml` are themselves
SHA-256-bound by `runtime-lock.json`, so changing either makes verification
fail closed.

`playwright-core` contains no bundled browser and the observer only launches
`/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge`. Offline setup
therefore needs only the two pinned archives prepared in advance; no silent
network fallback is permitted.

The fixed local operator runner uses the exact dedicated executable, not
`node` resolved from `PATH`, and opens its private capability pipe as FD 3:

```text
~/Library/Application Support/AI小说世界2026/controller-runtime/node-v24.19.0-darwin-<arch>/bin/node scripts/tts/controller-node/bin/observe.mjs
```

The observer independently refuses another `process.execPath`, a mismatched
Node receipt/archive identity, repository-local `node_modules`, a changed
Playwright tree, or a dependency that is not exactly `playwright-core@1.62.1`.
Its dependency load uses the fixed absolute package root. The controlling
Python process must also provide a minimal sanitized environment; this module
does not treat ambient `PATH`, `HOME`, `NODE_PATH`, or a caller-supplied module
path as authority.

Available checks are:

```text
bootstrap_node_runtime.py verify                 # runtime + dependency
bootstrap_node_runtime.py verify-runtime
bootstrap_node_runtime.py verify-dependencies
bootstrap_node_runtime.py prepare-dependencies  # fixed offline tarball only
bootstrap_node_runtime.py install-runtime        # explicit networked Node setup
```

No bootstrap or verification command creates files inside this repository.
The current host has verified Node 24.19.0 and the receipt-bound
`playwright-core@1.62.1` tree at the fixed repository-external paths. Runtime
preparation is host-local evidence, not a portable repository claim.

## Browser identity policy

Hard identity gates are the fixed Edge path, exact executable SHA-256 later
matched against the active controller policy allowlist, Team ID
`UBF8T346G9`, Identifier `com.microsoft.edgemac`, non-empty CDHash,
`codesign --verify --deep`, `spctl` acceptance and a Notarized Developer ID
source. The executable digest and complete codesign projection are collected
both before launch and after all observations; any change fails closed.

`codesign --strict` and the host-wide Gatekeeper override mode are recorded
environment facts, not identity trust anchors. On the fixed 2026-08-27 Edge
build, deep verification succeeds while strict verification is affected by
Finder metadata, and the host reports Gatekeeper assessments disabled while
the exact app assessment remains accepted/notarized. Their result texts are
retained only as SHA-256 projections inside the observer report. The canonical
observer-report SHA-256 is propagated into both the probe and signed collector
core, so the controller evidence commits to this identity observation without
persisting screenshots or raw diagnostic text.

## Sources and licenses

- Node.js 24.19.0 archive index and SHA-256 list:
  <https://nodejs.org/download/release/v24.19.0/> and
  <https://nodejs.org/download/release/v24.19.0/SHASUMS256.txt> (checked
  2026-08-27). Node.js core is distributed under the MIT license and its binary
  distribution includes additional third-party notices.
- Playwright BrowserType and Page APIs:
  <https://playwright.dev/docs/api/class-browsertype> and
  <https://playwright.dev/docs/api/class-page> (checked 2026-08-27). The docs
  support `executablePath`, Edge channels, screenshots, and viewport control,
  while warning that non-bundled browser compatibility must be verified.
- `playwright-core@1.62.1` is Apache-2.0, not MIT. It is the sole package
  dependency; no `playwright`, `@playwright/test`, or browser download is used.

## Protocol

stdin is one canonical JSON line with schema
`moss-tts-t4k-browser-observer-request/1.0`. It contains only run/scope hashes
and canonical novel/document UUIDs needed to construct the fixed route. stdout
is one canonical JSON line with schema
`moss-tts-t4k-browser-observer-report/1.2`; screenshots are in-memory PNG bytes
encoded as base64 for the Python host candidate. Console and page-error bodies
are never returned, only bounded counts and SHA-256 projections.
The final browser route must remain on the fixed loopback origin, preserve
exactly the workbench/novel/document query, and be either `/chat` or one
canonical `/chat/<session>` path. The report emits only route kind and
path/query fingerprints, never the final raw URL.

Schema 1.1 also includes one exact `interaction_evidence` object collected by
the fixed recipe and fixed selectors. It observes the chapter player,
CodeMirror 6 or textarea fallback, paragraph context-menu playback,
`Mod+Alt+Enter`, two rapid seeks and final-target settling, play/pause/rate/seek,
an edit-plus-undo round trip with zero TTS write count, and—when a real media
request is available—ETag, `If-None-Match` 304, Range 206, `If-Range` 206 and
unsatisfied Range 416. Evidence contains only booleans, counts, elapsed
milliseconds, fixed status/kind enums and SHA-256 values; it contains no novel
text, URL, identifier, request header or media bytes. The player exposes only
its fixed phase, fixed failure code, current ordinal and a comma-separated
`ready/pending/failed/cancelled` state projection; it exposes no segment ID,
text, URL or media identity. When that projection contains an exact
`ready -> pending` boundary, the observer dispatches the production sentence
seek at the preceding ready ordinal and reports `pending_gap=observed` only
after the real player settles to `blocked/PENDING_GAP` without entering the gap
ordinal. Missing, malformed, changing, timed-out or crossed-gap state remains
`not_observed`; the observer never replaces the Manifest or fabricates a
successful gap observation.

The first 2026-08-27 raw observation predated the accepted baseline Edition.
It proved the four exact layouts, zero actionable overlap/overflow and the
CodeMirror edit/undo round trip, while media-dependent interactions correctly
remained `not_observed`; that historical report was not a PASS.

After the real 56/56-segment Nano baseline was ready, the fixed runtime repeated
the observation against the same hidden-validation chapter. Report
`ce5cf23bee896cd5e02c469aeaf39eba85dda6545adf7ec67702cc4b56c053e2`
observed all four layouts with zero actionable overlap and horizontal overflow,
zero console/page errors, paragraph and cursor seek, latest-wins, semantic
play/pause/rate/seek, CodeMirror edit/undo with zero TTS writes, and the five
fixed media results (200, 304, 206, 206, 416). `pending_gap` remains
`not_observed` because this baseline is fully ready; the observer does not
fabricate a partial-ready state. No screenshot, text, audio or secret from the
run is stored in Git.
