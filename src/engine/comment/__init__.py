"""ai_comment generator factory."""

from __future__ import annotations

import os

from engine.comment.base import CommentGenerator
from engine.comment.template_generator import TemplateCommentGenerator


def get_comment_generator() -> CommentGenerator:
    kind = os.getenv("COMMENT_GENERATOR", "template")
    if kind == "template":
        return TemplateCommentGenerator()
    raise ValueError(f"Unknown COMMENT_GENERATOR: {kind}")

