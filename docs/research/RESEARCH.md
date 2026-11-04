# photo-to-part: best practice review (2026-11-02) and improvement plan

Scope: agent/LLM-driven reconstruction of physical parts from photos plus a few measurements, and scan cleanup, into printable parametric CAD or meshes with self-verification. Inputs: web sources (dates noted) plus our 5 test rounds (`/workspace/photo-to-part-test-r{2..5}/REPORT.md`) against v0.1.4 (4002dfd). Research only; no repo changes.

Verification note. Sources marked ✔ were opened and read. Sources marked (s) are known only from search-result summaries and should be checked before quoting.

## 1. What the field looks like now (short)

1. **Executable CadQuery code is the dominant target representation, and iterative repair beats one-shot.**
   - CADReasoner (arXiv 2603.29847, CVPR 2026 Findings) ✔ runs a CadQuery program, renders it, and feeds back **multi-view overlays (target in green, prediction in red, 6 ortho + 2 iso views) plus nearest-surface offset vectors**. It keeps the **best-so-far** candidate by Chamfer distance, and both IoU and invalid rate improve over t=1→5 iterations.
   - IterCAD (arXiv 2608.24020) ✔ makes it a learned **REVISE/STOP** loop over dimensioned orthographic views: max 4 turns, ~90% of samples stop by turn 2, and IoU rises 89.9→91.6.
   - CADCodeVerify (ICLR 2025, arXiv 2410.05340) ✔ is the training-free version: a VLM generates 2–5 yes/no verification questions from the requirement, answers them against 4 renders, and turns "no" answers into fix instructions. Compiler errors are fed back separately.
2. **Frontier general VLMs are still weak at image→CAD geometry without measurements.**
   - CAD-Coder (ASME JMD, published 2026-03-23; arXiv 2505.14646) ✔: GPT-4.5 IoU_best 0.524 and Qwen2.5-VL-72B 0.352, against a fine-tuned 0.675 on synthetic renders.
   - CadBench (arXiv 2605.10873, May 2026) (s) reports image-conditioned performance still below mesh-conditioned.
   - Implication: user measurements and explicit spec checks matter more than photo reading. That supports our spec-first direction.
3. **Point cloud → CAD code models exist** (CAD-Recode v1.5, ICCV 2025 ✔ README: Qwen2-1.5B, 3.09 GB weights). They are heavy and network-downloaded, so they are out of scope for a lightweight local plugin.
4. **Monocular metric geometry is good but needs intrinsics.**
   - Depth Anything 3 (arXiv 2511.10647, Nov 2025) ✔: DA3METRIC-LARGE (Apache-2.0) outputs canonical depth and needs `focal_px/300` to get metres. **Camera intrinsics are required**, per a maintainer comment on GitHub issue #72, 2025-11-25.
   - MoGe-2 (NeurIPS 2025) (s) predicts metric point maps plus intrinsics.
   - Sub-mm accuracy for small parts is not claimed by either. For printable parts, a physical reference in the plane (coin, ruler, ArUco marker) or calipers remains the trustworthy scale.
5. **Segmentation.** SAM 3 (Meta, 2025-11-19) ✔ does text, point, box and exemplar prompting, and its weights are open. A foreground mask from a point/box prompt is the standard way to get silhouettes; colour thresholding is not.
6. **Capture.** For small objects, phone photogrammetry beats phone LiDAR: iPhone 16 Pro Max photogrammetry RMSE 1.52–1.68 mm vs LiDAR 2.40–2.74 mm (Turkey Lidar Journal 2025 (s)). Scans are mm-class at best, so treat scans as references for a CAD rebuild, not as the deliverable. That matches our skill text.
7. **Mesh repair.** PyMeshFix (pyvista, v0.18.x docs ✔ via search) repairs to a single watertight mesh, fills holes, removes self-intersections and can join components. manifold3d guarantees manifold booleans. Both are pip-installable and local.
8. **Print readiness.**
   - Slicer CLIs slice and export G-code. PrusaSlicer `--info` and `--export-gcode` give dims, time and filament from G-code comments, but there is **no native printability report** (Prusa forum and issue #10934 (s)).
   - Wall thickness is typically estimated by inward ray casting from face samples. Overhang is the face-normal angle beyond 45° from vertical (trimesh issue #1899, PySLM blog (s)).
9. **Print-in-place clearances.** The common FDM guidance is **0.3 mm per side** for a 0.4 mm nozzle, 0.4 mm for typical PLA and 0.45–0.5 mm for PETG, and to **print a clearance test first** (Loftsmith guide; Printables tolerance testers (s)). An MCP project (mcp-printable (s)) makes a **clearance sweep through the joint's motion range mandatory for hinges**. I could not open the doc to confirm, so treat it as an idea, not a citation.
10. **Agent tool design.**
    - Anthropic, "Writing effective tools for agents" (2025-09-11) ✔: few consolidated, workflow-shaped tools; return **high-signal** context; `response_format` concise/detailed; truncation with guidance; **actionable error messages, not tracebacks**; unambiguous parameter names; **evaluate with realistic multi-step tasks and track tool calls, tokens and errors**; iterate on descriptions using transcripts.
    - MCP 2025-06-18 spec ✔ (via search summary of the spec pages): optional `outputSchema` + `structuredContent`, and tool annotations (`readOnlyHint`, `destructiveHint`, `idempotentHint`).

## 2. What we're doing that best practice says is wrong (or weak)

1. **There is no best-so-far selection or measured stopping rule.** CADReasoner keeps the best candidate by a geometric metric and stops on no improvement; IterCAD learns STOP. We let the agent decide, and in R3 T10 it overwrote a good version with a broken one. 0.1.3 added history but still trusts the agent's notion of "final". → Track a score per `_vN` and make the best-scoring validated version the default deliverable.
2. **Silhouette from colour or threshold segmentation.** Our auto-fit picked the coin (R3), the cap highlight, and the wrong view (R5 T7, 0.17). The field uses promptable segmentation (SAM-class) with a point or box prompt. At minimum use GrabCut seeded by the ROI.
3. **Single-photo metric claims without intrinsics.** The skill lets the agent read dimensions from an oblique photo with a coin; T8 thickness was read in-plane. Best practice: scale is valid only in the reference plane. Out-of-plane dims need a second view or the user's caliper. Flag every photo-derived number with plane and uncertainty.
4. **The overlay is our only geometric feedback, and it is 2-D, single-view and pose-fitted.** Research loops compare multiple fixed views (≥4–8) plus a metric offset signal. For the photo case we can't render the target, but we *can* give the agent per-dimension residuals (spec vs measured) and an 8-view contact sheet. That is the CADCodeVerify pattern.
5. **The agent writes its own spec and can weaken it (R5 T9).** Verification questions and specs should come from the *requirement* (the user's words and numbers), frozen before modelling, as in CADCodeVerify. v0.1.5's spec-tamper guard is the right fix; also freeze `spec.json` with a hash recorded at creation.
6. **No printability checks beyond watertight/bbox.** The field checks min wall thickness, overhangs and bed contact, and for mechanisms, clearances. We validate topology only, so a 0.4 mm hinge gap or a 0.5 mm washer passes untested.
7. **Errors and outputs are verbose.** Build errors carried boilerplate (R4) and render JSON is long. Anthropic recommends concise, actionable responses and a concise/detailed switch.
8. **Evaluation is manual.** We run 6–13 Hermes runs by hand per round. Best practice is a scripted eval harness with held-out tasks, metrics for tool calls, tokens, errors and pass rate, and transcript review.

## 3. Ranked improvements

Notation: Effort S/M/L. Local means it stays offline and lightweight (no model downloads, pure Python/numpy plus the existing trimesh and manifold3d stack).

### Do now (v0.1.6)
1. **Best-so-far version selection plus a REVISE/STOP rule.** Validate writes a numeric `score` (spec pass count, max dimensional residual mm, IoU if any) into history. The `next_step` hint says STOP when every spec item passes and the residual is under tolerance. It says REVERT TO vK when the new version scores worse. The final render defaults to the best validated version.
   - Why: CADReasoner best-so-far selection ✔ https://arxiv.org/abs/2603.29847; IterCAD revise/stop, most samples stop by turn 2 ✔ https://arxiv.org/abs/2608.24020. Our R3 T10 overwrite, and 3/6 runs hitting the 40-call cap in R5.
   - **M. Local.**
2. **Requirement-derived, frozen verification checklist (CADCodeVerify-style).** At spec creation, turn the user's numbers *and* qualitative features ("5 knuckles", "teardrop", "scroll ends", "two tabs") into a frozen `spec.json` with a hash. Validate answers the numeric items. Qualitative yes/no items are answered by the agent against an 8-view sheet, and the answer is recorded. Any edit to the frozen spec needs a `--reason` and appears in the report.
   - Why: CADCodeVerify ✔ https://arxiv.org/abs/2410.05340. R4 T9 drift, R5 T9 spec weakening, R5 d scrolls→rings.
   - **S–M. Local.**
3. **8-view diff contact sheet (6 ortho + 2 iso) with a per-dimension residual table.** When a previous version exists, overlay vN-1 in red and vN in green (CADReasoner's G/R encoding). Show spec residuals as text on the sheet. This gives the agent geometry-grounded feedback even when the photo overlay is poor.
   - Why: CADReasoner multi-view overlays ✔. CADCodeVerify uses 4 views ✔.
   - **S. Local** (existing z-buffer renderer).
4. **Printability checks in validate.** Min wall thickness via inward ray sampling, overhang area beyond 45°, flat bed-contact area, and smallest feature vs nozzle (default 0.4 mm). For `--expected-shells ≥2`, report the **minimum gap between bodies** and fail below a clearance (default 0.3 mm, configurable per material).
   - Why: thickness by ray casting and overhang by normal angle (s) https://github.com/mikedh/trimesh/issues/1899, https://lukeparry.uk/finding-overhangs-3dprinting-pyslm/; print-in-place 0.3 mm/side guidance (s) https://loftsmith.com/guides/print-in-place-hinge.
   - Note: trimesh ray casting needs `rtree`/`embreex` or falls back slowly. In our env `contains` failed without rtree (R5), so add it to the deps or use manifold3d / `trimesh.proximity`.
   - **M. Local.**
5. **Seeded segmentation for the overlay: GrabCut from ROI/seed, plus a full-pose search.** Search across all 3 views at 5° steps, with mirror, and initialise from PCA of the mask. Report the top 3 poses. Keep `--angled` advisory: still compute IoU.
   - Why: our R3–R5 overlay failures. Promptable segmentation is the norm: SAM 3 ✔ https://ai.meta.com/research/publications/sam-3-segment-anything-with-concepts/ (too heavy to bundle, so use OpenCV GrabCut as the local stand-in).
   - **M. Local** (opencv-python-headless is ~50 MB; acceptable, or implement a simple graph cut with numpy).
6. **Measurement provenance and plane validity in `photo_part_measure`.** Every returned mm value carries `plane` (reference plane or not) and `uncertainty_mm`, computed from pixel error ± and scale error. Refuse, or warn on, out-of-plane dimensions (thickness from a front view). Support **ArUco/AprilTag** detection when present, since it is more robust than a coin.
   - Why: single-photo scale is only valid in-plane and near-perpendicular; markers give ~1–3% (s) https://docs.opencv.org/4.13.0/d5/dae/tutorial_aruco_detection.html. R3/R5 T8 thickness error.
   - **S–M. Local** (OpenCV aruco module).
7. **Concise tool responses plus actionable errors.** Add `response_format: concise|detailed` (default concise ≤ ~15 lines). Lead errors with the cause and one fix, with no boilerplate. Declare `outputSchema` for each tool and return `structuredContent`.
   - Why: Anthropic tool guide ✔ https://www.anthropic.com/engineering/writing-tools-for-agents; MCP 2025-06-18 structured output and annotations (s) https://modelcontextprotocol.io/specification/2025-06-18/server/tools.
   - **S. Local.**
8. **Scripted eval harness in the repo.** Turn our test rounds into `evals/`: ~15 tasks (photos with licences, prompts, ground-truth spec, pass criteria) and a runner that drives Hermes headless. It records pass, residuals, tool calls, minutes, wrong-skill-id attempts and rm/overwrite events, and writes a table. Run it before each release, keeping a held-out subset.
   - Why: Anthropic recommends programmatic evals with realistic multi-step tasks and tracking calls, tokens and errors ✔.
   - **M. Local** (needs a model key at run time only).
9. **Mesh repair fallback via PyMeshFix.** When the manifold3d union leaves non-manifold edges (R4 b/d), offer `photo_part_heal --engine meshfix` with `joincomp`.
   - Why (s): https://pymeshfix.pyvista.org/ / https://github.com/pyvista/pymeshfix.
   - **S. Local** (pip wheel, small).

### Later / optional
10. **Optional slicer check.** If PrusaSlicer, OrcaSlicer or CuraEngine is installed locally, run a headless slice with a stock profile and report success, time, filament and warnings. Skip silently when absent.
    - Why: CLI slicing is the real printability oracle, though no native printability report exists (s) https://manpages.debian.org/unstable/prusa-slicer/prusa-slicer.1.en.html, https://github.com/prusa3d/PrusaSlicer/issues/10934.
    - **M. Local but heavy optional dependency.**
11. **Mechanism sweep check** for hinges: rotate body B about the knuckle axis through the declared range and report the minimum gap and any intersection.
    - Idea from mcp-printable (s, unverified) https://github.com/AaronGoldsmith/mcp-printable.
    - **M. Local.**
12. **Clearance or tolerance coupon generator.** Use `photo_part_template shape=clearance_test` (0.2/0.3/0.4/0.5 mm gaps; thread fit test), and have the skill suggest printing it before a fit-critical part.
    - Why: tolerance-tester practice (s) https://www.printables.com/model/379256-print-in-place-hinge-clearance-tester.
    - **S. Local.**
13. **Optional build123d/CadQuery backend for STEP and fillets** with a pinned install. Research models emit CadQuery, so LLMs are fluent in it. B-rep gives exact fillets and STEP.
    - Why: CADReasoner, CAD-Recode, CAD-Coder all target CadQuery ✔.
    - **L. Heavy** (OCC ~100s of MB). Keep optional.
14. **Optional ML helpers behind an explicit opt-in:**
    - SAM 3 point-prompt masks ✔ https://github.com/facebookresearch/sam3.
    - DA3METRIC/MoGe-2 for a rough out-of-plane depth sanity check. These need intrinsics: from EXIF focal length plus sensor size ✔ https://github.com/ByteDance-Seed/Depth-Anything-3/issues/72.
    - CAD-Recode for scan→CadQuery ✔ https://github.com/filaPro/cad-recode.
    - **L. Network download and GPU-ish, so not default.** Note the DA3 licences: Metric-Large and Small/Base are Apache-2.0, but Large/Giant any-view are CC BY-NC.
15. **Multi-image input.** Hermes attaches one `--image`, and our coat-hook test needed a folder path. Accept `photos=[...]` with a per-photo role (front/side/top/reference). Use one view per axis for in-plane measurements and cross-check dims across views.
    - Why: multi-view evidence dominates single-view in CADReasoner and CadBench (s).
    - **M. Local.**
16. **Hermes-side alias for the skill id** (`plugin:` prefix). This is still 1–3 wasted calls per run. Upstream request, **S**.

## 4. Things we already do that match best practice (keep)
- Parametric executable code as source, a compile → validate → render loop, units/scale guards, versioned outputs with history, and spec-driven validation. These match CADCodeVerify, CADReasoner and IterCAD.
- Scans treated as reference, not deliverable. This matches the scan-accuracy evidence.
- A small, consolidated toolset (6 tools) with `next_step` hints and a cause-first validator. This matches Anthropic's tool guidance.

## Sources
✔ = opened and read; (s) = search summary only.
- ✔ CADCodeVerify / CADPrompt, ICLR 2025: https://arxiv.org/html/2410.05340 · https://github.com/Kamel773/CAD_Code_Generation
- ✔ CADReasoner, CVPR 2026 Findings: https://arxiv.org/abs/2603.29847 · https://openaccess.thecvf.com/content/CVPR2026F/html/Kabisov_CADReasoner_Iterative_Program_Editing_for_CAD_Reverse_Engineering_CVPRF_2026_paper.html
- ✔ IterCAD (2026): https://arxiv.org/abs/2608.24020
- ✔ CAD-Coder, ASME JMD 2026-03-23: https://asmedigitalcollection.asme.org/mechanicaldesign/article/148/7/071702/1231735 · https://arxiv.org/pdf/2505.14646 · https://github.com/anniedoris/cad-coder
- (s) CadBench (May 2026): https://arxiv.org/abs/2605.10873 · https://github.com/anniedoris/CADBench
- ✔ CAD-Recode, ICCV 2025: https://github.com/filaPro/cad-recode
- (s) SightCAD active view selection: https://arxiv.org/html/2610.11954
- ✔ Depth Anything 3: https://arxiv.org/abs/2511.10647 · https://github.com/ByteDance-Seed/depth-anything-3 · https://github.com/ByteDance-Seed/Depth-Anything-3/issues/72
- (s) MoGe-2, NeurIPS 2025: https://github.com/microsoft/MoGe/ · https://wangrc.site/MoGe2Page/
- ✔ SAM 3 (2025-11-19): https://ai.meta.com/research/publications/sam-3-segment-anything-with-concepts/ · https://github.com/facebookresearch/sam3/ · https://about.fb.com/news/2025/11/new-sam-models-detect-objects-create-3d-reconstructions/
- (s) iPhone LiDAR vs photogrammetry, small objects (2025): https://dergipark.org.tr/en/pub/melid/article/1842776 · https://doi.org/10.5194/egusphere-egu25-7731
- (s) PyMeshFix: https://github.com/pyvista/pymeshfix · https://pymeshfix.pyvista.org/
- (s) PrusaSlicer CLI: https://manpages.debian.org/unstable/prusa-slicer/prusa-slicer.1.en.html · https://github.com/prusa3d/PrusaSlicer/issues/10934 · https://forum.prusa3d.com/forum/prusaslicer/export-detailed-printing-info-by-cli/
- (s) Wall thickness / overhang: https://github.com/mikedh/trimesh/issues/1899 · https://lukeparry.uk/finding-overhangs-3dprinting-pyslm/
- (s) Print-in-place clearance: https://loftsmith.com/guides/print-in-place-hinge · https://www.printables.com/model/379256-print-in-place-hinge-clearance-tester · https://github.com/AaronGoldsmith/mcp-printable
- (s) ArUco: https://docs.opencv.org/4.13.0/d5/dae/tutorial_aruco_detection.html
- ✔ Anthropic, Writing effective tools for agents (2025-09-11): https://www.anthropic.com/engineering/writing-tools-for-agents
- (s) MCP 2025-06-18 tools / structured output: https://modelcontextprotocol.io/specification/2025-06-18/server/tools · https://modelcontextprotocol.io/specification/2025-06-18/schema
- (s) Zoo Text-to-CAD API (cloud; not suitable for local plugin): https://zoo.dev/docs/developer-tools/api/ml/generate-a-cad-model-from-text
- (s) build123d-mcp (agent CAD server; README not retrievable): https://github.com/pzfreo/build123d-mcp
