# Remote-host project-agent handoff

Repository: `https://github.com/mojomast/hermes-photo-to-part.git`

Branch: **`video/showcase`**. Base: `video-kit` at `be886d0f57f803e4ef9019db03af7014f67c2b4f`. All changes are additions under `film/`.

## Fetch on your host

In an existing clone:

```bash
git fetch origin video/showcase
git log -1 --oneline origin/video/showcase
git diff --stat be886d0f57f803e4ef9019db03af7014f67c2b4f origin/video/showcase
```

For an isolated review clone:

```bash
git clone --branch video/showcase --single-branch \
  https://github.com/mojomast/hermes-photo-to-part.git photo-to-part-video
cd photo-to-part-video
```

## Ready-to-use files

- `film/delivery/photo-to-part-1080p.mp4` — primary X/hackathon upload, 1920×1080, 60 seconds, 30fps, H.264 + AAC, 10,071,379 bytes.
- `film/delivery/photo-to-part-square.mp4` — 1080×1080 alternate, same duration/frame rate/codecs, 8,029,993 bytes.
- `film/previews/photo-to-part-720p.mp4` and `photo-to-part-square-720p.mp4` — smaller review copies.
- `film/captions/showcase.srt` — timed approved captions.
- `film/delivery/X-POST.txt` — suggested post tagging `@NousResearch`.
- `film/delivery/verification.json` — exact file hashes and measured verification evidence.
- `film/README.md`, `film/REVIEW.md`, `film/STYLE.md` — usage, QA, source/license notes and creative direction.

These files are in GitHub; the remote host needs neither the original workstation nor its private Tailscale server. The masters are ready for review/use without Node, Chromium or a rerender.

To verify the committed media with Python's standard library, from the repository root:

```bash
python3 - <<'PY'
import hashlib, json
from pathlib import Path
root = Path('film')
for item in json.loads((root / 'delivery/verification.json').read_text())['files']:
    p = root / item['file']
    assert p.stat().st_size == item['bytes'], p
    assert hashlib.sha256(p.read_bytes()).hexdigest() == item['sha256'], p
    print('OK', p)
PY
```

## Project context

The video follows the exact seven-scene brief in `video-kit/README.md`: 0–5 hook; 5–12 title/prompt; 12–27 gear; 27–40 hinge; 40–50 trust; 50–56 proof; 56–60 end card. It uses only the supplied images, linked CC0 photos and approved claims. Dark graphite/amber styling, kinetic captions, original CC0 electronic music, no voiceover. Both aspect ratios are fully rendered; no placeholders or missing media remain.

Approved figures: gear photo-match IoU 0.94, under 5 minutes; strap hinge 70 mm; 248 tests; 28/28 sealed evals; CI green; v0.1.22. These are supplied project claims, not tests rerun by the video production. The original screenshot trust/warning states are preserved. The prompt bubble is an explicitly labelled example.

Exact end card:

```text
photo-to-part v0.1.22
github.com/mojomast/hermes-photo-to-part
Built for Hermes Agent by @NousResearch
```

All four MP4s passed full decoding, duration/frame-count, dimensions, loudness and true-peak checks. Both source builds reproduce their rendered fingerprints. Landscape preview playback showed 1,800 frames with zero dropped frames/stalls/errors. Subjective listening remains a human review step.

## Optional editing

Hyperrizz / HyperFrames **0.9.34**; the user explicitly chose Hyperrizz. Node.js 22+, Python 3, FFmpeg/ffprobe and Chromium are required for rendering. Finished audio, fonts, images and licenses are included.

```bash
cd film
npm ci
python3 scripts/audit.py
npm run preview
# If changes are requested:
npm run render
npm run render:square
```

New renders are written to ignored `film/out/`; compact previews go to `film/previews/`. When revising the film, refresh the committed masters in `film/delivery/` from verified renders and update `verification.json` and REVIEW.md together. Preserve the approved timing, source images, numbers, no-VO requirement and end card.

Review the branch and integrate the `film/` deliverables using the project's existing branch workflow. Prepare the landscape MP4 and supplied caption for the owner's hackathon/X submission. Actual publication remains with the owner unless separately authorized.
