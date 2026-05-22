"""Gradio playground.

A refined, focused UI: one screen for conversion, one for stats. The handlers
call :class:`DocsiferService` directly (no HTTP loopback), so the browser
talks to FastAPI which talks to the in-process service.
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import shutil
import tempfile
from pathlib import Path
from typing import Any

import gradio as gr
import pandas as pd
from fastapi import FastAPI

from ..analytics import AnalyticsService
from ..config import Settings
from ..core.service import DocsiferService

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Theme & copy
# ---------------------------------------------------------------------------
_THEME = gr.themes.Soft(
    primary_hue=gr.themes.colors.indigo,
    secondary_hue=gr.themes.colors.violet,
    neutral_hue=gr.themes.colors.slate,
    radius_size=gr.themes.sizes.radius_lg,
    font=("Inter", "ui-sans-serif", "system-ui", "sans-serif"),
)

_HERO = """
<div style="text-align:center; padding: 8px 0 24px;">
  <h1 style="margin:0; font-weight:700; letter-spacing:-0.02em;">📚 Docsifer</h1>
  <p style="margin:6px 0 0; opacity:0.8; font-size:1.05rem;">
    Convert documents into clean, LLM-ready Markdown.
  </p>
  <p style="margin:4px 0 0; opacity:0.6; font-size:0.9rem;">
    PDF · Word · PowerPoint · Excel · HTML · Audio · Image · CSV · JSON · ZIP
  </p>
</div>
"""

_FOOTER = """
<div style="text-align:center; opacity:0.55; font-size:0.85rem; padding: 16px 0 4px;">
  Powered by <a href="https://github.com/microsoft/markitdown" target="_blank">MarkItDown</a> ·
  <a href="https://github.com/lh0x00/docsifer" target="_blank">Source</a> ·
  Files are processed in-memory and discarded immediately.
</div>
"""

_CSS = """
.gradio-container { max-width: 1200px !important; margin: auto; }
#convert-btn { font-weight: 600; letter-spacing: 0.01em; }
.markdown-out textarea { font-family: ui-monospace, "JetBrains Mono", Menlo, monospace; font-size: 0.92rem; }
.compact-tabs button.selected { font-weight: 600; }
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _df_from_bucket(bucket: dict[str, dict[str, int]]) -> pd.DataFrame:
    columns = ["Model", "Total", "Daily", "Weekly", "Monthly", "Yearly"]
    rows: list[list[Any]] = []
    models: set[str] = set()
    for period in ("total", "daily", "weekly", "monthly", "yearly"):
        models.update((bucket.get(period) or {}).keys())
    for model in sorted(models):
        rows.append(
            [
                model,
                bucket.get("total", {}).get(model, 0),
                bucket.get("daily", {}).get(model, 0),
                bucket.get("weekly", {}).get(model, 0),
                bucket.get("monthly", {}).get(model, 0),
                bucket.get("yearly", {}).get(model, 0),
            ]
        )
    if not rows:
        rows.append(["docsifer", 0, 0, 0, 0, 0])
    return pd.DataFrame(rows, columns=columns)


def _build_openai_dict(
    base_url: str | None,
    api_key: str | None,
    model: str | None,
) -> dict[str, Any] | None:
    """Only forward the OpenAI config when an API key is provided (Bug A1)."""
    api_key = (api_key or "").strip()
    if not api_key:
        return None
    cfg: dict[str, Any] = {"api_key": api_key}
    if base_url and base_url.strip():
        cfg["base_url"] = base_url.strip()
    if model and model.strip():
        cfg["model"] = model.strip()
    return cfg


def _parse_cookies(raw: str | None) -> dict[str, Any] | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON for HTTP cookies: {exc}") from exc


def _write_markdown_file(text: str, *, tmp_dir: Path, stem: str) -> str:
    safe_stem = "".join(c for c in stem if c.isalnum() or c in "-_") or "document"
    name = f"docsifer-{safe_stem}-{secrets.token_hex(4)}.md"
    dst = tmp_dir / name
    dst.write_text(text, encoding="utf-8")
    return str(dst)


def _status(text: str, *, level: str = "info") -> str:
    palette = {
        "info": "#6366f1",
        "ok": "#16a34a",
        "warn": "#d97706",
        "err": "#dc2626",
    }
    color = palette.get(level, palette["info"])
    return (
        f'<div style="padding:10px 14px;border-radius:10px;'
        f"background:{color}14;color:{color};font-size:0.9rem;"
        f'border:1px solid {color}30;">{text}</div>'
    )


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------
def build_interface(settings: Settings, app: FastAPI) -> gr.Blocks:
    """Construct the Gradio interface bound to the running FastAPI app."""

    def _service() -> DocsiferService:
        return app.state.converter  # type: ignore[no-any-return]

    def _analytics() -> AnalyticsService:
        return app.state.analytics  # type: ignore[no-any-return]

    async def _run_conversion(
        file_path: str | None,
        url_str: str | None,
        base_url: str,
        api_key: str,
        model_id: str,
        cleanup: bool,
        http_cookies: str,
    ) -> tuple[str, str | None, str]:
        if not file_path and not (url_str and url_str.strip()):
            return "", None, _status("Please provide a file or a URL.", level="warn")

        try:
            openai_cfg = _build_openai_dict(base_url, api_key, model_id)
            cookies = _parse_cookies(http_cookies)
            http_cfg = {"cookies": cookies} if cookies else None
        except ValueError as exc:
            return "", None, _status(str(exc), level="err")

        managed_dir = Path(tempfile.mkdtemp(prefix="docsifer-ui-", dir=settings.tmp_dir))
        try:
            if file_path:
                src = Path(file_path)
                staged = managed_dir / src.name
                shutil.copyfile(src, staged)
                source: str | Path = staged
                stem = src.stem
            else:
                source = (url_str or "").strip()
                stem = "url"

            try:
                result = await asyncio.wait_for(
                    _service().convert_file(
                        source,
                        openai_config=openai_cfg,
                        http_config=http_cfg,
                        cleanup_html=bool(cleanup),
                    ),
                    timeout=settings.request_timeout_sec,
                )
            except asyncio.TimeoutError:
                return (
                    "",
                    None,
                    _status(
                        f"Conversion timed out after {settings.request_timeout_sec}s. "
                        "Try a smaller file.",
                        level="err",
                    ),
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("Gradio conversion failed")
                return "", None, _status(f"Conversion failed: {exc}", level="err")

            asyncio.create_task(_record_access(result.token_count))
            md_path = _write_markdown_file(result.markdown, tmp_dir=settings.tmp_dir, stem=stem)
            byte_len = len(result.markdown.encode("utf-8"))
            ok_msg = (
                f"Done — {len(result.markdown):,} chars · "
                f"{byte_len / 1024:.1f} KB · ~{result.token_count:,} tokens"
            )
            return result.markdown, md_path, _status(ok_msg, level="ok")
        finally:
            shutil.rmtree(managed_dir, ignore_errors=True)

    async def _record_access(tokens: int) -> None:
        try:
            await _analytics().access(tokens)
        except Exception:
            logger.exception("Analytics access failed (UI)")

    async def _fetch_stats() -> tuple[pd.DataFrame, pd.DataFrame, str]:
        snap = await _analytics().stats()
        access_df = _df_from_bucket(snap.get("access", {}))
        tokens_df = _df_from_bucket(snap.get("tokens", {}))
        msg = (
            _status("Analytics backend healthy.", level="ok")
            if snap.get("healthy", True)
            else _status("Analytics degraded — using in-memory snapshot.", level="warn")
        )
        return access_df, tokens_df, msg

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------
    with gr.Blocks(
        title="Docsifer — Document to Markdown",
        theme=_THEME,
        css=_CSS,
        analytics_enabled=False,
    ) as demo:
        gr.HTML(_HERO)

        with gr.Tabs(elem_classes=["compact-tabs"]):
            # ---- Convert tab ------------------------------------------------
            with gr.Tab("Convert"):
                with gr.Row(equal_height=False):
                    with gr.Column(scale=5, min_width=320):
                        file_input = gr.File(
                            label="File",
                            file_types=settings.allowed_extensions,
                            type="filepath",
                            file_count="single",
                            height=120,
                        )
                        url_input = gr.Textbox(
                            label="…or a URL",
                            placeholder="https://example.com/article",
                            lines=1,
                        )

                        with gr.Accordion("LLM (optional)", open=False):
                            gr.Markdown(
                                "Provide an OpenAI-compatible key for OCR / "
                                "layout / transcription. Leave blank for basic mode.",
                                elem_classes=["help-text"],
                            )
                            openai_api_key = gr.Textbox(
                                label="API key",
                                placeholder="sk-…",
                                type="password",
                            )
                            with gr.Row():
                                openai_base_url = gr.Textbox(
                                    label="Base URL",
                                    value=settings.default_openai_base_url,
                                    scale=3,
                                )
                                openai_model = gr.Textbox(
                                    label="Model",
                                    value=settings.default_openai_model,
                                    scale=2,
                                )

                        with gr.Accordion("Advanced", open=False):
                            cleanup_toggle = gr.Checkbox(
                                label="Strip script / style / hidden HTML",
                                value=True,
                            )
                            http_cookies = gr.Textbox(
                                label="HTTP cookies (JSON, optional)",
                                placeholder='{"session": "abc..."}',
                                lines=2,
                            )

                        convert_btn = gr.Button(
                            "Convert to Markdown",
                            variant="primary",
                            elem_id="convert-btn",
                            size="lg",
                        )
                        status_box = gr.HTML(value="", visible=True)

                    with gr.Column(scale=7, min_width=380):
                        output_md = gr.Textbox(
                            label="Markdown",
                            lines=24,
                            max_lines=40,
                            interactive=True,
                            show_copy_button=True,
                            elem_classes=["markdown-out"],
                            placeholder="Your converted Markdown will appear here…",
                        )
                        download_file = gr.File(
                            label="Download",
                            interactive=False,
                            height=70,
                        )

                convert_btn.click(
                    fn=_run_conversion,
                    inputs=[
                        file_input,
                        url_input,
                        openai_base_url,
                        openai_api_key,
                        openai_model,
                        cleanup_toggle,
                        http_cookies,
                    ],
                    outputs=[output_md, download_file, status_box],
                    api_name=False,
                    show_progress="full",
                )

            # ---- Stats tab --------------------------------------------------
            with gr.Tab("Stats"):
                gr.Markdown(
                    "Aggregated usage counters (per model and period).",
                )
                stats_status = gr.HTML(value="")
                stats_btn = gr.Button("Refresh", variant="secondary", size="sm")
                with gr.Row():
                    access_df = gr.DataFrame(
                        label="Access count",
                        headers=["Model", "Total", "Daily", "Weekly", "Monthly", "Yearly"],
                        interactive=False,
                        wrap=True,
                    )
                    tokens_df = gr.DataFrame(
                        label="Token usage",
                        headers=["Model", "Total", "Daily", "Weekly", "Monthly", "Yearly"],
                        interactive=False,
                        wrap=True,
                    )
                stats_btn.click(
                    fn=_fetch_stats,
                    inputs=[],
                    outputs=[access_df, tokens_df, stats_status],
                    api_name=False,
                )
                # Also load on first render for a friendlier first impression.
                demo.load(
                    fn=_fetch_stats,
                    inputs=[],
                    outputs=[access_df, tokens_df, stats_status],
                )

        gr.HTML(_FOOTER)

    # Bounded queue so the UI cannot saturate the underlying gate.
    demo.queue(
        max_size=settings.max_queue_depth,
        default_concurrency_limit=settings.max_concurrent_conversions,
        api_open=False,
    )
    return demo
