# Mission

## Purpose

Reconstruct the **real** source code shown in a screen-recording video by
extracting text from its frames via local OCR. Input is an `.mp4` (or similar)
of a code editor being scrolled vertically; output is the extracted code plus an
honest report of everything that could not be recovered with confidence.

The canonical, locked specification of behavior and deliverables lives in
[`README.md`](../README.md). This document states *why* and *what we optimize
for*; the README states the detailed *what*.

## Overriding success criterion: Fidelity first

We are judged on **accuracy of the extracted text, not on coverage**.

- **Never invent code.** A blank, a gap, or an uncertainty marker is always
  preferable to a fabricated line.
- When a line cannot be read with confidence, mark it in the output:
  `# [OCR_UNCERTAIN] frame=1234 time=00:01:23.400 texto_original="..."`.
- When line numbers reveal a gap (e.g. line 32 → line 34), record the missing
  line explicitly rather than stitching neighbors together.
- Consolidating multiple reads of the same line is allowed and encouraged;
  guessing the *content* of an unread line is not.

Coverage, speed, and ergonomics matter — but only after fidelity. Any change
that trades correctness for more extracted lines is a regression.

## Principles

1. **Local only.** No data leaves the machine. No external APIs.
2. **Honest reporting.** Every discarded frame, missing line, and low-confidence
   passage is surfaced in `relatorio_falhas.md`, not hidden.
3. **Deterministic and inspectable.** Raw OCR is preserved in `ocr_raw.csv` and
   the frames actually used are saved, so any result can be traced back to a
   frame and a timestamp.
4. **Do the minimum work.** Sample frames adaptively by FPS; skip blurry and
   near-duplicate frames instead of processing everything.

## Non-goals

- Not a general video-to-text OCR tool; it is specialized for scrolling code.
- Not a code *corrector* — it does not fix, format, or complete the source.
- No cloud, no LLM-in-the-loop reconstruction in the core pipeline (listed only
  as a future, opt-in review step).

## Definition of done (per run)

Given a video, the tool produces the full output tree defined in the README
(`codigo_extraido.txt`, `relatorio_falhas.md`, `ocr_raw.csv`,
`metadata_video.json`, `frames_usados/`) where every uncertain or missing
passage is explicitly flagged and no line is fabricated.
