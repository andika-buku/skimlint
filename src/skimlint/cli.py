"""skimlint: flags Markdown that reads as a slog at a glance."""

from __future__ import annotations

import argparse
import json
import multiprocessing
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Dict, List, Tuple

from . import __version__, fitness
from .text import TextReport, analyze_text

DEFAULT_MAX_PARAGRAPH_WORDS = 55


def _parse_args(argv: List[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="skimlint",
        description="Flags Markdown that reads as a slog at a glance: long paragraphs, "
        "dense inline code, hard-to-parse sentences (--language), and AIM visual clutter (--visual). "
        "Each file also gets a fitness score from 0 to 100.",
    )
    parser.add_argument("paths", nargs="+", help="Markdown files or directories; '-' reads stdin")
    parser.add_argument("--max-paragraph-words", type=int, default=DEFAULT_MAX_PARAGRAPH_WORDS, metavar="N",
                        help="fail on a paragraph, list item, or table cell over N words "
                        f"(default {DEFAULT_MAX_PARAGRAPH_WORDS}, 0 = off)")
    parser.add_argument("--max-code-spans", type=int, default=0, metavar="N",
                        help="fail on a paragraph with more than N inline code spans (default off)")
    parser.add_argument("--language", action="store_true",
                        help="parse sentences with spaCy: dependency distance and coherence")
    parser.add_argument("--spacy-model", default=None, metavar="NAME",
                        help="spaCy model for --language (default en_core_web_md)")
    parser.add_argument("--max-dependency-distance", type=float, default=0, metavar="X",
                        help="fail on a sentence with a mean dependency distance above X (default off; needs --language)")
    parser.add_argument("--visual", action="store_true",
                        help="render each file and score its screens with AIM clutter metrics")
    parser.add_argument("--metrics", default="m1,m2,m3,m4,m5,m6,m7,m8,m13",
                        help="AIM metrics for --visual (default: all)")
    parser.add_argument("--fail-above", action="append", default=[], metavar="METRIC=VALUE",
                        help="fail when a screen scores above VALUE, for example m8=5.5 (repeatable)")
    parser.add_argument("--max-screens", type=int, default=10, metavar="N",
                        help="score at most the first N screens of each file (default 10)")
    parser.add_argument("--width", type=int, default=980, metavar="PX",
                        help="content column width in pixels (default 980, as GitHub)")
    parser.add_argument("--jobs", type=int, default=os.cpu_count() or 1, metavar="N",
                        help="parallel workers for --visual (default: CPU count)")
    parser.add_argument("--chromium", metavar="PATH",
                        help="Chromium executable for --visual (or set SKIMLINT_CHROMIUM)")
    parser.add_argument("--save-screenshots", metavar="DIR", help="write the scored screens as PNG files")
    parser.add_argument("--format", choices=("text", "json", "fitness"), default="text",
                        help="fitness prints one tab-separated 'score path' line per file")
    parser.add_argument("--version", action="version", version=f"skimlint {__version__}")
    args = parser.parse_args(argv)
    if args.max_screens < 1:
        parser.error("--max-screens must be at least 1")
    if args.max_dependency_distance and not args.language:
        parser.error("--max-dependency-distance needs --language")
    if args.spacy_model and not args.language:
        parser.error("--spacy-model needs --language")
    args.metric_ids = [m.strip() for m in args.metrics.split(",") if m.strip()]
    args.limits = {}
    for item in args.fail_above:
        metric, _, value = item.partition("=")
        try:
            args.limits[metric.strip()] = float(value)
        except ValueError:
            parser.error(f"--fail-above expects METRIC=VALUE, got {item!r}")
    if args.visual:
        from .aim import METRICS

        unknown = [m for m in args.metric_ids + list(args.limits) if m not in METRICS]
        if unknown:
            parser.error(f"unknown metric {unknown[0]!r}; choose from {', '.join(METRICS)}")
    elif args.limits:
        parser.error("--fail-above needs --visual")
    return args


def _collect(paths: List[str]) -> List[Tuple[str, str]]:
    docs = []
    for path in paths:
        if path == "-":
            docs.append(("<stdin>", sys.stdin.read()))
        elif Path(path).is_dir():
            docs.extend((str(p), p.read_text(encoding="utf-8")) for p in sorted(Path(path).rglob("*.md")))
        else:
            docs.append((path, Path(path).read_text(encoding="utf-8")))
    return docs


def _text_findings(report: TextReport, args: argparse.Namespace) -> List[Dict]:
    findings = []
    for p in report.paragraphs:
        if args.max_paragraph_words and p.words > args.max_paragraph_words:
            findings.append({
                "line": p.line, "rule": "long-paragraph",
                "message": f"{'table cell' if p.kind == 'cell' else 'paragraph'} has {p.words} words "
                           f"(max {args.max_paragraph_words}): \"{p.preview} …\"",
            })
        if args.max_code_spans and p.code_spans > args.max_code_spans:
            findings.append({
                "line": p.line, "rule": "dense-inline-code",
                "message": f"paragraph has {p.code_spans} inline code spans (max {args.max_code_spans})",
            })
    return findings


def _language_findings(language, limit: float) -> List[Dict]:
    return [
        {
            "line": s.line, "rule": "hard-sentence",
            "message": f"sentence has dependency distance {s.dependency_distance:.2f} (max {limit:g}): \"{s.preview} …\"",
        }
        for s in language.sentences
        if limit and s.dependency_distance > limit
    ]


def _score_screen(job: Tuple[bytes, List[str]]) -> Dict[str, float]:
    from .aim import run_metrics

    png, metric_ids = job
    return run_metrics(png, metric_ids)


def _visual(docs: List[Tuple[str, str]], args: argparse.Namespace) -> List[Dict]:
    from .aim import METRICS
    from .render import screenshot

    screens = screenshot([md for _, md in docs], args.width, args.max_screens, args.chromium)
    jobs = [(png, args.metric_ids) for doc_screens in screens for png in doc_screens]
    # Spawn, not fork: Playwright has started threads in this process by now.
    context = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(max_workers=max(1, args.jobs), mp_context=context) as pool:
        scores = list(pool.map(_score_screen, jobs))

    results = []
    cursor = 0
    for (name, _), doc_screens in zip(docs, screens):
        doc_scores = scores[cursor : cursor + len(doc_screens)]
        cursor += len(doc_screens)
        if args.save_screenshots:
            out = Path(args.save_screenshots)
            out.mkdir(parents=True, exist_ok=True)
            stem = Path(name).stem if name != "<stdin>" else "stdin"
            for i, png in enumerate(doc_screens, 1):
                (out / f"{stem}-{i}.png").write_bytes(png)
        summary = {}
        for metric_id in args.metric_ids:
            values = [s[metric_id] for s in doc_scores]
            peak = max(range(len(values)), key=values.__getitem__)
            summary[metric_id] = {
                "name": METRICS[metric_id][0],
                "first": values[0],
                "max": values[peak],
                "max_screen": peak + 1,
            }
        results.append({"screens": doc_scores, "summary": summary})
    return results


def _visual_findings(visual: Dict, limits: Dict[str, float]) -> List[Dict]:
    findings = []
    for metric_id, limit in limits.items():
        for i, scores in enumerate(visual["screens"], 1):
            if scores[metric_id] > limit:
                findings.append({
                    "line": None, "rule": f"visual-{metric_id}",
                    "message": f"screen {i}: {metric_id} {visual['summary'][metric_id]['name']} "
                               f"{scores[metric_id]:.4g} (max {limit:g})",
                })
    return findings


def _print_text(results: List[Dict]) -> None:
    for r in results:
        print(r["path"])
        for f in r["findings"]:
            where = f"{f['line']}:" if f["line"] else "-:"
            print(f"  {where:<6} {f['message']}  [{f['rule']}]")
        t = r["text"]
        longest = f"{t['longest_paragraph_words']} words"
        if t["longest_paragraph_line"]:
            longest += f" (line {t['longest_paragraph_line']})"
        print(f"  words {t['words']} · blocks {t['paragraphs']} · longest {longest}"
              f" · most inline code spans in one block {t['max_code_spans']}")
        if "language" in r:
            lang = r["language"]
            if lang["sentences"]:
                coherence = f"{lang['coherence_mean']:.2f}" if lang["coherence_mean"] is not None else "n/a"
                print(f"  sentences {lang['sentences']} · dependency distance mean {lang['dependency_distance_mean']:.2f}"
                      f", p90 {lang['dependency_distance_p90']:.2f} · coherence {coherence}")
        if "visual" in r:
            screens = len(r["visual"]["screens"])
            print(f"  visual, {screens} screen{'s' if screens != 1 else ''}:")
            for metric_id, s in r["visual"]["summary"].items():
                print(f"    {metric_id:<4} {s['name']:<24} first {s['first']:<10.4g} "
                      f"max {s['max']:.4g} (screen {s['max_screen']})")
        fit = r["fitness"]
        if fit["score"] is not None:
            parts = ", ".join(f"{k} {v:.2f}" for k, v in fit["components"].items())
            print(f"  fitness {fit['score']:.1f} ({parts})")
        print()
    failing = sum(1 for r in results if r["findings"])
    print(f"{failing} of {len(results)} file{'s' if len(results) != 1 else ''} failed")


def main(argv: List[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        docs = _collect(args.paths)
    except OSError as e:
        print(f"skimlint: {e}", file=sys.stderr)
        return 2
    nlp = None
    if args.language:
        from .language import DEFAULT_MODEL, load_model

        try:
            nlp = load_model(args.spacy_model or DEFAULT_MODEL)
        except (ImportError, RuntimeError) as e:
            print(f"skimlint: {e}", file=sys.stderr)
            return 2

    results = []
    for name, markdown in docs:
        report = analyze_text(markdown)
        result = {"path": name, "text": report.to_dict(), "findings": _text_findings(report, args)}
        components = {"blocks": fitness.blocks_component(report, args.max_paragraph_words)}
        if nlp is not None:
            from .language import analyze_language

            language = analyze_language(report.paragraphs, nlp)
            result["language"] = language.to_dict()
            result["findings"].extend(_language_findings(language, args.max_dependency_distance))
            components["sentences"] = fitness.sentences_component(language)
        result["_components"] = components
        results.append(result)
    if args.visual and docs:
        for result, visual in zip(results, _visual(docs, args)):
            result["visual"] = visual
            result["findings"].extend(_visual_findings(visual, args.limits))
            result["_components"]["visual"] = fitness.visual_component(visual)
    for result in results:
        result["fitness"] = fitness.score(result.pop("_components"))

    if args.format == "json":
        json.dump(results, sys.stdout, indent=2)
        print()
    elif args.format == "fitness":
        for r in results:
            score = r["fitness"]["score"]
            print(f"{'' if score is None else f'{score:.1f}'}\t{r['path']}")
    else:
        _print_text(results)
    return 1 if any(r["findings"] for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
