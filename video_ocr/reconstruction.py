"""Reconstruction for local video OCR."""

import itertools
from collections import Counter

from rapidfuzz import fuzz

from video_ocr.models import (
    FUZZY_MATCH_THRESHOLD,
    LINE_NUMBER_ONLY_RE,
    LINE_NUMBER_RE,
    LINE_NUMBER_WORD_RE,
    MAX_FRAME_LINE_NUMBER_NEIGHBOR_DISTANCE,
    MIN_AGREEMENT_SHARE,
    MIN_INCREASING_SHARE,
    MIN_NUMBERED_SHARE,
    MIN_READS_FOR_AGREEMENT,
    MISSING_RUN_COLLAPSE_MIN,
    OCR_UNCERTAIN_CONFIDENCE,
    FrameOutcome,
    GapNeighbor,
    LineRead,
    MergedLine,
    MissingLine,
    OCRLine,
    OCRRow,
    OCRWord,
    TimeSpan,
)
from video_ocr.ocr import (
    _line_right,
    _mean_confidence,
    _reconstruct_words,
)


def _split_numbered_text(text: str) -> tuple[int, str] | None:
    """Split text that begins with an editor gutter number plus separator."""
    match = LINE_NUMBER_RE.match(text)
    if not match:
        return None

    number = int(match.group("number"))
    punct_content = match.group("punct_content")
    if punct_content is not None:
        return number, punct_content

    space_content = match.group("space_content") or ""
    # In the plain form (`12 print(...)`), one whitespace character is the
    # separator; additional spaces are evidence of indentation.
    return number, space_content[1:]


def _number_only_line_number(text: str) -> int | None:
    """Return the gutter number from a number-only OCR line, if present."""
    match = LINE_NUMBER_ONLY_RE.match(text)
    return int(match.group("number")) if match else None


def _line_center_y(line: OCRLine) -> float | None:
    """Vertical center of an OCR line when geometry is available."""
    if line.top is None or line.height is None:
        return None
    return line.top + line.height / 2


def _content_words_after_gutter(line: OCRLine) -> list[OCRWord] | None:
    """Return word boxes after a standalone gutter token, if the line has one."""
    if len(line.words) < 2:
        return None
    if not LINE_NUMBER_WORD_RE.match(line.words[0].text.strip()):
        return None

    index = 1
    while index < len(line.words) and line.words[index].text.strip() in {":", "|", "."}:
        index += 1
    return line.words[index:]


def _code_origin_for_frame(lines: list[OCRLine]) -> int | None:
    """Left edge of the code column inferred from word geometry in one frame."""
    origins: list[int] = []
    for line in lines:
        content_words = _content_words_after_gutter(line)
        if content_words:
            origins.append(content_words[0].left)
            continue
        if _number_only_line_number(line.text) is not None:
            continue
        if _split_numbered_text(line.text) is not None:
            continue
        if line.left is not None:
            origins.append(line.left)
    return min(origins) if origins else None


def _line_content_from_words(line: OCRLine, code_origin: int | None) -> str:
    """Render one code OCR line from word boxes when possible."""
    if line.words:
        return _reconstruct_words(line.words, origin_left=code_origin)
    return line.text


def _content_from_numbered_line(
    line: OCRLine, fallback_content: str, code_origin: int | None
) -> str:
    """Extract content after a gutter number, preferring positional evidence."""
    content_words = _content_words_after_gutter(line)
    if content_words is not None:
        return _reconstruct_words(content_words, origin_left=code_origin)
    return fallback_content


def _gutter_pair_distance(gutter: OCRLine, code: OCRLine) -> float | None:
    """Distance for a spatially plausible pair; missing geometry is not evidence."""
    right = _line_right(gutter)
    if code.left is not None:
        if right is not None and code.left <= right:
            return None
        if gutter.left is not None and code.left <= gutter.left:
            return None
    gutter_center = _line_center_y(gutter)
    code_center = _line_center_y(code)
    if gutter_center is None or code_center is None:
        return None
    distance = abs(code_center - gutter_center)
    max_height = max(gutter.height or 0, code.height or 0, 12)
    return distance if distance <= max(8.0, max_height * 0.75) else None


def _pair_gutter_lines(
    lines: list[OCRLine], excluded: set[int] | None = None
) -> dict[int, int]:
    """Give each code box to its uniquely nearest eligible gutter first.

    Ownership is decided across the whole frame, before choosing a code box for
    each gutter. An earlier number cannot consume a later number's closer text.
    Equidistant boxes stay unpaired rather than choosing by OCR iteration order.
    With no usable vertical geometry, retain only unambiguous adjacency matches.
    """
    gutters = [
        i
        for i, line in enumerate(lines)
        if _number_only_line_number(line.text) is not None
    ]
    owned: dict[int, list[tuple[float, int, int, int]]] = {}
    for index, code in enumerate(lines):
        if excluded and index in excluded:
            continue
        if (
            not code.text.strip()
            or _number_only_line_number(code.text) is not None
            or _split_numbered_text(code.text) is not None
        ):
            continue
        spatial: list[tuple[float, int]] = []
        adjacent: list[tuple[float, int]] = []
        for gutter_index in gutters:
            gutter = lines[gutter_index]
            right = _line_right(gutter)
            if code.left is not None and (
                (right is not None and code.left <= right)
                or (gutter.left is not None and code.left <= gutter.left)
            ):
                continue
            if _line_center_y(gutter) is None or _line_center_y(code) is None:
                if abs(index - gutter_index) == 1:
                    adjacent.append((0.0, gutter_index))
            else:
                distance = _gutter_pair_distance(gutter, code)
                if distance is not None:
                    spatial.append((distance, gutter_index))
        candidates = spatial or adjacent
        if not candidates:
            continue
        best_distance = min(distance for distance, _ in candidates)
        nearest = [g for distance, g in candidates if distance == best_distance]
        if len(nearest) != 1:
            continue
        gutter_index = nearest[0]
        owned.setdefault(gutter_index, []).append(
            (
                best_distance,
                abs(index - gutter_index),
                code.left if code.left is not None else 10**9,
                index,
            )
        )
    return {gutter: min(candidates)[-1] for gutter, candidates in owned.items()}


def _find_paired_code_line(
    gutter_index: int, lines: list[OCRLine], paired_code_lines: set[int]
) -> int | None:
    """Compatibility helper using the same frame-wide ownership as parsing."""
    return _pair_gutter_lines(lines, paired_code_lines).get(gutter_index)


def _to_line_read(
    row: OCRRow,
    *,
    line_number: int | None,
    content: str,
    confidence: float | None,
) -> LineRead:
    """Build a line read while copying frame provenance from its OCR row."""
    return LineRead(
        line_number=line_number,
        content=content,
        frame_number=row.frame_number,
        time_seconds=row.time_seconds,
        time_formatted=row.time_formatted,
        confidence=confidence,
        sharpness=row.sharpness,
    )


def _filter_frame_line_number_outliers(reads: list[LineRead]) -> list[LineRead]:
    """Drop implausible frame-local gutter numbers without guessing a repair."""
    numbered = [read.line_number for read in reads if read.line_number is not None]
    if len(numbered) < 3:
        return reads

    filtered: list[LineRead] = []
    for read in reads:
        if read.line_number is None:
            filtered.append(read)
            continue

        neighbors = [number for number in numbered if number != read.line_number]
        if not neighbors:
            filtered.append(read)
            continue
        nearest = min(abs(read.line_number - number) for number in neighbors)
        if nearest <= MAX_FRAME_LINE_NUMBER_NEIGHBOR_DISTANCE:
            filtered.append(read)
            continue

        # Preserve the OCR content and provenance, but do not let one isolated
        # gutter glitch create a fabricated line number or thousands of gaps.
        filtered.append(read.model_copy(update={"line_number": None}))
    return filtered


def parse_code_lines(
    rows: list[OCRRow], *, strip_line_numbers: bool = True
) -> list[LineRead]:
    """Split each frame read into per-line reads, extracting leading line numbers.

    Numbered reads can be plain (`12 print(...)`), colon/pipe separated
    (`12:print(...)`, `12|print(...)`), or split into neighboring OCR lines
    where the gutter number and code text have separate boxes. Content is
    reconstructed from word geometry when available so indentation and
    meaningful intra-line spacing survive the OCR stage.

    With ``strip_line_numbers=False`` every line keeps its full text — used by
    the unnumbered path so code that merely starts with an integer is not cut.
    """
    reads: list[LineRead] = []
    for row in rows:
        frame_reads: list[LineRead] = []
        frame_lines = [line for line in row.lines if line.text.strip()]
        if not strip_line_numbers:
            for line in frame_lines:
                frame_reads.append(
                    _to_line_read(
                        row,
                        line_number=None,
                        content=line.text,
                        confidence=line.confidence,
                    )
                )
            reads.extend(frame_reads)
            continue

        code_origin = _code_origin_for_frame(frame_lines)
        gutter_pairs = _pair_gutter_lines(frame_lines)
        paired_code_lines = set(gutter_pairs.values())

        for index, line in enumerate(frame_lines):
            if index in paired_code_lines:
                continue
            if not line.text.strip():
                continue

            number_only = _number_only_line_number(line.text)
            if number_only is not None:
                paired_index = gutter_pairs.get(index)
                if paired_index is None:
                    frame_reads.append(
                        _to_line_read(
                            row,
                            line_number=number_only,
                            content="",
                            confidence=line.confidence,
                        )
                    )
                    continue

                code_line = frame_lines[paired_index]
                frame_reads.append(
                    _to_line_read(
                        row,
                        line_number=number_only,
                        content=_line_content_from_words(code_line, code_origin),
                        confidence=_mean_confidence(
                            (line.confidence, code_line.confidence)
                        ),
                    )
                )
                continue

            split = _split_numbered_text(line.text)
            if split:
                line_number, fallback_content = split
                content = _content_from_numbered_line(
                    line, fallback_content, code_origin
                )
            else:
                line_number = None
                content = line.text
            frame_reads.append(
                _to_line_read(
                    row,
                    line_number=line_number,
                    content=content,
                    confidence=line.confidence,
                )
            )
        reads.extend(_filter_frame_line_number_outliers(frame_reads))
    return reads


def has_line_numbers(reads: list[LineRead]) -> bool:
    """Decide whether the video shows editor line numbers.

    True when enough reads carry a leading number (``MIN_NUMBERED_SHARE``) and
    those numbers are mostly increasing within each frame
    (``MIN_INCREASING_SHARE``) — guarding against code that merely starts
    with integers.
    """
    if not reads:
        return False
    numbered = [read for read in reads if read.line_number is not None]
    if len(numbered) / len(reads) < MIN_NUMBERED_SHARE:
        return False

    increasing = 0
    total_pairs = 0
    by_frame: dict[int, list[int]] = {}
    for read in numbered:
        assert read.line_number is not None
        by_frame.setdefault(read.frame_number, []).append(read.line_number)
    for numbers in by_frame.values():
        for previous, current in itertools.pairwise(numbers):
            total_pairs += 1
            if current > previous:
                increasing += 1
    if total_pairs == 0:
        return True
    return increasing / total_pairs >= MIN_INCREASING_SHARE


def _normalized(text: str) -> str:
    """Collapse whitespace for frequency counting and fuzzy comparison."""
    return " ".join(text.split())


def _same_line(a: str, b: str) -> bool:
    """Fuzzy-decide whether two reads show the same on-screen line.

    Comparison only — the texts are never blended, averaged, or repaired.
    """
    return fuzz.ratio(_normalized(a), _normalized(b)) >= FUZZY_MATCH_THRESHOLD


def _best_read(
    group: list[LineRead], *, uncertain_confidence: float = OCR_UNCERTAIN_CONFIDENCE
) -> MergedLine:
    """Pick a group's best read: frequency, then confidence, then sharpness.

    The winner is chosen among non-empty reads when any exist — a gutter-only
    read (number seen, content not) is evidence the content was unreadable in
    that frame, not that the line is blank. The most frequent content wins
    (whitespace-normalized for counting), ties broken by confidence then frame
    sharpness. The winning read's content is emitted verbatim — reads are
    never blended. The line is flagged uncertain when the winner's confidence
    is missing or below ``uncertain_confidence``, or when fewer than
    ``MIN_AGREEMENT_SHARE`` of at least ``MIN_READS_FOR_AGREEMENT`` reads
    fuzzy-match the winning content — disagreement across frames marks
    garbage that saturated engine confidences would let through.
    """
    candidates = [read for read in group if _normalized(read.content)] or group
    frequency = Counter(_normalized(read.content) for read in candidates)
    top_count = max(frequency.values())
    finalists = [
        read for read in candidates if frequency[_normalized(read.content)] == top_count
    ]
    winner = max(
        finalists,
        key=lambda read: (
            read.confidence if read.confidence is not None else -1.0,
            read.sharpness,
        ),
    )
    agreeing = sum(1 for read in group if _same_line(read.content, winner.content))
    contested = (
        len(group) >= MIN_READS_FOR_AGREEMENT
        and agreeing / len(group) < MIN_AGREEMENT_SHARE
    )
    uncertain = (
        winner.confidence is None
        or winner.confidence < uncertain_confidence
        or contested
    )
    return MergedLine(read=winner, uncertain=uncertain)


def merge_ocr_results(
    reads: list[LineRead],
    *,
    uncertain_confidence: float = OCR_UNCERTAIN_CONFIDENCE,
) -> list[MergedLine]:
    """Consolidate repeated reads of each numbered line into one best read.

    Reads are grouped by detected line number and each group's winner is
    chosen by :func:`_best_read`; the result is ordered by line number.
    Gaps in numbering are left as gaps.
    """
    by_number: dict[int, list[LineRead]] = {}
    for read in reads:
        if read.line_number is not None:
            by_number.setdefault(read.line_number, []).append(read)
    return [
        _best_read(by_number[number], uncertain_confidence=uncertain_confidence)
        for number in sorted(by_number)
    ]


def _overlap_length(document: list[list[LineRead]], frame_lines: list[LineRead]) -> int:
    """Longest document suffix whose lines all fuzzy-match the frame's head.

    Tried from the longest candidate down; every aligned pair must match, so
    an ambiguous alignment yields 0 (keeping a duplicate) rather than a
    partial merge that could drop a real line.
    """
    for overlap in range(min(len(document), len(frame_lines)), 0, -1):
        start = len(document) - overlap
        if all(
            _same_line(frame_lines[index].content, document[start + index][-1].content)
            for index in range(overlap)
        ):
            return overlap
    return 0


def reconstruct_by_time(
    reads: list[LineRead],
    *,
    uncertain_confidence: float = OCR_UNCERTAIN_CONFIDENCE,
) -> list[MergedLine]:
    """Reconstruct unnumbered code in video-time order, deduplicating scroll.

    Frames are processed in ascending time; within a frame, lines keep their
    on-screen top-to-bottom order. Each frame's lines are aligned against the
    tail of the document built so far: the overlapping reads join the
    existing per-line groups, only the lines past the overlap are appended as
    new. With no overlap the whole frame is appended — a duplicate is always
    preferable to a dropped line. Each group's winner is then chosen by
    :func:`_best_read`, verbatim.
    """
    by_frame: dict[int, list[LineRead]] = {}
    for read in reads:
        by_frame.setdefault(read.frame_number, []).append(read)

    document: list[list[LineRead]] = []
    for frame_number in sorted(by_frame):
        frame_lines = by_frame[frame_number]
        overlap = _overlap_length(document, frame_lines)
        start = len(document) - overlap
        for index, read in enumerate(frame_lines):
            if index < overlap:
                document[start + index].append(read)
            else:
                document.append([read])
    return [
        _best_read(group, uncertain_confidence=uncertain_confidence)
        for group in document
    ]


def _gap_neighbor(item: MergedLine) -> GapNeighbor:
    """Provenance of a merged line as one side of a numbering gap."""
    read = item.read
    assert read.line_number is not None
    return GapNeighbor(
        line_number=read.line_number,
        frame_number=read.frame_number,
        time_seconds=read.time_seconds,
        time_formatted=read.time_formatted,
    )


def detect_missing_lines(merged: list[MergedLine]) -> list[MissingLine]:
    """Flag every line number absent from the numbered reconstruction.

    Walks the numbered merged lines in line-number order: each jump greater
    than 1 yields one :class:`MissingLine` per absent number, carrying the
    surrounding lines' timestamps; numbering that starts above 1 yields the
    leading numbers as gaps with no before-neighbor. Reads without line
    numbers (the time-ordered path) produce no gaps — where numbering is
    absent, missing lines are never guessed. Empty and single-line input
    return an empty list.
    """
    numbered = sorted(
        (
            (item.read.line_number, item)
            for item in merged
            if item.read.line_number is not None
        ),
        key=lambda pair: pair[0],
    )
    if not numbered:
        return []

    missing: list[MissingLine] = []
    first_number, first_item = numbered[0]
    for absent in range(1, first_number):
        missing.append(MissingLine(line_number=absent, after=_gap_neighbor(first_item)))
    for (previous_number, previous_item), (
        next_number,
        next_item,
    ) in itertools.pairwise(numbered):
        for absent in range(previous_number + 1, next_number):
            missing.append(
                MissingLine(
                    line_number=absent,
                    before=_gap_neighbor(previous_item),
                    after=_gap_neighbor(next_item),
                )
            )
    return missing


def unextractable_sections(outcomes: list[FrameOutcome]) -> list[TimeSpan]:
    """Group consecutive unusable sampled frames into (start, end) time spans.

    Spans come only from observed per-frame outcomes — frames discarded as
    blurry or whose OCR came back blank; content is never inferred.
    Near-duplicate discards are covered by their accepted neighbor and do not
    open or extend a span.
    """
    spans: list[TimeSpan] = []
    run: list[FrameOutcome] = []

    def flush_run() -> None:
        if run:
            spans.append(
                TimeSpan(
                    start_seconds=run[0].time_seconds,
                    end_seconds=run[-1].time_seconds,
                    start_formatted=run[0].time_formatted,
                    end_formatted=run[-1].time_formatted,
                    frames=len(run),
                )
            )
            run.clear()

    for outcome in outcomes:
        if outcome.usable:
            flush_run()
        else:
            run.append(outcome)
    flush_run()
    return spans


def _missing_line_entry(missing: MissingLine) -> str:
    """Render one missing line per the README phrasing, without inventing times."""
    if missing.before and missing.after:
        # Scroll overlap means the neighbors' best reads may come from any
        # frame each line appears in; render the window chronologically.
        first, second = sorted(
            (missing.before, missing.after), key=lambda side: side.time_seconds
        )
        return (
            f"Linha {missing.line_number} possivelmente ausente entre os tempos "
            f"{first.time_formatted} e {second.time_formatted}."
        )
    if missing.after:
        return (
            f"Linha {missing.line_number} possivelmente ausente antes do tempo "
            f"{missing.after.time_formatted} (sem linha extraída antes da lacuna)."
        )
    if missing.before:
        return (
            f"Linha {missing.line_number} possivelmente ausente depois do tempo "
            f"{missing.before.time_formatted} (sem linha extraída depois da lacuna)."
        )
    return (
        f"Linha {missing.line_number} possivelmente ausente "
        "(sem linhas vizinhas extraídas)."
    )


def _collapsed_run_entry(run: list[MissingLine]) -> str:
    """Render a contiguous run of absent line numbers as one range entry.

    A leading run (no before-neighbor) is the "never shown in the video" case;
    an interior run is bounded by the surrounding extracted lines' timestamps.
    The report's total count is untouched — only the listing is condensed.
    """
    first, last = run[0], run[-1]
    numbers = f"Linhas {first.line_number} a {last.line_number}"
    if first.before is None:
        window = (
            f" (primeira linha extraída vista no tempo {last.after.time_formatted})"
            if last.after is not None
            else ""
        )
        return f"{numbers} nunca exibidas no vídeo{window}."
    sides = [side for side in (first.before, last.after) if side is not None]
    if len(sides) == 2:
        low, high = sorted(sides, key=lambda side: side.time_seconds)
        return (
            f"{numbers} possivelmente ausentes entre os tempos "
            f"{low.time_formatted} e {high.time_formatted}."
        )
    edge = sides[0]
    return f"{numbers} possivelmente ausentes próximo ao tempo {edge.time_formatted}."


def _missing_line_entries(missing: list[MissingLine]) -> list[str]:
    """Render missing lines, collapsing any long contiguous run into one range.

    Numbering gaps yield one absent number each; a wide gap (a scroll jump or a
    single misread gutter number) would otherwise emit hundreds of lines and
    drown the real gaps. Contiguous runs of at least ``MISSING_RUN_COLLAPSE_MIN``
    absent numbers — leading or interior — become one range entry; shorter runs
    stay itemized. The report's total count is untouched.
    """
    entries: list[str] = []
    run: list[MissingLine] = []

    def flush() -> None:
        if not run:
            return
        if len(run) >= MISSING_RUN_COLLAPSE_MIN:
            entries.append(_collapsed_run_entry(run))
        else:
            entries.extend(_missing_line_entry(item) for item in run)
        run.clear()

    for item in missing:
        if run and item.line_number != run[-1].line_number + 1:
            flush()
        run.append(item)
    flush()
    return entries


def _uncertain_entry(item: MergedLine) -> str:
    """Render one low-confidence merged line with its frame/time provenance."""
    read = item.read
    line_part = f"linha {read.line_number}, " if read.line_number is not None else ""
    confidence = f"{read.confidence:.1f}" if read.confidence is not None else "n/d"
    return (
        f"- {line_part}frame={read.frame_number}, tempo={read.time_formatted}, "
        f'confiança={confidence}: `"{read.content}"`'
    )
