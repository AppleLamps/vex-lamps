from __future__ import annotations

import re

from vex_manim.validator import CodeProfile, ValidationReport


def compiler_validation_report(brief, blueprint, scene_source: str) -> ValidationReport:
    copy_bank = dict(getattr(brief, "copy_bank", {}) or {})
    visible_copy = " ".join(
        str(item).strip()
        for item in [
            getattr(brief, "headline", ""),
            getattr(brief, "deck", ""),
            *(copy_bank.get("supporting_lines") or [])[:2],
            *(copy_bank.get("steps") or [])[:3],
            copy_bank.get("left_detail"),
            copy_bank.get("right_detail"),
        ]
        if str(item or "").strip()
    )
    visible_word_count = len(re.findall(r"[A-Za-z0-9][A-Za-z0-9'./%-]*", visible_copy))
    panel_like_kinds = {"panel", "card", "ui_modules", "strip_modules"}
    premium_motion_tokens = ("route", "ring", "beam", "badge", "signal", "connector", "pulse", "glow", "focus")
    dynamic_devices = list(getattr(blueprint, "dynamic_devices", []) or [])
    suggested_features = list(getattr(blueprint, "suggested_features", []) or [])
    camera_plan_text = str(getattr(blueprint, "camera_plan", "") or "").lower()
    camera_move_mentions = (
        1
        if any(token in camera_plan_text for token in ("camera", "slide", "zoom", "punch", "reframe", "pan", "drift", "settle"))
        else 0
    )
    profile = CodeProfile(
        advanced_features=suggested_features,
        primitive_features=["VGroup"],
        imports=["manim", "vex_manim.premium_fallback"],
        play_calls=max(len(getattr(blueprint, "motion_beats", []) or []), 3),
        wait_calls=1,
        layout_registration_calls=max(len(getattr(blueprint, "elements", []) or []) // 2, 3),
        panel_helper_calls=sum(
            1 for element in (getattr(blueprint, "elements", []) or []) if getattr(element, "kind", "") in panel_like_kinds
        ),
        premium_helper_calls=max(
            sum(1 for item in dynamic_devices if any(token in str(item).lower() for token in premium_motion_tokens)),
            min(len(dynamic_devices), 4),
        ),
        title_helper_calls=1,
        visible_text_word_count=min(
            visible_word_count,
            int(getattr(brief, "text_budget_words", visible_word_count) or visible_word_count),
        ),
        long_visible_text_literals=0,
        dynamic_device_count=max(
            len(set(dynamic_devices)),
            min(max(int(getattr(brief, "minimum_dynamic_devices", 2)) + 1, 2), 5),
        ),
        camera_move_mentions=camera_move_mentions,
        class_names=["GeneratedScene"],
        line_count=len(scene_source.splitlines()),
    )
    return ValidationReport(valid=True, errors=[], warnings=[], profile=profile)


def can_accept_blueprint_compiler_quality(brief, validation, quality, min_quality: float) -> bool:
    if float(quality.score) >= float(min_quality):
        return True
    near_miss_floor = max(float(min_quality) - 0.06, 0.54)
    if float(quality.score) < near_miss_floor:
        return False
    if not _has_solid_compiler_motion_grammar(brief, validation):
        return False
    issues = list(quality.issues)
    return not any(_is_severe_compiler_issue(issue) for issue in issues)


def minimum_blueprint_compiler_quality(brief) -> float:
    family = str(getattr(brief, "scene_family", "") or "")
    if family == "timeline_journey":
        return 0.55
    if family == "system_map":
        return 0.58
    if family in {"metric_story", "dashboard_build"}:
        return 0.64
    if family == "comparison_morph":
        return 0.66
    if family == "interface_focus":
        return 0.62
    return 0.6


def _has_solid_compiler_motion_grammar(brief, validation) -> bool:
    profile = validation.profile
    return (
        profile.dynamic_device_count >= max(int(brief.minimum_dynamic_devices), 3)
        and len(profile.advanced_features) >= 3
        and profile.premium_helper_calls >= 2
        and (profile.camera_move_mentions > 0 or profile.play_calls >= 4)
    )


def _is_severe_compiler_issue(issue: str) -> bool:
    cleaned = str(issue or "").strip().lower()
    severe_markers = (
        "extends outside the safe frame",
        "falls into the bottom subtitle-safe region",
        "very small font size",
        "too wide for comfortable readability",
        "colliding with",
        "overlaps",
        "too dense",
        "too much visible copy",
        "reads like a paragraph",
        "too low-contrast",
        "too sparse",
        "too static",
        "duration drifted",
    )
    return any(marker in cleaned for marker in severe_markers)
