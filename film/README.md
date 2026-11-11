# photo-to-part — 60-second showcase

Hyperrizz / HyperFrames **0.9.34**. A graphite-and-amber precision-workbench treatment: tactile photographs, clamp-corner reveals, original Part studio crops, large kinetic captions and an original electronic instrumental. **No voiceover.**

## Outputs

- **Committed landscape master:** `delivery/photo-to-part-1080p.mp4` — 1920×1080, 10,071,379 bytes.
- **Committed square master:** `delivery/photo-to-part-square.mp4` — 1080×1080, 8,029,993 bytes.
- These verified masters are available immediately after fetching `video/showcase`; rendering is optional. Remote-host handoff: `HANDOFF.md`.

Regenerating writes:

- `out/photo-to-part-1080p.mp4` — 1920×1080 / 30fps, 60 seconds, H.264 + AAC.
- `out/photo-to-part-square.mp4` — separately composed 1080×1080 / 30fps square cut.
- `previews/photo-to-part-720p.mp4` and `previews/photo-to-part-square-720p.mp4` — compact review copies.
- `previews/contact-sheet.jpg` and `contact-sheet-square.jpg` — scene contact sheets.
- `captions/showcase.srt` — exact timed on-screen copy, optional accessibility sidecar.

## Install, preview and render

Requirements: Node.js 22+, Python 3, FFmpeg/ffprobe with libx264/AAC/loudnorm, and Chromium. Fonts, photos, screenshots and finished music are bundled; render does not fetch media or need an account/API key.

```bash
cd film
npm ci
npm run preview
npm run render
npm run render:square
```

HyperFrames can provision Chromium. To use an existing browser, set `PRODUCER_HEADLESS_SHELL_PATH` for rendering or `CHROME_BIN` for QA. The render script uses two workers, low priority/two-core affinity on Linux, bounded FFmpeg threads, project/shared locks and candidate files. Final exports are promoted only after full decode, audio, frame-count, duration and size verification. Each is budgeted below 49 MB.

`node scripts/build.mjs --square` builds the square composition for Studio. `npm run build` restores landscape. Square is laid out independently, not cropped from the widescreen MP4.

## Exact edit

| Time | Content |
|---|---|
| 00:00–00:05 | Gear photo push-in; “Snap a photo. Get a printable part.” |
| 00:05–00:12 | Original banner crop, “photo-to-part, a Hermes plugin”, photo attachment and the requested replacement prompt |
| 00:12–00:27 | Gear Ready pane, parametric-template / IoU 0.94 / under-5-minutes captions |
| 00:27–00:40 | Strap hinge photo, then the specified Ready screenshot; exact 70 mm caption |
| 00:40–00:50 | Four 2.5-second trust beats using supplied render views and pane crops |
| 00:50–00:56 | “248 tests · 28/28 sealed evals · CI green” |
| 00:56–01:00 | Exact version, repository and @NousResearch end card |

The chat bubble is the brief's explicitly requested editorial prompt example, labelled as such. Screenshots are original pixels; camera cropping/scaling does not fabricate interaction. All numeric overlays come from the approved kit. Incidental numbers, warnings and trust states inside original screenshot pixels remain their source content. The gear's guide-only qualification and the hinge examples' original trust state are preserved. The weak-match shot uses the actual `untrusted` field in `strap-hinge-pane-ready-2.png`.

This is a showcase made from supplied screenshots and approved claims, not a recording of a live run. The source photos and app screenshots are not placeholders. No other logos or brands were added.

## Provenance and licenses

Brief: `mojomast/hermes-photo-to-part`, branch `video-kit`, pinned to **`be886d0f57f803e4ef9019db03af7014f67c2b4f`**. Exact brief retained in `assets/BRIEF.md`; source URLs, SHA-256 and dimensions in `assets/provenance.json`. The release shown is **v0.1.22**.

- Supplied screenshots/banner/render views: approved video-kit assets, repository MIT; license in `assets/licenses/`.
- Gear photograph: Paolo Neo, CC0, Wikimedia Commons `Zahnrad.jpg`.
- Strap hinge photograph: The Metropolitan Museum of Art, CC0, Wikimedia Commons `Strap_Hinge_MET_cdi55-61-56.jpg`.
- Barlow Condensed, Manrope and DM Mono: SIL Open Font License 1.1, original license files bundled.
- **PRECISION**, original 120 BPM electronic score and effects: **CC0-1.0**. No sampled commercial music or voice. Source is `scripts/music.py`, deterministic seed `12224828`; license in `assets/audio/LICENSE.txt`. Regeneration requires Python + NumPy + FFmpeg, but normal rendering uses the bundled WAV.

Music phrase phase begins at 0 seconds. Accents hit all major scene boundaries and internal trust/gear cuts. The score resolves at 56 seconds and releases before 60. Its PCM target is −14 LUFS, with headroom reserved for AAC; final encoded measurements are recorded separately in REVIEW.md.

## Editing and QA

One source file per scene in `scenes/`; shared compositor/typography in `shared/`. `copy.json` is the approved copy ledger; scene modules contain its intentional line breaks and positions. Palette and timing are JSON. Build output and caches are disposable.

```bash
python3 scripts/audit.py
python3 scripts/captions.py
npm run build
npm run lint
npm run check
npm run stills
npm run qa
```

The audit checks scene boundaries, approved text, the seven allowed images and original asset hashes. Seek QA compares reverse and shuffled frames exactly, includes internal cut boundaries, tests motion/effect sensitivity and checks canvas text bounds. Framework DOM analysis cannot certify canvas typography; actual still/encoded review is documented in REVIEW.md.

The files are ready for the user's X submission workflow. The completed film is delivered on `video/showcase`, based on the pinned `video-kit` commit, with all additions under `film/`. `delivery/X-POST.txt` contains a prepared caption tagging @NousResearch. Posting to X is handled by the project owner.
