from __future__ import annotations

import json
import re
import subprocess
from typing import Any

import config
from broll_intelligence import (
    call_reasoning_model,
    extract_json_array,
    infer_visual_type,
    semantic_keywords,
    truncate,
    window_text,
)

SUPPORTED_TEMPLATES = {
    "metric_callout": "Large value or strong claim with supporting context.",
    "keyword_stack": "Stacked short concepts with strong editorial styling.",
    "timeline_steps": "A short process or sequence laid out step by step.",
    "comparison_split": "Side-by-side contrast between two states.",
    "quote_focus": "A clean emphasis shot for a memorable phrase or line.",
    "system_flow": "A connected flow of stages or ideas.",
    "stat_grid": "A compact dashboard of 2-4 supporting stats or takeaways.",
}

STYLE_PACKS = {
    "editorial_clean": {
        "background": "#09111F",
        "panel_fill": "#12223C",
        "panel_stroke": "#5BC0EB",
        "accent": "#F59E0B",
        "text_primary": "#F8FAFC",
        "text_secondary": "#D6E3F3",
    },
    "bold_tech": {
        "background": "#07131D",
        "panel_fill": "#0D2435",
        "panel_stroke": "#34D399",
        "accent": "#38BDF8",
        "text_primary": "#ECFEFF",
        "text_secondary": "#BAE6FD",
    },
    "documentary_kinetic": {
        "background": "#120B0C",
        "panel_fill": "#24151A",
        "panel_stroke": "#F97316",
        "accent": "#FACC15",
        "text_primary": "#FFF7ED",
        "text_secondary": "#FED7AA",
    },
    "product_ui": {
        "background": "#08101E",
        "panel_fill": "#10223E",
        "panel_stroke": "#818CF8",
        "accent": "#22C55E",
        "text_primary": "#F8FAFC",
        "text_secondary": "#C7D2FE",
    },
    "cinematic_night": {
        "background": "#050816",
        "panel_fill": "#101A34",
        "panel_stroke": "#A78BFA",
        "accent": "#F43F5E",
        "text_primary": "#F8FAFC",
        "text_secondary": "#E9D5FF",
    },
}

STYLE_PACK_HINTS = {
    "data_graphic": "bold_tech",
    "product_ui": "product_ui",
    "process": "editorial_clean",
    "abstract_motion": "cinematic_night",
    "cutaway": "documentary_kinetic",
    "location": "documentary_kinetic",
}

THEME_BY_VISUAL_TYPE = {
    "data_graphic": {
        "panel_stroke": "#38BDF8",
        "accent": "#FACC15",
    },
    "product_ui": {
        "panel_stroke": "#818CF8",
        "accent": "#22C55E",
    },
    "process": {
        "panel_stroke": "#34D399",
        "accent": "#F97316",
    },
    "abstract_motion": {
        "panel_stroke": "#A78BFA",
        "accent": "#F43F5E",
    },
}

RENDERER_HINTS_BY_TYPE = {
    "data_graphic": "manim",
    "product_ui": "ffmpeg",
    "process": "manim",
    "abstract_motion": "blender",
    "cutaway": "ffmpeg",
    "location": "ffmpeg",
}


def detect_scene_cuts(
    input_path: str,
    threshold: float = 0.34,
    min_gap_sec: float = 0.8,
) -> list[float]:
    command = [
        config.FFMPEG_PATH,
        "-i",
        input_path,
        "-filter:v",
        f"select=gt(scene\\,{threshold}),showinfo",
        "-an",
        "-f",
        "null",
        "-",
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        return []
    scene_cuts: list[float] = []
    for line in (result.stderr or "").splitlines():
        match = re.search(r"pts_time:([0-9.]+)", line)
        if not match:
            continue
        pts_time = float(match.group(1))
        if scene_cuts and pts_time - scene_cuts[-1] < min_gap_sec:
            continue
        scene_cuts.append(round(pts_time, 3))
    return scene_cuts


def _count_numbers(text: str) -> int:
    return len(re.findall(r"\b\d+(?:\.\d+)?%?\b", text))


def _card_words(sentence: dict[str, Any], words: list[dict[str, Any]]) -> list[dict[str, Any]]:
    start_index = int(sentence.get("word_start_index") or 0)
    end_index = int(sentence.get("word_end_index") or 0)
    if start_index > 0 and end_index >= start_index:
        return [word for word in words if start_index <= int(word.get("index") or 0) <= end_index]
    start_sec = float(sentence.get("start") or 0.0)
    end_sec = float(sentence.get("end") or start_sec)
    return [
        word
        for word in words
        if float(word.get("end") or 0.0) > start_sec and float(word.get("start") or 0.0) < end_sec
    ]


def _nearest_scene_distance(start_sec: float, end_sec: float, scene_cuts: list[float]) -> tuple[float | None, float]:
    if not scene_cuts:
        return None, 999.0
    anchor = start_sec
    nearest = min(scene_cuts, key=lambda cut: min(abs(cut - start_sec), abs(cut - end_sec)))
    return nearest, min(abs(nearest - anchor), abs(nearest - end_sec))


def _replace_safety(
    *,
    pause_before: float,
    pause_after: float,
    scene_distance: float,
    words_per_second: float,
    visual_type_hint: str,
) -> float:
    score = 0.22
    score += min(pause_before, 0.6) * 0.38
    score += min(pause_after, 0.6) * 0.46
    if scene_distance <= 0.35:
        score += 0.18
    if scene_distance <= 0.18:
        score += 0.06
    if words_per_second <= 2.0:
        score += 0.1
    if visual_type_hint in {"abstract_motion", "cutaway", "location"}:
        score += 0.08
    if visual_type_hint in {"data_graphic", "product_ui"}:
        score -= 0.06
    return round(max(0.0, min(score, 1.0)), 3)


def _default_style_pack(visual_type_hint: str) -> str:
    return STYLE_PACK_HINTS.get(visual_type_hint, "editorial_clean")


def _theme_for_card(card: dict[str, Any], style_pack: str) -> dict[str, str]:
    theme = dict(STYLE_PACKS.get(style_pack, STYLE_PACKS["editorial_clean"]))
    theme.update(THEME_BY_VISUAL_TYPE.get(str(card.get("visual_type_hint") or ""), {}))
    return theme


def _default_template(card: dict[str, Any]) -> str:
    visual_type = str(card.get("visual_type_hint") or "")
    numbers = int(card.get("numeric_hits") or 0)
    if visual_type == "data_graphic":
        return "stat_grid" if numbers >= 2 else "metric_callout"
    if visual_type == "process":
        return "system_flow" if len(card.get("keywords") or []) >= 3 else "timeline_steps"
    if visual_type == "product_ui":
        return "comparison_split"
    if visual_type == "abstract_motion":
        return "keyword_stack"
    return "quote_focus" if numbers == 0 else "metric_callout"


def _default_renderer_hint(card: dict[str, Any]) -> str:
    visual_type = str(card.get("visual_type_hint") or "")
    if visual_type in RENDERER_HINTS_BY_TYPE:
        return RENDERER_HINTS_BY_TYPE[visual_type]
    return "ffmpeg"


def _default_motion_preset(card: dict[str, Any], template: str) -> str:
    visual_type = str(card.get("visual_type_hint") or "")
    if template in {"timeline_steps", "system_flow"}:
        return "diagram_draw"
    if template in {"metric_callout", "stat_grid"}:
        return "kinetic_pop"
    if visual_type == "abstract_motion":
        return "spotlight_sweep"
    return "gentle_rise"


def _format_renderer_capabilities(capabilities: list[dict[str, Any]] | None) -> str:
    if not capabilities:
        return "No renderer metadata was provided."
    lines: list[str] = []
    for item in capabilities:
        name = str(item.get("name") or "unknown")
        available = bool(item.get("available"))
        templates = ", ".join(item.get("supported_templates") or [])
        reason = str(item.get("reason") or "")
        suffix = f" unavailable: {reason}" if not available and reason else ""
        lines.append(f"- {name} | available={available} | templates={templates}{suffix}")
    return "\n".join(lines)


def _visual_priority(card: dict[str, Any]) -> float:
    combined = f"{card['sentence_text']} {card['context_text']}".lower()
    tokens = re.findall(r"[a-zA-Z0-9']+", combined)
    if not tokens:
        return 0.0
    numbers = int(card.get("numeric_hits") or 0)
    specificity = min(len(set(tokens)) / max(len(tokens), 1), 1.0)
    visual_hits = len(card.get("keywords") or [])
    proper_nouns = len(re.findall(r"\b[A-Z][a-zA-Z0-9]+\b", f"{card['sentence_text']} {card['context_text']}"))
    cut_bonus = max(0.0, 1.0 - min(float(card.get("scene_distance") or 999.0), 1.0))
    replace_bonus = float(card.get("replace_safety") or 0.0)
    pause_bonus = min(float(card.get("pause_after") or 0.0), 0.6) * 9.0
    return round(
        24
        + numbers * 8.5
        + specificity * 20
        + min(visual_hits, 8) * 3.2
        + proper_nouns * 2.3
        + cut_bonus * 11
        + replace_bonus * 14
        + pause_bonus,
        2,
    )


def build_visual_context_cards(
    sentences: list[dict[str, Any]],
    transcript_segments: list[dict[str, Any]],
    clip_duration: float,
    *,
    words: list[dict[str, Any]] | None = None,
    scene_cuts: list[float] | None = None,
) -> list[dict[str, Any]]:
    words = words or []
    scene_cuts = scene_cuts or []
    cards: list[dict[str, Any]] = []
    total_sentences = len(sentences)
    for index, sentence in enumerate(sentences, start=1):
        start_sec = max(0.0, min(float(sentence.get("start") or 0.0), clip_duration))
        end_sec = max(start_sec + 0.12, min(float(sentence.get("end") or start_sec + 0.8), clip_duration))
        sentence_text = truncate(str(sentence.get("text") or ""), 220)
        if not sentence_text:
            continue
        context_text = truncate(
            window_text(
                transcript_segments,
                max(0.0, start_sec - 3.0),
                min(clip_duration, end_sec + 3.0),
            ),
            320,
        )
        card_words = _card_words(sentence, words)
        pause_before = 0.0
        pause_after = 0.0
        if index > 1:
            prev = sentences[index - 2]
            pause_before = max(0.0, start_sec - float(prev.get("end") or start_sec))
        if index < total_sentences:
            nxt = sentences[index]
            pause_after = max(0.0, float(nxt.get("start") or end_sec) - end_sec)
        word_count = len(card_words)
        words_per_second = round(word_count / max(end_sec - start_sec, 0.15), 2) if word_count else 0.0
        keywords = semantic_keywords(f"{sentence_text} {context_text}", limit=8)
        visual_type_hint = infer_visual_type(f"{sentence_text} {context_text}")
        nearest_scene_cut, scene_distance = _nearest_scene_distance(start_sec, end_sec, scene_cuts)
        numeric_hits = _count_numbers(f"{sentence_text} {context_text}")
        replace_safety = _replace_safety(
            pause_before=pause_before,
            pause_after=pause_after,
            scene_distance=scene_distance,
            words_per_second=words_per_second,
            visual_type_hint=visual_type_hint,
        )
        suggested_composition = (
            "replace"
            if replace_safety >= 0.63 and visual_type_hint not in {"data_graphic", "product_ui"}
            else "picture_in_picture"
        )
        style_pack = _default_style_pack(visual_type_hint)
        row = {
            "card_id": f"visual_card_{index:03d}",
            "start": round(start_sec, 2),
            "end": round(end_sec, 2),
            "sentence_text": sentence_text,
            "context_text": context_text,
            "keywords": keywords,
            "visual_type_hint": visual_type_hint,
            "word_count": word_count,
            "words_per_second": words_per_second,
            "pause_before": round(pause_before, 3),
            "pause_after": round(pause_after, 3),
            "nearest_scene_cut": round(nearest_scene_cut, 3) if nearest_scene_cut is not None else None,
            "scene_distance": round(scene_distance, 3),
            "numeric_hits": numeric_hits,
            "replace_safety": replace_safety,
            "suggested_composition": suggested_composition,
            "style_pack": style_pack,
            "suggested_renderer": _default_renderer_hint({"visual_type_hint": visual_type_hint}),
        }
        row["priority"] = _visual_priority(row)
        cards.append(row)
    return cards


def _format_cards_for_llm(cards: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for card in cards:
        lines.append(
            "\n".join(
                [
                    f"{card['card_id']} | {card['start']:.2f}-{card['end']:.2f} | priority={card['priority']:.2f}",
                    f"Sentence: {card['sentence_text']}",
                    f"Context: {card['context_text']}",
                    f"Keywords: {', '.join(card['keywords'])}",
                    f"Hint: {card['visual_type_hint']} | renderer={card['suggested_renderer']} | style={card['style_pack']}",
                    (
                        "Evidence: "
                        f"numbers={card['numeric_hits']} | "
                        f"wps={card['words_per_second']:.2f} | "
                        f"pause_before={card['pause_before']:.2f}s | "
                        f"pause_after={card['pause_after']:.2f}s | "
                        f"scene_distance={card['scene_distance']:.2f}s | "
                        f"replace_safety={card['replace_safety']:.2f}"
                    ),
                ]
            )
        )
    return "\n\n".join(lines)


def _snap_to_scene(
    value: float,
    scene_cuts: list[float],
    max_distance: float = 0.4,
    *,
    direction: str = "nearest",
) -> float:
    if not scene_cuts:
        return value
    if direction == "forward":
        forward = [cut for cut in scene_cuts if cut >= value]
        if forward:
            nearest = min(forward, key=lambda cut: abs(cut - value))
        else:
            nearest = min(scene_cuts, key=lambda cut: abs(cut - value))
    elif direction == "backward":
        backward = [cut for cut in scene_cuts if cut <= value]
        if backward:
            nearest = min(backward, key=lambda cut: abs(cut - value))
        else:
            nearest = min(scene_cuts, key=lambda cut: abs(cut - value))
    else:
        nearest = min(scene_cuts, key=lambda cut: abs(cut - value))
    if abs(nearest - value) <= max_distance:
        return nearest
    return value


def _extract_emphasis_text(card: dict[str, Any]) -> str:
    text = str(card.get("sentence_text") or "")
    number_match = re.search(r"\b\d+(?:\.\d+)?%?\b", text)
    if number_match:
        return number_match.group(0)
    keywords = list(card.get("keywords") or [])
    if keywords:
        return " ".join(keywords[:3])
    return truncate(text, 32)


def _coerce_string_list(raw: Any, limit: int, max_chars: int) -> list[str]:
    if isinstance(raw, list):
        values = [truncate(str(item), max_chars) for item in raw if str(item).strip()]
    elif str(raw or "").strip():
        values = [truncate(str(raw), max_chars)]
    else:
        values = []
    return values[:limit]


def _normalize_visual_plan(
    raw_plan: list[dict[str, Any]],
    cards: list[dict[str, Any]],
    clip_duration: float,
    max_visuals: int,
    min_visual_sec: float,
    max_visual_sec: float,
    scene_cuts: list[float],
    available_renderers: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    card_map = {card["card_id"]: card for card in cards}
    known_renderers = {str(item.get("name") or "").strip().lower() for item in (available_renderers or [])}
    available_names = {
        str(item.get("name") or "").strip().lower()
        for item in (available_renderers or [])
        if bool(item.get("available"))
    }
    normalized: list[dict[str, Any]] = []
    last_end = -999.0
    for index, item in enumerate(raw_plan, start=1):
        card = card_map.get(str(item.get("card_id") or "").strip())
        if card is None:
            continue
        start_sec = max(0.0, min(float(card["start"]) - 0.08, clip_duration))
        end_sec = min(clip_duration, float(card["end"]) + 0.22)
        start_sec = _snap_to_scene(start_sec, scene_cuts, direction="forward")
        end_sec = _snap_to_scene(end_sec, scene_cuts, direction="backward")
        if end_sec - start_sec < min_visual_sec:
            end_sec = min(clip_duration, start_sec + min_visual_sec)
        if end_sec - start_sec > max_visual_sec:
            end_sec = start_sec + max_visual_sec
        if end_sec <= start_sec or start_sec - last_end < 0.18:
            continue
        confidence = max(0.0, min(float(item.get("confidence", 0.58)), 1.0))
        if confidence < 0.35:
            continue
        template = str(item.get("template") or _default_template(card)).strip().lower()
        if template not in SUPPORTED_TEMPLATES:
            template = _default_template(card)
        composition_mode = str(item.get("composition_mode") or card["suggested_composition"]).strip().lower()
        if composition_mode in {"pip", "overlay", "picture-in-picture"}:
            composition_mode = "picture_in_picture"
        if composition_mode not in {"replace", "picture_in_picture"}:
            composition_mode = card["suggested_composition"]
        position = str(item.get("position") or "bottom_right").strip().lower()
        if position not in {"top_left", "top_right", "bottom_left", "bottom_right", "top", "bottom", "center"}:
            position = "bottom_right"
        scale = round(max(0.24, min(float(item.get("scale", 0.42) or 0.42), 0.8)), 3)
        supporting_lines = _coerce_string_list(item.get("supporting_lines"), limit=3, max_chars=72)
        keywords = _coerce_string_list(item.get("keywords"), limit=4, max_chars=28)
        steps = _coerce_string_list(item.get("steps"), limit=4, max_chars=28)
        headline = truncate(str(item.get("headline") or card["sentence_text"]), 72)
        emphasis_text = truncate(str(item.get("emphasis_text") or _extract_emphasis_text(card)), 48)
        footer_text = truncate(str(item.get("footer_text") or card["context_text"]), 84)
        style_pack = str(item.get("style_pack") or card["style_pack"] or "editorial_clean").strip().lower()
        if style_pack not in STYLE_PACKS:
            style_pack = card["style_pack"]
        renderer_hint = str(item.get("renderer_hint") or card["suggested_renderer"] or "auto").strip().lower()
        if renderer_hint in known_renderers and renderer_hint not in available_names:
            renderer_hint = "auto"
        if renderer_hint not in known_renderers and renderer_hint != "auto":
            renderer_hint = card["suggested_renderer"]
        motion_preset = truncate(
            str(item.get("motion_preset") or _default_motion_preset(card, template)),
            32,
        )
        spec = {
            "visual_id": f"visual_{index:03d}",
            "card_id": card["card_id"],
            "start": round(start_sec, 2),
            "end": round(end_sec, 2),
            "duration": round(end_sec - start_sec, 2),
            "sentence_text": card["sentence_text"],
            "context_text": card["context_text"],
            "keywords": card["keywords"][:8],
            "visual_type_hint": card["visual_type_hint"],
            "template": template,
            "composition_mode": composition_mode,
            "position": position,
            "scale": scale,
            "headline": headline,
            "emphasis_text": emphasis_text,
            "supporting_lines": supporting_lines,
            "steps": steps,
            "quote_text": truncate(str(item.get("quote_text") or headline), 120),
            "left_label": truncate(str(item.get("left_label") or "Before"), 28),
            "right_label": truncate(str(item.get("right_label") or "After"), 28),
            "left_detail": truncate(str(item.get("left_detail") or card["sentence_text"]), 72),
            "right_detail": truncate(str(item.get("right_detail") or card["context_text"]), 72),
            "footer_text": footer_text,
            "style_pack": style_pack,
            "theme": _theme_for_card(card, style_pack),
            "renderer_hint": renderer_hint,
            "motion_preset": motion_preset,
            "rationale": truncate(str(item.get("rationale") or "Generated visual aligned to the active spoken beat."), 160),
            "confidence": round(confidence, 2),
            "importance": round(min(max(card["priority"] / 92.0, 0.25), 1.0), 2),
            "evidence": {
                "pause_before": card["pause_before"],
                "pause_after": card["pause_after"],
                "scene_distance": card["scene_distance"],
                "replace_safety": card["replace_safety"],
                "word_count": card["word_count"],
                "words_per_second": card["words_per_second"],
                "numeric_hits": card["numeric_hits"],
            },
        }
        if template == "keyword_stack" and not keywords:
            spec["keywords"] = card["keywords"][:4] or [headline]
        if template in {"timeline_steps", "system_flow"} and not steps:
            spec["steps"] = (
                [headline, emphasis_text, footer_text[:28]]
                if footer_text
                else [headline, emphasis_text]
            )[:4]
        if template in {"metric_callout", "stat_grid"} and not supporting_lines:
            spec["supporting_lines"] = [truncate(card["sentence_text"], 72), truncate(card["context_text"], 72)]
        normalized.append(spec)
        last_end = end_sec
        if len(normalized) >= max_visuals:
            break
    return normalized


def _candidate_pool(cards: list[dict[str, Any]], max_visuals: int) -> list[dict[str, Any]]:
    ranked = sorted(cards, key=lambda item: (item["priority"], -item["start"]), reverse=True)
    pool: list[dict[str, Any]] = []
    for card in ranked:
        if any(abs(card["start"] - existing["start"]) < 0.6 for existing in pool):
            continue
        pool.append(card)
        if len(pool) >= max(max_visuals * 4, 12):
            break
    return pool


def fallback_visual_plan(
    cards: list[dict[str, Any]],
    clip_duration: float,
    max_visuals: int,
    min_visual_sec: float,
    max_visual_sec: float,
    scene_cuts: list[float],
    available_renderers: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    ranked = _candidate_pool(cards, max_visuals)
    fallback = []
    for card in ranked:
        template = _default_template(card)
        fallback.append(
            {
                "card_id": card["card_id"],
                "template": template,
                "renderer_hint": card["suggested_renderer"],
                "style_pack": card["style_pack"],
                "composition_mode": card["suggested_composition"],
                "headline": truncate(card["sentence_text"], 68),
                "emphasis_text": _extract_emphasis_text(card),
                "supporting_lines": [truncate(card["context_text"], 72)],
                "keywords": card["keywords"][:4],
                "steps": [truncate(term, 24) for term in card["keywords"][:3]],
                "quote_text": truncate(card["sentence_text"], 120),
                "footer_text": truncate(card["context_text"], 84),
                "left_label": "Before",
                "right_label": "After",
                "left_detail": truncate(card["sentence_text"], 72),
                "right_detail": truncate(card["context_text"], 72),
                "position": "bottom_right",
                "scale": 0.42,
                "motion_preset": _default_motion_preset(card, template),
                "rationale": "Fallback visual chosen from the strongest transcript beat when the model plan was unavailable.",
                "confidence": round(min(max(card["priority"] / 88.0, 0.45), 0.9), 2),
            }
        )
        if len(fallback) >= max_visuals:
            break
    return _normalize_visual_plan(
        fallback,
        cards,
        clip_duration,
        max_visuals,
        min_visual_sec,
        max_visual_sec,
        scene_cuts,
        available_renderers,
    )


def analyze_visual_plan_with_llm(
    provider_name: str,
    model_name: str,
    cards: list[dict[str, Any]],
    clip_duration: float,
    max_visuals: int,
    min_visual_sec: float,
    max_visual_sec: float,
    scene_cuts: list[float],
    *,
    available_renderers: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    fallback = fallback_visual_plan(
        cards,
        clip_duration,
        max_visuals,
        min_visual_sec,
        max_visual_sec,
        scene_cuts,
        available_renderers,
    )
    if not cards:
        return fallback

    candidate_cards = _candidate_pool(cards, max_visuals)
    template_lines = "\n".join(f"- {name}: {description}" for name, description in SUPPORTED_TEMPLATES.items())
    renderer_lines = _format_renderer_capabilities(available_renderers)
    system_prompt = (
        "You are a senior motion graphics director planning precise generated visuals for an explainer video. "
        "Choose only transcript beats where a custom animation would make the spoken idea clearer. "
        "Prefer concise, literal, high-signal visuals with strong editorial taste. "
        "Use the evidence fields to decide when a full-screen replacement is safe versus when picture-in-picture is safer. "
        "Return ONLY a JSON array with at most {count} objects using these keys: "
        "card_id, template, renderer_hint, style_pack, composition_mode, headline, emphasis_text, supporting_lines, "
        "steps, keywords, quote_text, left_label, right_label, left_detail, right_detail, footer_text, position, scale, "
        "motion_preset, rationale, confidence."
    ).format(count=max_visuals)
    user_prompt = (
        f"Video duration: {clip_duration:.2f}s\n"
        f"Max visuals: {max_visuals}\n"
        f"Duration per visual: {min_visual_sec:.1f}s to {max_visual_sec:.1f}s\n"
        f"Detected scene cuts: {scene_cuts[:24]}\n\n"
        f"Supported templates:\n{template_lines}\n\n"
        "Available renderers:\n"
        f"{renderer_lines}\n\n"
        "Composition modes:\n"
        "- replace: full-screen generated cutaway\n"
        "- picture_in_picture: keep the source visible and place the visual in a corner\n\n"
        "Style packs:\n"
        "- editorial_clean\n- bold_tech\n- documentary_kinetic\n- product_ui\n- cinematic_night\n\n"
        f"Candidate transcript cards:\n{truncate(_format_cards_for_llm(candidate_cards), 8200)}\n\n"
        "Pick the strongest beats only. Avoid generic filler. "
        "Favor stat_grid or metric_callout for quantitative beats. "
        "Favor timeline_steps or system_flow for processes. "
        "Favor comparison_split for contrasts. "
        "Favor quote_focus or keyword_stack for abstract ideas. "
        "Prefer ffmpeg for simple clean editorial cards, manim for diagrams and process visuals, and blender for cinematic replacement shots when available. "
        "Return JSON array only."
    )
    try:
        director_raw = call_reasoning_model(provider_name, model_name, system_prompt, user_prompt)
        director_plan = json.loads(extract_json_array(director_raw))
    except Exception:
        return fallback
    normalized_director = _normalize_visual_plan(
        director_plan,
        cards,
        clip_duration,
        max_visuals,
        min_visual_sec,
        max_visual_sec,
        scene_cuts,
        available_renderers,
    )
    if not normalized_director:
        return fallback

    critic_system_prompt = (
        "You are a strict motion-design critic and QA lead. "
        "Your job is to reject generic, weak, repetitive, or mistimed visuals and return a tighter plan. "
        "Preserve only high-signal visuals, keep them concise, and fix backend/style/template choices when needed. "
        "Return ONLY a JSON array with the same schema as the director."
    )
    critic_user_prompt = (
        "Renderer capabilities:\n"
        f"{renderer_lines}\n\n"
        "Original candidate cards:\n"
        f"{truncate(_format_cards_for_llm(candidate_cards), 6200)}\n\n"
        "Director plan to critique:\n"
        f"{json.dumps(normalized_director, indent=2)}\n\n"
        "Remove generic filler, reduce repetition, and make sure replacement shots only happen when the evidence looks safe. "
        "Return JSON array only."
    )
    try:
        critic_raw = call_reasoning_model(provider_name, model_name, critic_system_prompt, critic_user_prompt)
        critic_plan = json.loads(extract_json_array(critic_raw))
        normalized_critic = _normalize_visual_plan(
            critic_plan,
            cards,
            clip_duration,
            max_visuals,
            min_visual_sec,
            max_visual_sec,
            scene_cuts,
            available_renderers,
        )
        return normalized_critic or normalized_director or fallback
    except Exception:
        return normalized_director or fallback
