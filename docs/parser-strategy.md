# Parser Strategy

This document is the authoritative reference for QALens's parser layer (Phase 3+).
It covers the abstraction contract, format detection logic, extraction strategy,
extension points, and the reasoning behind key design decisions.

---

## Design Principles

1. **Extract only** — parsers produce `TestRun`; they never classify failures,
   score flakiness, or generate insights.
2. **Warn, don't crash** — missing or malformed optional fields become
   `ExtractionWarning` entries on `TestRun.warnings`, not exceptions.
3. **Deterministic** — identical input always produces identical output.
4. **Prefer structured hints** — Allure's `widgets/` JSON is more stable than
   its rendered DOM; Extent's embedded `var testdata = {...}` is more reliable
   than scraping CSS classes. DOM traversal is a fallback, not the primary path.
5. **Confidence-based detection** — each parser assigns a float confidence score
   to its detection verdict, letting the `Detector` pick the best match rather
   than failing on ambiguity.

---

## Parser Contract

Every QALens parser **must** subclass `BaseParser` (defined in `src/qalens/parsers/base.py`):

```python
class BaseParser(ABC):
    parser_key: str          # "allure", "extent", …
    parser_name: str         # human-readable label

    @abstractmethod
    def can_parse(self, report_path: Path) -> DetectionResult: ...

    @abstractmethod
    def parse(self, report_path: Path) -> TestRun: ...
```

### Why ABC and not Protocol?

`Protocol` would require all callers to be structurally compatible, making it
harder to attach shared helpers (warning accumulation, default plumbing).
`ABC` makes the contract explicit and forces implementors to read the base class,
which is acceptable for the small number of expected implementations.

---

## DetectionResult

`DetectionResult` is a frozen Pydantic model returned by every `can_parse()` call:

| Field | Type | Description |
|---|---|---|
| `parser_key` | `str` | Identifies the parser, e.g. `"allure"` |
| `parser_name` | `str` | Human-readable name |
| `confidence` | `float` | `0.0`–`1.0` |
| `reasons` | `list[str]` | Evidence strings (logged and surfaced to the user) |
| `matched_files` | `list[Path]` | Files that contributed to the verdict |
| `warnings` | `list[str]` | Non-fatal issues during detection |
| `matched` _(computed)_ | `bool` | `confidence >= 0.5` |

### Confidence thresholds

| Range | Label | Meaning |
|---|---|---|
| ≥ 0.80 | High | Definitive signal present (meta tag, JSON file) |
| 0.50–0.79 | Medium | Multiple corroborating signals |
| 0.30–0.49 | Low | Weak or single signal — `matched` is `False` |
| < 0.30 | None | No recognizable signal |

`DetectionResult.no_match()` returns `confidence=0.0`.
`DetectionResult.unknown()` returns `parser_key="unknown"` and `confidence=0.0`.

---

## Detector

`Detector` (in `src/qalens/parsers/detector.py`) is a registry and dispatcher:

```python
detector = Detector()                    # registers AllureHtmlParser + ExtentHtmlParser
result   = detector.detect(path)         # returns the highest-confidence DetectionResult
parser   = detector.get_parser("allure") # retrieve by key
parser   = detector.get_parser_for_path(path)  # detect + retrieve in one call
```

The default parser registration order is `[AllureHtmlParser, ExtentHtmlParser]`.
When two parsers tie on confidence, the one registered first wins.
The minimum confidence for a successful match is **0.30**; below that
`detect()` returns `DetectionResult.unknown()`.

### Custom parsers

```python
detector = Detector(parsers=[])       # empty registry
detector.register(MyParser())         # add a custom parser
detector.unregister("allure")         # remove a built-in parser
```

Registering a parser with an existing `parser_key` **replaces** the old entry.

---

## Report Detection — Signal Overview

### Allure detection signals (`AllureHtmlParser.can_parse`)

| Signal | File / Artefact | Confidence |
|---|---|---|
| Both `widgets/summary.json` and `data/suites.json` exist | JSON | **0.96** |
| `widgets/summary.json` exists | JSON | 0.90 |
| `data/suites.json` exists | JSON | 0.85 |
| Extra data JSON files (`behaviors.json`, `categories.json`, …) | JSON | 0.80 |
| `app.js` contains the string `"allure"` | JS | 0.75 |
| Entry HTML has `ng-app` attribute (AngularJS) | DOM | 0.70 |
| `<title>` contains `"allure"` | DOM | 0.65 |
| Script `src` attribute references `"allure"` | DOM | 0.65 |

### Extent detection signals (`ExtentHtmlParser.can_parse`)

| Signal | File / Artefact | Confidence |
|---|---|---|
| `<meta name="generator" content="ExtentReports…">` | DOM | **0.95** |
| `var reportConfig = {…}` or `var testdata = {…}` in script | DOM/JS | 0.85 |
| Known Extent CSS class names in DOM | DOM | 0.70 |
| `config.js`, `spark-config.js`, `extent.js` present | FS | 0.65 |
| `spartan-sources/`, `spark/`, `assets/` directories | FS | 0.55 |

### Why structured hints over DOM scraping?

DOM structure is a rendering artefact — Extent and Allure both ship bundled
JS that rehydrates the page. CSS class names and heading text may change
between minor versions without any semantic change to the data. By contrast:

- Allure's `widgets/summary.json` has been structurally stable since Allure 2.0.
- Extent's `<meta name="generator">` tag is documented and version-stamped.
- Extent's `var reportConfig` / `var testdata` script blobs are the authoritative
  data source and predate the rendered DOM.

DOM markers are kept as fallback signals (medium confidence) to handle
edge cases where only the HTML file is available.

---

## Extent Report Parser

### Detection

See the signal table above. The parser uses BeautifulSoup (html.parser) for
meta-tag extraction and regex for the embedded script variable check.
Both checks are fast (no network, no subprocess) and are done in `can_parse`.

### Phase 2 extraction (metadata only)

`parse()` currently:
1. Resolves the entry HTML (`index.html`, `report.html`, or user-supplied file).
2. Reads the `<meta name="generator">` tag for the report version.
3. Reads the `<title>` tag (falling back to `reportConfig.reportName`) for the project name.
4. Builds and returns `RunMetadata`.
5. Returns an empty `test_cases=[]` list with a `HIGH`-severity `ExtractionWarning`.

### Phase 3 extraction (implemented)

`parse()` now performs full test case extraction:
1. Resolves the entry HTML and loads it into BeautifulSoup.
2. Extracts the `var reportConfig = {…}` JSON blob for project metadata.
3. Extracts the `var testdata = {…}` JSON blob containing the complete test tree.
4. Iterates `testdata.tests` → each node → `_extract_test_case_from_node()`.
5. Falls back to DOM traversal of `.test-content` nodes when the JSON blob is
   absent (e.g. older Extent versions that did not embed data).  
6. Builds `RunMetadata` with project name, report version (`5.x` from meta generator),
   and `started_at`/`finished_at` derived from the min/max test timestamps.

**Partial extraction preference**: if `exception` or `details` blocks are missing
for a failed test, a `LOW`-severity warning is emitted and the step-level failure
information is used instead. Only a completely absent `testdata` blob causes a
`HIGH`-severity warning.

**Known limitations**:
- Extent v3 reports without the `var testdata` blob use DOM fallback; tag and
  attachment extraction may be incomplete.
- Nested sub-test nodes beyond depth 2 are supported but step `depth` is tracked
  for filtering by callers.

### Extent → Canonical field mapping

| Extent Field | Canonical Field |
|---|---|
| `test.name` | `TestCaseResult.name` |
| `test.status` | `TestCaseResult.status` |
| `test.startTime` / `endTime` | `started_at` / `finished_at` |
| `test.nodes` | `TestCaseResult.steps` |
| `test.media` | `TestCaseResult.attachments` |
| `test.exception.message` | `FailureInfo.message` |
| `test.exception.stackTrace` | `FailureInfo.stack_trace` |
| `test.category` | `TestCaseResult.tags` |
| `test.author` | `TestCaseResult.owner` |

---

## Allure Report Parser

### Detection

The primary check is file-system existence of `widgets/summary.json` and
`data/suites.json` — no file content is read during detection, making it
almost free. Secondary signals (app.js, DOM markers) require file reads
and are only evaluated if the primary check is inconclusive.

### Phase 2 extraction (metadata only)

`parse()` currently:
1. Resolves the report root directory.
2. Loads `widgets/summary.json` to extract `reportName` and `time.start`/`time.stop`.
3. Converts epoch-millisecond timestamps to UTC `datetime` objects.
4. Builds and returns `RunMetadata` with `started_at` and `finished_at` populated.
5. Returns `test_cases=[]` with a `HIGH`-severity `ExtractionWarning`.

### Phase 3 extraction (implemented)

`parse()` now performs full test case extraction:
1. Resolves the report root directory.
2. Loads `widgets/summary.json` for run-level metadata (`reportName`, timestamps).
3. Loads `data/suites.json` and recursively walks the suite tree to collect test UIDs.
4. For each UID, reads `data/test-cases/<uid>.json` for full detail (steps, failure,
   attachments, labels, links, parameters, retry count).
5. Converts epoch-millisecond timestamps to UTC `datetime` objects.

**Extraction order preference**: per-test JSON files (`data/test-cases/<uid>.json`)
are the authoritative source. The suites tree (`data/suites.json`) is used only as
the discovery index (UID + summary status/name as fallbacks when detail files are missing).

**Partial extraction preference**: when a test detail file is missing (network mount,
partially copied report), the summary-level name and status from `data/suites.json`
still produce a `TestCaseResult` — steps, failure, and attachments are empty and no
warning is raised unless a detail parse error occurs.

**Known limitations**:
- Allure v1 reports (flat HTML, no `data/` directory) are detected at medium
  confidence via DOM markers but produce empty `test_cases` with a `HIGH`-severity
  warning (v1 detail JSON layout differs).
- Retry deduplication (grouping by `historyId`) is not yet implemented; retries
  appear as separate `TestCaseResult` entries with `is_retry=True`.

### Allure → Canonical field mapping

| Allure Field | Canonical Field |
|---|---|
| `name` | `TestCaseResult.name` |
| `status` | `TestCaseResult.status` |
| `time.start` / `time.stop` | `started_at` / `finished_at` |
| `statusMessage` | `FailureInfo.message` |
| `statusTrace` | `FailureInfo.stack_trace` |
| `steps` | `TestCaseResult.steps` |
| `attachments` | `TestCaseResult.attachments` |
| `labels[name=feature]` | `TestCaseResult.feature` |
| `labels[name=suite]` | `TestCaseResult.suite` |
| `parameters` | `TestCaseResult.parameters` |
| `links` | `TestCaseResult.links` |

---

## Partial Extraction and Warnings

When an expected field is absent or cannot be parsed, the parser calls
`self._warn(...)` (provided by `BaseParser`) instead of raising:

```python
self._warn(
    field="FailureInfo.stack_trace",
    reason="stackTrace field absent in Extent JSON payload",
    test_name="LoginTest.testInvalidPassword",
    severity=WarningSeverity.LOW,
)
```

All accumulated warnings are flushed into `TestRun.warnings` via
`self._collect_warnings()` at the end of `parse()`.  This guarantees that
partial data with warnings is always returned rather than raising and losing
everything that was already parsed.

---

## Adding a New Parser

1. Create `src/qalens/parsers/<format>.py` and subclass `BaseParser`.
2. Set `parser_key` and `parser_name` as class-level string attributes.
3. Implement `can_parse()` → return `DetectionResult` with confidence evidence.
4. Implement `parse()` → return `TestRun`; use `self._warn()` for missing fields.
5. Add fixtures under `tests/fixtures/<format>_sample/`.
6. Add tests in `tests/test_<format>_parser.py`.
7. Export from `src/qalens/parsers/__init__.py`.
8. The `Detector` will pick it up automatically if registered via
   `Detector(parsers=[..., MyParser()])` or `detector.register(MyParser())`.
