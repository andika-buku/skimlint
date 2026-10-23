# skimlint

Experimental CLI to prevent unreadable Markdown mess.

A reader decides in a few seconds whether a document is easy or a slog, before they read a word. skimlint measures what drives that first impression:

- **Text checks** (fast, no browser): paragraph size and inline code density, with line numbers.
- **Visual checks** (`--visual`): skimlint renders the Markdown as GitHub does, cuts the page into 1280×800 screens, and scores each screen with the visual clutter metrics of [Aalto Interface Metrics (AIM)](https://github.com/aalto-ui/aim).

## Install

```sh
pip install "skimlint @ git+https://github.com/andika-buku/skimlint"            # text checks
pip install "skimlint[visual] @ git+https://github.com/andika-buku/skimlint"    # + visual checks
playwright install chromium                                                     # once, for --visual
```

Python 3.10 or later. To use a Chromium that is already installed, pass `--chromium PATH` or set `SKIMLINT_CHROMIUM`.

## Usage

```sh
skimlint docs/                                        # every *.md file under docs/
skimlint proposal.md design.md
gh pr view 123 --json body -q .body | skimlint -      # a PR description from stdin
skimlint --visual --fail-above m8=5.5 proposal.md
skimlint --format json proposal.md
```

The exit code is 0 when every file passes, 1 when a file fails a check, and 2 when a file cannot be read.

```text
$ skimlint --visual --metrics m4,m6,m7,m8 tests/fixtures/dense.md
tests/fixtures/dense.md
  3:     paragraph has 75 words (max 55): "The sync worker now retries a failed upload …"  [long-paragraph]
  5:     paragraph has 76 words (max 55): "To keep the change small, RetryPolicy keeps its …"  [long-paragraph]
  7:     paragraph has 67 words (max 55): "Rollout is behind the sync_backoff_v2 flag, defaulting to …"  [long-paragraph]
  words 224 · paragraphs 3 · longest 76 words (line 5) · most inline code spans in one paragraph 11
  visual, 1 screen:
    m4   contour_density          first 0.03326    max 0.03326 (screen 1)
    m6   contour_congestion       first 0.8277     max 0.8277 (screen 1)
    m7   subband_entropy          first 2.407      max 2.407 (screen 1)
    m8   feature_congestion       first 4.094      max 4.094 (screen 1)

1 of 1 file failed
```

### Options

| Option | Default | Meaning |
|---|---|---|
| `--max-paragraph-words N` | 55 | Fail on a paragraph or list item over N words. 0 turns it off. |
| `--max-code-spans N` | off | Fail on a paragraph with more than N inline code spans. |
| `--visual` | off | Render each file and score its screens with AIM metrics. |
| `--metrics LIST` | all | AIM metrics to compute, for example `m4,m8`. |
| `--fail-above METRIC=VALUE` | none | Fail when any screen scores above VALUE. Repeatable. |
| `--max-screens N` | 10 | Score at most the first N screens of each file. |
| `--width PX` | 980 | Content column width, as in GitHub's file view. |
| `--jobs N` | CPU count | Parallel workers for the visual metrics. |
| `--save-screenshots DIR` | — | Write the scored screens as PNG files. |
| `--format text\|json` | text | JSON includes every paragraph and every screen's scores. |

## Checks

### Text

| Rule | Measures |
|---|---|
| `long-paragraph` | Words in each paragraph. List items and block quotes count as paragraphs. Headings, table cells, and code blocks do not. |
| `dense-inline-code` | Inline code spans in each paragraph. Many grey chips inside running text look noisy. |

### Visual (AIM)

Each metric runs on every 1280×800 screen. The report gives the first screen, which is what a glance sees, and the screen with the highest score. The last screen is padded with white.

| ID | Metric | Higher means |
|---|---|---|
| m1 | PNG file size | More visual information (compression as a complexity proxy) |
| m2 | JPEG file size | Same, with JPEG at quality 70 |
| m3 | Distinct RGB values | More colours |
| m4 | Contour density | More edges: text, chips, borders |
| m5 | Figure-ground contrast | Clearer separation of content and background |
| m6 | Contour congestion | Edges packed closer together |
| m7 | Subband entropy | A less predictable, more cluttered image (Rosenholtz et al. 2007) |
| m8 | Feature congestion | More clutter in colour, contrast, and orientation (Rosenholtz et al. 2007) |
| m13 | Luminance standard deviation | More light-dark variation |

## Calibration status

The thresholds are provisional. They come from one reader's verdicts on two pairs of real documents: one pair of PR descriptions and one pair of specs.

| Document | Reader verdict | Longest paragraph | m8, first screen |
|---|---|---|---|
| PR description A | easy | 14 words | 4.36 |
| PR description B | awful | 56 words | 5.65 |
| Spec C | ok | 52 words | 4.34 |
| Spec D | awful | 135 words | 6.44 |

The default of 55 words passes both documents that the reader accepted and fails both awful ones. m8 separates the same pairs, but two pairs are too few for a default, so no visual check fails unless you set `--fail-above`. Collect more verdicts before you tighten either one.

## Speed

The original AIM code takes about 63 seconds per screen for m1 to m8 and m13, almost all of it in m6, m7, and m8. The port in [`src/skimlint/aim.py`](src/skimlint/aim.py) takes about 11 seconds per screen on one core, and screens run in parallel.

| Metric | Original AIM | skimlint |
|---|---|---|
| m6 contour congestion | 16 s | 0.2 s |
| m7 subband entropy | 16 s | 5.3 s |
| m8 feature congestion | 31 s | 5.1 s |
| Others | < 0.1 s each | < 0.1 s each |

The text checks take milliseconds.

## How the port is verified

The speedups change how a value is computed, not the value. [`tests/test_aim.py`](tests/test_aim.py) compares every metric with the original AIM code on fixture screenshots, with a relative tolerance of 1e-6. The largest difference seen is 7×10⁻¹¹, in m8. To regenerate the reference values, run [`scripts/make_aim_reference.py`](scripts/make_aim_reference.py) against a clone of `aalto-ui/aim`.

One deliberate difference: on a blank screen, m5 and m6 return 0.0, as the AIM code intends. With numpy 2, the original returns NaN there.

## Development

```sh
pip install -e ".[visual,test]"
playwright install chromium
pytest
```

## Credits

- [Aalto Interface Metrics](https://github.com/aalto-ui/aim), MIT License. Oulasvirta et al., "Aalto Interface Metrics (AIM): A Service and Codebase for Computational GUI Evaluation", UIST 2018 Adjunct.
- Rosenholtz, Li, and Nakano, "Measuring visual clutter", Journal of Vision, 2007 (m7, m8).
- [github-markdown-css](https://github.com/sindresorhus/github-markdown-css), MIT License.

See [NOTICE](NOTICE) for the license texts.
