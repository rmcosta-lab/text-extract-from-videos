"""Pure-function tests for the fidelity-critical reconstruction pipeline.

Most functions under test operate on pydantic models — no video, OpenCV, or
OCR backend needed, mirroring the FakeEngine approach proven in
`test_suggest_crop.py`. The one exception is `run_ocr`'s duplicate-outcome
logic, which is exercised with small synthetic frames and skipped when
OpenCV / scikit-image are unavailable.
"""

from pathlib import Path
from typing import Any

import pytest

from extract_code_from_video import (
    CropBox,
    EngineName,
    FrameOutcome,
    InvalidExtractionParameterError,
    LineRead,
    MergedLine,
    MissingLine,
    OCRLine,
    OCRResult,
    OCRRow,
    OCRWord,
    VideoMetadata,
    _best_read,
    _candidate_frame_window,
    _format_time,
    _missing_line_entries,
    _parse_timestamp,
    _reconstruct_words,
    adaptive_sample_step,
    detect_missing_lines,
    has_line_numbers,
    merge_ocr_results,
    parse_code_lines,
    prepare_output_tree,
    reconstruct_by_time,
    run_ocr,
    uncertain_confidence_for,
    unextractable_sections,
    write_extracted_code,
)

# --- fixtures ---------------------------------------------------------------


def _read(
    content: str,
    *,
    number: int | None = None,
    frame: int = 1,
    confidence: float | None = 90.0,
    sharpness: float = 100.0,
) -> LineRead:
    return LineRead(
        line_number=number,
        content=content,
        frame_number=frame,
        time_seconds=frame / 30,
        time_formatted=_format_time(frame / 30),
        confidence=confidence,
        sharpness=sharpness,
    )


def _merged(content: str, *, number: int | None = None, frame: int = 1) -> MergedLine:
    return MergedLine(read=_read(content, number=number, frame=frame))


def _row(lines: list[OCRLine], *, frame: int = 1) -> OCRRow:
    return OCRRow(
        text="\n".join(line.text for line in lines),
        frame_number=frame,
        time_seconds=frame / 30,
        time_formatted=_format_time(frame / 30),
        confidence=90.0,
        sharpness=100.0,
        frame_image_path=f"frames_usados/frame_{frame}.png",
        lines=lines,
    )


def _metadata(*, fps: float = 30.0, total_frames: int = 900) -> VideoMetadata:
    return VideoMetadata(
        fps=fps,
        duration_seconds=total_frames / fps,
        width=1920,
        height=1080,
        total_frames=total_frames,
        codec="hevc",
        source="ffprobe",
    )


# --- timestamps -------------------------------------------------------------


def test_parse_timestamp_accepts_all_documented_forms() -> None:
    assert _parse_timestamp(None, "--start-time") is None
    assert _parse_timestamp("12.5", "--start-time") == 12.5
    assert _parse_timestamp("01:02.5", "--start-time") == 62.5
    assert _parse_timestamp("01:02:03.250", "--end-time") == 3723.25


@pytest.mark.parametrize("value", ["abc", "1:2:3:4", "01:75", "01:75:00"])
def test_parse_timestamp_rejects_invalid_forms(value: str) -> None:
    with pytest.raises(InvalidExtractionParameterError):
        _parse_timestamp(value, "--start-time")


def test_format_time_renders_millisecond_clock() -> None:
    assert _format_time(3723.25) == "01:02:03.250"
    assert _format_time(0.0) == "00:00:00.000"


# --- sampling window --------------------------------------------------------


def test_candidate_frame_window_counts_step_and_forced_frames() -> None:
    start, end, expected, first, last = _candidate_frame_window(
        _metadata(), start_seconds=0.0, end_seconds=None, step=15
    )
    assert (start, end) == (0, 900)
    # 60 step candidates (0, 15, ... 885) plus forced frame 1 (frame 15 is
    # already a step candidate).
    assert expected == 61
    assert (first, last) == (0, 885)


def test_candidate_frame_window_empty_segment_yields_no_candidates() -> None:
    start, end, expected, first, last = _candidate_frame_window(
        _metadata(), start_seconds=40.0, end_seconds=None, step=15
    )
    assert start == end == 900
    assert expected == 0
    assert first is None and last is None


# --- parse_code_lines -------------------------------------------------------


def test_parse_code_lines_extracts_plain_and_separator_numbers() -> None:
    rows = [
        _row(
            [
                OCRLine(text="12 print(x)"),
                OCRLine(text="13:return y"),
                OCRLine(text="14|value = 2"),
            ]
        )
    ]
    reads = parse_code_lines(rows)
    assert [(read.line_number, read.content) for read in reads] == [
        (12, "print(x)"),
        (13, "return y"),
        (14, "value = 2"),
    ]


def test_parse_code_lines_keeps_full_text_when_not_stripping() -> None:
    rows = [_row([OCRLine(text="12 print(x)")])]
    reads = parse_code_lines(rows, strip_line_numbers=False)
    assert [(read.line_number, read.content) for read in reads] == [
        (None, "12 print(x)")
    ]


def test_parse_code_lines_pairs_separate_gutter_and_code_boxes() -> None:
    gutter = OCRLine(
        text="12",
        confidence=95.0,
        left=0,
        top=100,
        width=30,
        height=20,
        words=[OCRWord(text="12", left=0, top=100, width=30, height=20)],
    )
    code = OCRLine(
        text="print(x)",
        confidence=85.0,
        left=60,
        top=100,
        width=200,
        height=20,
        words=[OCRWord(text="print(x)", left=60, top=100, width=200, height=20)],
    )
    reads = parse_code_lines([_row([gutter, code])])
    assert len(reads) == 1
    assert reads[0].line_number == 12
    assert reads[0].content == "print(x)"
    assert reads[0].confidence == 90.0  # mean of the paired boxes


def test_parse_code_lines_unpaired_gutter_yields_empty_content() -> None:
    reads = parse_code_lines([_row([OCRLine(text="12")])])
    assert [(read.line_number, read.content) for read in reads] == [(12, "")]


def test_parse_code_lines_demotes_isolated_line_number_outliers() -> None:
    rows = [
        _row(
            [
                OCRLine(text="1 alpha"),
                OCRLine(text="2 beta"),
                OCRLine(text="3 gamma"),
                OCRLine(text="999 delta"),
            ]
        )
    ]
    reads = parse_code_lines(rows)
    assert [read.line_number for read in reads] == [1, 2, 3, None]
    assert reads[-1].content == "delta"  # content survives, number does not


# --- has_line_numbers -------------------------------------------------------


def test_has_line_numbers_true_for_mostly_numbered_increasing_reads() -> None:
    reads = [_read(f"code {n}", number=n) for n in (1, 2, 3, 4)]
    reads.append(_read("unnumbered"))
    assert has_line_numbers(reads) is True


def test_has_line_numbers_false_when_numbered_share_is_low() -> None:
    reads = [_read("code", number=1)] + [_read(f"text {i}") for i in range(9)]
    assert has_line_numbers(reads) is False


def test_has_line_numbers_false_when_numbers_are_not_increasing() -> None:
    reads = [_read(f"code {n}", number=n) for n in (9, 5, 3, 1)]
    assert has_line_numbers(reads) is False


# --- merging & uncertainty --------------------------------------------------


def test_merge_orders_by_line_number_and_drops_unnumbered_reads() -> None:
    reads = [
        _read("second", number=2),
        _read("first", number=1),
        _read("floating"),
    ]
    merged = merge_ocr_results(reads)
    assert [item.read.content for item in merged] == ["first", "second"]


def test_best_read_prefers_most_frequent_content() -> None:
    group = [
        _read("return x", frame=1),
        _read("return x", frame=2),
        _read("retvrn x", frame=3, confidence=99.0),
    ]
    item = _best_read(group)
    assert item.read.content == "return x"
    assert item.uncertain is False  # fuzzy variant still agrees with the winner


def test_best_read_breaks_frequency_ties_by_confidence() -> None:
    group = [
        _read("value = 1", frame=1, confidence=70.0),
        _read("value = I", frame=2, confidence=95.0),
    ]
    assert _best_read(group).read.content == "value = I"


def test_best_read_flags_low_confidence_as_uncertain() -> None:
    assert _best_read([_read("blur", confidence=30.0)]).uncertain is True
    assert _best_read([_read("clear", confidence=90.0)]).uncertain is False
    assert _best_read([_read("unknown", confidence=None)]).uncertain is True


def test_best_read_flags_divergent_reads_despite_saturated_confidence() -> None:
    group = [
        _read("et n ee", frame=1, confidence=98.1),
        _read("ret rn x", frame=2, confidence=98.5),
        _read("re urn", frame=3, confidence=97.9),
    ]
    item = _best_read(
        group, uncertain_confidence=uncertain_confidence_for(EngineName.paddle)
    )
    assert item.uncertain is True


def test_best_read_never_lets_empty_reads_outvote_content() -> None:
    group = [_read("", frame=i) for i in range(4)]
    group += [_read("return x", frame=10), _read("return x", frame=11)]
    item = _best_read(group)
    assert item.read.content == "return x"
    assert item.uncertain is True  # most frames could not read the content


def test_best_read_keeps_all_empty_group_as_confident_blank() -> None:
    item = _best_read([_read("", frame=i, confidence=95.0) for i in range(3)])
    assert item.read.content == ""
    assert item.uncertain is False


def test_uncertain_confidence_floor_is_calibrated_per_engine() -> None:
    assert uncertain_confidence_for(EngineName.tesseract) == 60.0
    assert uncertain_confidence_for(EngineName.paddle) == 95.0


# --- time-ordered reconstruction --------------------------------------------


def test_reconstruct_by_time_deduplicates_scroll_overlap() -> None:
    frame1 = [
        _read("def alpha():", frame=1),
        _read("    return beta", frame=1),
        _read("print(gamma)", frame=1),
    ]
    frame2 = [
        _read("    return beta", frame=2),
        _read("print(gamma)", frame=2),
        _read("omega = 1", frame=2),
    ]
    merged = reconstruct_by_time(frame1 + frame2)
    assert [item.read.content for item in merged] == [
        "def alpha():",
        "    return beta",
        "print(gamma)",
        "omega = 1",
    ]


def test_reconstruct_by_time_accepts_fuzzy_overlap_variants() -> None:
    frame1 = [_read("    return beta", frame=1), _read("print(gamma)", frame=1)]
    frame2 = [_read("print(ganma)", frame=2), _read("omega = 1", frame=2)]
    merged = reconstruct_by_time(frame1 + frame2)
    assert len(merged) == 3  # the fuzzy variant joined the existing group


def test_reconstruct_by_time_keeps_duplicates_when_nothing_overlaps() -> None:
    frame1 = [_read("alpha_line()", frame=1)]
    frame2 = [_read("totally_different()", frame=2)]
    merged = reconstruct_by_time(frame1 + frame2)
    assert len(merged) == 2


# --- gap detection & report -------------------------------------------------


def test_detect_missing_lines_flags_gaps_with_neighbor_provenance() -> None:
    merged = [_merged("a", number=1), _merged("d", number=4, frame=9)]
    missing = detect_missing_lines(merged)
    assert [item.line_number for item in missing] == [2, 3]
    assert missing[0].before is not None and missing[0].before.line_number == 1
    assert missing[0].after is not None and missing[0].after.line_number == 4


def test_detect_missing_lines_reports_leading_gap_without_before() -> None:
    missing = detect_missing_lines([_merged("x", number=3)])
    assert [item.line_number for item in missing] == [1, 2]
    assert all(item.before is None for item in missing)


def test_detect_missing_lines_ignores_unnumbered_reconstruction() -> None:
    assert detect_missing_lines([_merged("a"), _merged("b")]) == []


def test_missing_line_entries_collapse_leading_run_into_one_range() -> None:
    missing = detect_missing_lines([_merged("x", number=500), _merged("y", number=502)])
    entries = _missing_line_entries(missing)
    assert len(missing) == 500
    assert len(entries) == 2
    assert entries[0].startswith("Linhas 1 a 499 nunca exibidas")
    assert "Linha 501" in entries[1]


def test_missing_line_entries_collapse_long_interior_run() -> None:
    # A single wide interior gap (e.g. a misread gutter number) must not emit
    # one line each; lines 2..19 collapse into one range entry. Starting at
    # line 1 keeps this an interior (before + after) run, not a leading one.
    missing = detect_missing_lines(
        [_merged("a", number=1), _merged("b", number=20, frame=9)]
    )
    entries = _missing_line_entries(missing)
    assert len(missing) == 18
    assert len(entries) == 1
    assert entries[0].startswith("Linhas 2 a 19 possivelmente ausentes entre os tempos")


def test_missing_line_entries_keep_short_gaps_itemized() -> None:
    # A 2-line interior gap stays itemized (each line is still worth naming).
    missing = detect_missing_lines([_merged("a", number=1), _merged("b", number=4)])
    entries = _missing_line_entries(missing)
    assert len(missing) == 2
    assert len(entries) == 2
    assert entries[0].startswith("Linha 2 possivelmente ausente")
    assert entries[1].startswith("Linha 3 possivelmente ausente")


# --- adaptive sampling step -------------------------------------------------


def test_adaptive_sample_step_preserves_canonical_tiers() -> None:
    assert adaptive_sample_step(30.0) == 15
    assert adaptive_sample_step(60.0) == 30
    assert adaptive_sample_step(120.0) == 60


def test_adaptive_sample_step_snaps_atypical_high_rates_to_tiers() -> None:
    assert adaptive_sample_step(25.0) == 15  # nearest 30
    assert adaptive_sample_step(50.0) == 30  # nearest 60
    assert adaptive_sample_step(240.0) == 60  # nearest 120


def test_adaptive_sample_step_uses_half_rate_below_the_low_fps_floor() -> None:
    assert adaptive_sample_step(10.0) == 5
    assert adaptive_sample_step(23.0) == 12
    assert adaptive_sample_step(1.0) == 1  # never zero


def test_unextractable_sections_group_consecutive_unusable_frames() -> None:
    outcomes = [
        FrameOutcome(
            frame_number=i,
            time_seconds=i / 30,
            time_formatted=_format_time(i / 30),
            usable=usable,
        )
        for i, usable in enumerate([True, False, False, True, False])
    ]
    spans = unextractable_sections(outcomes)
    assert [(span.frames, span.start_seconds) for span in spans] == [
        (2, 1 / 30),
        (1, 4 / 30),
    ]


# --- spacing reconstruction -------------------------------------------------


def test_reconstruct_words_preserves_indentation_and_gaps() -> None:
    words = [
        OCRWord(text="return", left=32, top=0, width=48, height=10),
        OCRWord(text="x", left=96, top=0, width=8, height=10),
    ]
    # char width 8 → 4 leading spaces from origin 0, 2 spaces inside the gap.
    assert _reconstruct_words(words, origin_left=0) == "    return  x"


def test_reconstruct_words_without_origin_starts_at_first_word() -> None:
    words = [OCRWord(text="x", left=500, top=0, width=8, height=10)]
    assert _reconstruct_words(words) == "x"


# --- outputs ----------------------------------------------------------------


def test_write_extracted_code_places_marker_before_uncertain_line(
    tmp_path: Path,
) -> None:
    merged = [
        _merged("clean_line()", number=1),
        MergedLine(read=_read("garbled", number=2, frame=7), uncertain=True),
    ]
    write_extracted_code(merged, tmp_path)
    lines = (tmp_path / "codigo_extraido.txt").read_text("utf-8").splitlines()
    assert lines[0] == "clean_line()"
    assert lines[1].startswith("# [OCR_UNCERTAIN] frame=7 ")
    assert 'texto_original="garbled"' in lines[1]
    assert lines[2] == "garbled"


def test_prepare_output_tree_clears_previous_run_artifacts(tmp_path: Path) -> None:
    (tmp_path / "codigo_extraido.txt").write_text("STALE", "utf-8")
    (tmp_path / "ocr_raw.csv").write_text("STALE", "utf-8")
    frames_dir = tmp_path / "frames_usados"
    frames_dir.mkdir()
    (frames_dir / "frame_1.png").write_bytes(b"STALE")

    prepare_output_tree(tmp_path)

    assert not (tmp_path / "codigo_extraido.txt").exists()
    assert not (tmp_path / "ocr_raw.csv").exists()
    assert list(frames_dir.iterdir()) == []


def test_missing_line_model_allows_absent_neighbors() -> None:
    entry = MissingLine(line_number=1)
    assert entry.before is None and entry.after is None


# --- run_ocr duplicate outcomes ---------------------------------------------


class _FixedEngine:
    """OCR engine stub returning the same result for every frame."""

    def __init__(self, text: str) -> None:
        self._text = text

    def recognize(self, image: Any) -> OCRResult:
        return OCRResult(text=self._text, confidence=90.0 if self._text else None)


def _identical_noise_frames(count: int) -> list[tuple[int, float, Any]]:
    """Byte-identical textured frames: each after the first is a near-duplicate.

    Random texture keeps them above the blur threshold; being identical drives
    SSIM to 1.0 so every frame after the first is discarded as a duplicate.
    """
    np = pytest.importorskip("numpy")
    rng = np.random.default_rng(0)
    base = rng.integers(0, 256, size=(200, 300, 3), dtype=np.uint8)
    return [(index, index / 30.0, base.copy()) for index in range(count)]


def test_run_ocr_duplicate_inherits_empty_neighbor_outcome(tmp_path: Path) -> None:
    pytest.importorskip("cv2")
    pytest.importorskip("skimage")
    frames = _identical_noise_frames(3)
    _rows, stats, outcomes = run_ocr(
        iter(frames), _FixedEngine(""), tmp_path, 3, CropBox()
    )
    assert stats.frames_discarded_duplicate == 2
    # The accepted frame's OCR was blank, so the duplicates it "covers" are
    # still unextractable — not silently marked usable.
    assert [outcome.usable for outcome in outcomes] == [False, False, False]


def test_run_ocr_duplicate_inherits_usable_neighbor_outcome(tmp_path: Path) -> None:
    pytest.importorskip("cv2")
    pytest.importorskip("skimage")
    frames = _identical_noise_frames(3)
    rows, stats, outcomes = run_ocr(
        iter(frames), _FixedEngine("codigo()"), tmp_path, 3, CropBox()
    )
    assert stats.frames_discarded_duplicate == 2
    assert len(rows) == 1  # only the accepted frame is OCR'd
    assert [outcome.usable for outcome in outcomes] == [True, True, True]
