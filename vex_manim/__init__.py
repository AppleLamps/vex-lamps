from vex_manim.briefs import SceneBrief, build_scene_brief

__all__ = ["SceneBrief", "VexGeneratedScene", "build_scene_brief"]


def __getattr__(name: str):
    if name == "VexGeneratedScene":
        from vex_manim.runtime import VexGeneratedScene

        return VexGeneratedScene
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
