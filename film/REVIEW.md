# photo-to-part production review

Complete: landscape and square masters, compact previews, editable source and private review delivery.

## Contract and evidence

Exactly 60 seconds / 1,800 frames at 30fps. Landscape 1920×1080 and independently laid-out 1080×1080 square. Hyperrizz / HyperFrames 0.9.34, checked 2026-11-11. No voiceover.

The supplied `video-kit/README.md` was read first. Source pinned at `be886d0f57f803e4ef9019db03af7014f67c2b4f`. Original seven images and all font/license bytes are hashed. All captions match approved kit text; scene boundaries match the exact seven-scene table. No app test or live execution is claimed; figures are supplied/approved values, not newly measured performance.

Real pane content is retained, including the gear's guide-only status. The weak-match shot shows the actual untrusted badge from the second hinge capture. The requested prompt bubble is labelled PROMPT EXAMPLE. No invented cursor, fake progress event, extra product statistic, added logo or generated product image is used.

## Preflight and visual review

- Opening, gear evidence and end card reviewed full-size; both complete scene contact sheets inspected.
- Clamped photo/reveal motif, real screenshot pans, changing evidence composition, large caption match cuts, locked proof values and quiet four-second end card.
- Improved close-up framing to avoid excessive magnification and preserve source warning context. Removed duplicated banner text behind the end card by using the original banner's render crop.
- Both compositions: **45 reverse and 45 shuffled exact-pixel matches**. Motion and effect controls change pixels.
- Canvas typography: **737 landscape / 661 square** bounds checks, zero violations. This is separate from HyperFrames DOM checks.
- Landscape build/lint and strict framework runtime/layout/craft/audio check passed with zero errors/warnings.
- Original 120 BPM score, downbeat zero, edit-aligned hits, no samples/VO. PCM measured **−14.00 LUFS / −2.14 dBTP**.

## Encoded verification

All four exports passed full audio/video decode, dimensions, 30fps and **1,800 decoded frames / 60.000 seconds of picture**. H.264/yuv420p video, AAC stereo audio and faststart. The compact preview containers include 0.010 seconds of AAC padding; the delivered masters have the exact requested picture duration.

| File | Dimensions | Bytes | Encoded LUFS | True peak |
|---|---|---:|---:|---:|
| `delivery/photo-to-part-1080p.mp4` | 1920×1080 | 10,071,379 | −14.06 | −1.12 dBTP |
| `delivery/photo-to-part-square.mp4` | 1080×1080 | 8,029,993 | −14.06 | −1.12 dBTP |
| `previews/photo-to-part-720p.mp4` | 1280×720 | 3,632,019 | −14.09 | −1.17 dBTP |
| `previews/photo-to-part-square-720p.mp4` | 720×720 | 3,047,745 | −14.09 | −1.17 dBTP |

Actual encoded frames/cut samples checked in both formats, including internal gear/hinge/trust cuts at −1/0/+1 frame. All twelve expected motion intervals change pixels; the end card holds stable (landscape 57–59s mean pixel-channel difference 0.000129; square 0).

Full landscape preview playback completed unmuted: **1,800 frames, zero dropped frames, zero waiting events and no page/player errors**. Seek to 45 seconds passed. This is programmatic verification; subjective listening was not performed. Square received full decode and encoded frame review rather than a separate realtime playback run.

## Source reproduction and delivery

An isolated source-only copy installed with `npm ci` and rebuilt both formats without pre-existing dependencies/cache. Both fingerprints exactly match rendered output:

- Landscape: `a895c53fb336e914a87340c27be4a7548ee929e233791481a7a5a18a5e792ed7`
- Square: `13c9a14ebd5f98a08ee922d32ab3510e18a36ef51eea71a8f683e01f8634ee6e`

Machine-readable checksums and measured results: `delivery/verification.json`. Editable source archive excludes dependencies, caches, rendered intermediates and private review state. A private review server serves only copied delivery artifacts; HTTP sizes and byte-range seeking were verified. Its address remains outside the source archive.

No missing media or placeholder slots remain. At the user's subsequent request, the completed project and byte-identical master copies are packaged on `video/showcase` for a remote-host agent. Changes are confined to `film/`. The optional `delivery/X-POST.txt` supplies an approved-claims caption for the user's post; no X posting was performed.
