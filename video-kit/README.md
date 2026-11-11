# photo-to-part: 60-second showcase video kit

Everything a video agent needs to make the hackathon showcase video for
photo-to-part, fetchable straight from GitHub. No login needed; the repo is public.

- Repo: https://github.com/mojomast/hermes-photo-to-part
- Branch: `video-kit`
- Release shown in the video: v0.1.22 (https://github.com/mojomast/hermes-photo-to-part/releases/tag/v0.1.22)
- Catalog PR: https://github.com/NousResearch/hermes-agent/pull/153757

Get everything:

```
git clone --branch video-kit --depth 1 https://github.com/mojomast/hermes-photo-to-part.git
# assets are in hermes-photo-to-part/video-kit/assets and hermes-photo-to-part/docs
```

Or download single files from
`https://raw.githubusercontent.com/mojomast/hermes-photo-to-part/video-kit/<path>`.

## What the plugin is

photo-to-part is a Hermes Agent plugin by Kyle Durepos (@mojomast). You give Hermes a
phone photo of a physical part, plus any measurements you know. It rebuilds the part as
a validated, 3D-printable STL and keeps your stated dimensions exact. A live
"Part studio" pane in Hermes Desktop shows each stage until the part is Ready. For common
parts such as spur gears it uses a parametric template instead of guessing geometry. It
scores how well the result matches the photo (IoU), and flags weak matches as untrusted.

## Assets

| File | Raw URL | What it shows |
|---|---|---|
| `video-kit/assets/gear-pane-ready.png` | https://raw.githubusercontent.com/mojomast/hermes-photo-to-part/video-kit/video-kit/assets/gear-pane-ready.png | Part studio pane, spur gear run finished (Ready) |
| `video-kit/assets/strap-hinge-pane-ready.png` | https://raw.githubusercontent.com/mojomast/hermes-photo-to-part/video-kit/video-kit/assets/strap-hinge-pane-ready.png | Part studio pane, strap hinge run finished (Ready) |
| `video-kit/assets/strap-hinge-pane-ready-2.png` | https://raw.githubusercontent.com/mojomast/hermes-photo-to-part/video-kit/video-kit/assets/strap-hinge-pane-ready-2.png | Another strap hinge run in the Ready state |
| `docs/catalog-banner.png` | https://raw.githubusercontent.com/mojomast/hermes-photo-to-part/video-kit/docs/catalog-banner.png | Plugin banner (good for title and end cards) |
| `docs/screenshot-views.png` | https://raw.githubusercontent.com/mojomast/hermes-photo-to-part/video-kit/docs/screenshot-views.png | Four rendered views of a generated sample part |

Source part photos (public domain, CC0, from Wikimedia Commons; credit optional):

- Spur gear: https://upload.wikimedia.org/wikipedia/commons/6/6b/Zahnrad.jpg (Paolo Neo, CC0)
- Iron strap hinge: https://upload.wikimedia.org/wikipedia/commons/2/2d/Strap_Hinge_MET_cdi55-61-56.jpg (The Met, CC0)

## Real numbers you may use (no others)

- Spur gear: used the gear template; photo match IoU 0.94; delivered in under 5 minutes (285 s).
- Strap hinge: 70 mm long, exactly as the user stated; delivered in about 15 minutes.
- 248 automated tests pass, 28/28 sealed evals pass, CI green.
- Version v0.1.22. Built for Hermes Agent by Nous Research.

## Brief

60 seconds, 16:9, 1080p. Confident, clean maker/engineering tone. Dark UI look,
crisp motion, punchy kinetic type, upbeat electronic music with hits on cuts. No
voiceover; big on-screen captions that are readable on a phone.

| Time | Scene |
|---|---|
| 0–5 s | Hook: the gear photo, slow push-in. Caption: "Snap a photo. Get a printable part." |
| 5–12 s | Title card over catalog-banner.png: "photo-to-part, a Hermes plugin". A simple chat bubble with the photo attached and "make me a printable replacement". |
| 12–27 s | Gear: pan and zoom across gear-pane-ready.png. Captions: "Spots a spur gear and uses a parametric template", "Matches the photo: IoU 0.94", "Delivered in under 5 minutes". |
| 27–40 s | Hinge: the strap hinge photo, then strap-hinge-pane-ready.png. Caption: "Strap hinge: 70 mm, exactly as measured". |
| 40–50 s | Trust beats, fast captions over screenshot-views.png and pane crops: "A validated STL every time", "Your measurements stay locked", "Weak photo matches flagged untrusted", "Live progress in the Part studio pane". |
| 50–56 s | Proof strip: "248 tests · 28/28 sealed evals · CI green". |
| 56–60 s | End card: "photo-to-part v0.1.22", "github.com/mojomast/hermes-photo-to-part", "Built for Hermes Agent by @NousResearch". |

## Rules

- Exactly 60 seconds (X hackathon entries must be under 90 s).
- Use only the screenshots and numbers above; don't invent UI, stats or features.
- No logos or brands other than Hermes and Nous Research.
- Export MP4 (H.264 video, AAC audio). A 1080x1080 square cut is a bonus.
