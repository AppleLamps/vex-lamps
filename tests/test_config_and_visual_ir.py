from __future__ import annotations

from google.genai import types

import config
from vex_manim.blueprint import build_scene_blueprints
from vex_manim.briefs import build_scene_brief
from vex_manim.visual_ir import (
    build_storyboard_frames,
    build_visual_explanation_ir,
    critique_storyboard,
)


def test_gemma_config_disables_thinking_and_sdk_afc() -> None:
    tool = types.Tool(function_declarations=[])

    generation_config = config.build_gemini_generation_config(
        "system",
        model_name="gemma-4-31b-it",
        tools=[tool],
    )

    assert generation_config.thinking_config is None
    assert generation_config.automatic_function_calling is not None
    assert generation_config.automatic_function_calling.disable is True


def test_gemini_config_keeps_thinking_disabled_only_for_gemma() -> None:
    generation_config = config.build_gemini_generation_config(
        "system",
        model_name="gemini-2.5-flash",
    )

    assert generation_config.thinking_config is not None
    assert generation_config.thinking_config.thinking_budget == 0


def test_visual_ir_storyboard_uses_semantic_misconception_frame() -> None:
    spec = {
        "visual_id": "visual_smoke",
        "template": "spotlight_compare",
        "renderer_hint": "manim",
        "composition_mode": "replace",
        "headline": "Build First Study Later",
        "deck": "Inverted learning loop",
        "sentence_text": "You do not learn hard things by watching tutorials for ten hours.",
        "context_text": "Pick a small project, get stuck, then study exactly what blocks you.",
        "left_detail": "Tutorial binge",
        "right_detail": "Build then study",
        "supporting_lines": ["Get stuck", "Targeted study", "Build first"],
        "duration": 5.0,
        "importance": 0.82,
        "semantic_frame": {
            "intuition_mode": "misconception_flip",
            "mental_model": "Active building exposes the exact gaps passive watching hides.",
            "viewer_takeaway": "Build first, study the blocker.",
            "before_state": "Tutorial binge",
            "after_state": "Build then study",
            "cause": "Passive watching hides gaps",
            "effect": "Getting stuck reveals the next lesson",
            "story_window": "Tutorials feel productive until a project exposes the missing skill.",
        },
    }
    brief = build_scene_brief(spec, width=1920, height=1080, fps=30, latex_available=False)
    blueprints = build_scene_blueprints(brief, limit=3)

    ir = build_visual_explanation_ir(spec, brief, blueprints[0])
    frames = build_storyboard_frames(ir, brief, blueprints[0])
    critique = critique_storyboard(ir, frames, brief, blueprints[0])

    assert ir.scene_type == "before_after_morph"
    assert ir.misconception == "Tutorial binge"
    assert ir.correct_model == "Build then study"
    assert len(frames) == 3
    assert critique.passed
