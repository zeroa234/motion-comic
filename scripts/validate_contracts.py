#!/usr/bin/env python3
"""Stack-agnostic contract validator for the motion-comic production skill.

Zero third-party dependencies (Python 3.10+ stdlib only).
Validates layer boundary contracts across any underlying CV, TTS, AI video, or rendering stack:
  - timeline   : Audio timeline.json contract
  - manifest   : L0 prepared/<page>/manifest.json contract
  - page-map   : L1 page-map.json contract (with optional timeline anchor resolution)
  - story      : L1 story.json contract (monotonicity, renderers, bubble conflicts, noop zones)
  - qc-report  : L3 qc_report.json delivery gate check
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

DEFAULT_VALID_RENDERERS = {"fast_25d", "video_clip"}
DEFAULT_VALID_FALLBACKS = {"fast_25d"}
ZONE_MOTION_KEYS = ("dx", "dy", "rot", "sx", "sy", "shiver")


def index_timeline(
    timeline: list[dict[str, Any]],
) -> tuple[dict[str, tuple[float, float]], dict[str, list[dict[str, Any]]]]:
    voice_map: dict[str, tuple[float, float]] = {}
    sfx_map: dict[str, list[dict[str, Any]]] = {}
    for ev in timeline:
        if ev.get("voice") and ev.get("line") is not None:
            key = f"{ev['voice']}@{int(ev['line'])}"
            t0 = float(ev["t"])
            sp = ev.get("speech")
            t1 = float(sp[1]) if isinstance(sp, list) and len(sp) >= 2 else t0
            voice_map[key] = (t0, t1)
        if ev.get("sfx"):
            sfx_map.setdefault(str(ev["sfx"]), []).append(ev)
    return voice_map, sfx_map


def resolve_time(
    expr: Any,
    voice_map: dict[str, tuple[float, float]],
    sfx_map: dict[str, list[dict[str, Any]]],
) -> float:
    if isinstance(expr, (int, float)):
        return float(expr)
    if not isinstance(expr, dict):
        raise ValueError(f"Invalid time expression: {expr!r}")
    if "max" in expr:
        return max(resolve_time(x, voice_map, sfx_map) for x in expr["max"])
    if "min" in expr:
        return min(resolve_time(x, voice_map, sfx_map) for x in expr["min"])
    if "anchor" not in expr:
        raise ValueError(f"Time expression missing 'anchor': {expr!r}")

    anchor = str(expr["anchor"])
    offset = float(expr.get("offset", 0.0))
    use_end = anchor.endswith("$")
    core = anchor[:-1] if use_end else anchor

    if core.startswith("sfx:"):
        name = core[4:]
        evs = sfx_map.get(name)
        if not evs:
            raise KeyError(f"SFX anchor not found in timeline: {name!r}")
        idx = int(expr.get("index", 0))
        if idx < 0 or idx >= len(evs):
            raise IndexError(f"SFX anchor {name!r} index {idx} out of range (0..{len(evs) - 1})")
        ev = evs[idx]
        base = float(ev["t"]) + (float(ev.get("dur", 0.0)) if use_end else 0.0)
        return round(base + offset, 4)

    if core in voice_map:
        t0, t1 = voice_map[core]
        return round((t1 if use_end else t0) + offset, 4)
    raise KeyError(f"Voice anchor not found in timeline: {anchor!r}")


def zone_has_effective_motion(z: dict[str, Any]) -> bool:
    if not any(k in z for k in ZONE_MOTION_KEYS):
        # Omitted amplitude keys rely on renderer defaults for z["driver"].
        return True
    shv = z.get("shiver")
    if isinstance(shv, list) and len(shv) >= 2:
        if abs(float(shv[0])) > 1e-7 or abs(float(shv[1])) > 1e-7:
            return True
    return any(abs(float(z.get(k, 0.0))) > 1e-7 for k in ("dx", "dy", "rot", "sx", "sy"))


def validate_timeline(data: Any) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(data, list) or not data:
        return ["timeline.json must be a non-empty JSON array"], warnings

    seen_voices: set[str] = set()
    for i, ev in enumerate(data):
        if not isinstance(ev, dict):
            errors.append(f"event[{i}]: must be an object")
            continue
        if "t" not in ev or not isinstance(ev["t"], (int, float)):
            errors.append(f"event[{i}]: missing numeric 't'")
        has_voice = bool(ev.get("voice")) and ev.get("line") is not None
        has_sfx = bool(ev.get("sfx"))
        if not has_voice and not has_sfx:
            errors.append(f"event[{i}]: must define either (voice + line) or sfx")
        if has_voice:
            key = f"{ev['voice']}@{ev['line']}"
            if key in seen_voices:
                warnings.append(f"event[{i}]: duplicate voice anchor {key!r}")
            seen_voices.add(key)
            sp = ev.get("speech")
            if sp is None:
                warnings.append(f"event[{i}] ({key}): missing 'speech' [onset, end]; cue_sync will fall back to 't'")
            elif not (isinstance(sp, list) and len(sp) == 2 and sp[1] >= sp[0]):
                errors.append(f"event[{i}] ({key}): invalid 'speech' interval {sp!r}")
        if has_sfx and ev.get("under") and float(ev.get("dur", 0.0)) <= 0:
            errors.append(f"event[{i}] (sfx:{ev['sfx']}): 'under' SFX must specify positive 'dur'")
    return errors, warnings


def validate_manifest(data: Any, manifest_dir: Path | None = None) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(data, dict):
        return ["manifest.json must be a JSON object"], warnings

    for req in ("schema", "size", "is_monochrome", "panels"):
        if req not in data:
            errors.append(f"manifest missing required key: {req!r}")

    panels = data.get("panels")
    if not isinstance(panels, list) or not panels:
        errors.append("manifest 'panels' must be a non-empty array")
        return errors, warnings

    seen_ids: set[str] = set()
    for i, p in enumerate(panels):
        pid = p.get("id")
        if not pid:
            errors.append(f"panels[{i}]: missing 'id'")
            continue
        if pid in seen_ids:
            errors.append(f"panels[{i}]: duplicate panel id {pid!r}")
        seen_ids.add(pid)
        rect = p.get("rect")
        if not (isinstance(rect, list) and len(rect) == 4 and rect[2] > rect[0] and rect[3] > rect[1]):
            errors.append(f"panel {pid}: invalid normalized 'rect' {rect!r}")
        pdir_rel = p.get("dir")
        if not pdir_rel:
            errors.append(f"panel {pid}: missing 'dir'")
        elif manifest_dir is not None:
            pdir = manifest_dir / pdir_rel
            for fname in ("orig.png", "clean.png", "depth16.png"):
                if not (pdir / fname).exists():
                    errors.append(f"panel {pid}: missing required asset {pdir / fname}")
    return errors, warnings


def validate_page_map(
    data: Any,
    timeline: list[dict[str, Any]] | None = None,
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(data, dict):
        return ["page-map.json must be a JSON object"], warnings

    for req in ("timeline", "audio", "prepared_dir", "out", "window", "pages"):
        if req not in data:
            errors.append(f"page-map missing required key: {req!r}")
    pages = data.get("pages")
    if not isinstance(pages, list) or not pages:
        errors.append("page-map 'pages' must be a non-empty array")
        return errors, warnings

    vm, sm = index_timeline(timeline) if timeline is not None else ({}, {})

    def _check_expr(expr: Any, ctx: str, allow_zero: bool = False) -> float | None:
        if isinstance(expr, (int, float)):
            if not (allow_zero and abs(float(expr)) < 1e-9):
                warnings.append(f"{ctx}: hardcoded numeric timestamp {expr}; prefer timeline anchor expressions")
            return float(expr)
        if timeline is not None:
            try:
                return resolve_time(expr, vm, sm)
            except Exception as exc:
                errors.append(f"{ctx}: failed to resolve time expression {expr!r}: {exc}")
                return None
        if not isinstance(expr, dict) or not any(k in expr for k in ("anchor", "max", "min")):
            errors.append(f"{ctx}: malformed time expression {expr!r}")
        return None

    win = data.get("window") or {}
    t_win_start = _check_expr(win.get("start"), "window.start", allow_zero=True)
    t_win_end = _check_expr(win.get("end"), "window.end")
    if t_win_start is not None and t_win_end is not None and t_win_end <= t_win_start:
        errors.append(f"window.end ({t_win_end}) <= window.start ({t_win_start})")

    prev_start: float | None = None
    for idx, pe in enumerate(pages):
        stem = pe.get("page", f"page[{idx}]")
        if "page" not in pe or "start" not in pe:
            errors.append(f"pages[{idx}]: missing 'page' or 'start'")
            continue
        st = _check_expr(pe["start"], f"page {stem}.start", allow_zero=(idx == 0))
        if st is not None:
            if prev_start is not None and st + 1e-4 < prev_start:
                errors.append(f"page {stem}.start ({st}) < previous page start ({prev_start})")
            prev_start = st
        if "end" in pe:
            et = _check_expr(pe["end"], f"page {stem}.end")
            if st is not None and et is not None and et <= st:
                errors.append(f"page {stem}.end ({et}) <= start ({st})")
        for pid, pov in (pe.get("panel_overrides") or {}).items():
            if "start" in pov:
                _check_expr(pov["start"], f"page {stem}:{pid}.start")
            for zi, z in enumerate(pov.get("zones") or []):
                if not zone_has_effective_motion(z):
                    warnings.append(f"page {stem}:{pid}.zones[{zi}]: explicit zero amplitudes (no-op)")

    for bi, b in enumerate(data.get("bursts") or []):
        if "at" in b:
            _check_expr(b["at"], f"bursts[{bi}].at")

    return errors, warnings


def validate_story(
    data: Any,
    extra_renderers: set[str] | None = None,
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(data, dict):
        return ["story.json must be a JSON object"], warnings

    for req in ("timeline", "audio", "prepared_dir", "shots"):
        if req not in data:
            errors.append(f"story missing required key: {req!r}")
    shots = data.get("shots")
    if not isinstance(shots, list) or not shots:
        errors.append("story 'shots' must be a non-empty array")
        return errors, warnings

    allowed_renderers = set(DEFAULT_VALID_RENDERERS) | (extra_renderers or set())
    has_subs = bool(data.get("subtitles"))
    bubble_mode = str(data.get("bubble_mode", "")).strip().lower()
    default_hide = bubble_mode != "cue_sync"
    hide_bub = bool(data.get("hide_bubbles_with_subtitles", default_hide))

    prev_num_start: float | None = None
    for i, sh in enumerate(shots):
        sid = sh.get("shot_id", f"shot_{i}")
        if "page" not in sh or "start" not in sh:
            errors.append(f"{sid}: missing 'page' or 'start'")
            continue
        st_raw, et_raw = sh["start"], sh.get("end")
        if isinstance(st_raw, (int, float)):
            st_f = float(st_raw)
            if prev_num_start is not None and st_f + 1e-4 < prev_num_start:
                errors.append(f"{sid}: non-monotonic start={st_f} < prev={prev_num_start}")
            prev_num_start = st_f
            if isinstance(et_raw, (int, float)) and float(et_raw) <= st_f:
                errors.append(f"{sid}: non-positive duration end={et_raw} <= start={st_f}")

        renderer = str(sh.get("renderer", "fast_25d"))
        if renderer not in allowed_renderers:
            errors.append(f"{sid}: invalid renderer {renderer!r} (allowed: {sorted(allowed_renderers)})")
        fallback = str(sh.get("fallback", "fast_25d"))
        if fallback not in DEFAULT_VALID_FALLBACKS and fallback not in allowed_renderers:
            errors.append(f"{sid}: invalid fallback {fallback!r}")
        if renderer == "video_clip" and not sh.get("clip_path") and fallback != "fast_25d":
            errors.append(f"{sid}: renderer='video_clip' requires 'clip_path' unless fallback='fast_25d'")
        if has_subs and not hide_bub and sh.get("show_bubbles", True) and bubble_mode != "cue_sync":
            warnings.append(f"{sid}: subtitles enabled with show_bubbles=true outside cue_sync mode; may overlap")
        for zi, z in enumerate(sh.get("zones") or []):
            if not zone_has_effective_motion(z):
                warnings.append(f"{sid}: zones[{zi}] ({z.get('driver', 'unknown')}) has zero effective motion")
    return errors, warnings


def validate_qc_report(data: Any) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(data, dict):
        return ["qc_report.json must be a JSON object"], warnings

    if not data.get("ok"):
        errors.append("qc_report.ok is not true")
    if int(data.get("fallback_count", 0)) > 0:
        errors.append(f"fallback_count={data['fallback_count']} (delivery gate requires 0)")
    black_shots = data.get("black_shots") or []
    if black_shots:
        errors.append(f"black_shots detected: {black_shots}")
    noop_zones = data.get("noop_zones") or []
    if noop_zones:
        warnings.append(f"noop_zones reported: {noop_zones}")
    return errors, warnings


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Validate motion-comic layer contracts (stack-agnostic).")
    ap.add_argument("kind", choices=("timeline", "manifest", "page-map", "story", "qc-report"))
    ap.add_argument("path", type=Path, help="Path to the JSON artifact to validate")
    ap.add_argument("--timeline", type=Path, default=None, help="Optional timeline.json for resolving page-map anchors")
    ap.add_argument("--check-files", action="store_true", help="For manifest: verify orig.png/clean.png/depth16.png exist")
    ap.add_argument("--extra-renderers", default="", help="Comma-separated extra renderer names registered by your L2 adapter")
    args = ap.parse_args(argv)

    data = json.loads(args.path.read_text(encoding="utf-8"))
    if args.kind == "timeline":
        errors, warnings = validate_timeline(data)
    elif args.kind == "manifest":
        errors, warnings = validate_manifest(data, manifest_dir=args.path.parent if args.check_files else None)
    elif args.kind == "page-map":
        tl = json.loads(args.timeline.read_text(encoding="utf-8")) if args.timeline else None
        errors, warnings = validate_page_map(data, timeline=tl)
    elif args.kind == "story":
        extra = {s.strip() for s in args.extra_renderers.split(",") if s.strip()}
        errors, warnings = validate_story(data, extra_renderers=extra)
    else:
        errors, warnings = validate_qc_report(data)

    for w in warnings:
        print(f"[WARN] {w}")
    for e in errors:
        print(f"[ERROR] {e}", file=sys.stderr)

    if errors:
        print(f"[FAIL] {args.kind} validation failed ({len(errors)} errors, {len(warnings)} warnings)", file=sys.stderr)
        return 1
    print(f"[OK] {args.kind} validation passed (0 errors, {len(warnings)} warnings)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
