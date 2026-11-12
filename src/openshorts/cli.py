"""openshorts CLI: scan for highlights, or cut them straight into clips."""

from __future__ import annotations

from pathlib import Path

import click

from openshorts.detect import detect_highlights
from openshorts.ffmpeg_utils import SHORTS_MAX_DURATION, cut_clip


def _common_detect_options(f):
    f = click.option("--threshold", default=2.5, show_default=True,
                      help="Std devs above baseline loudness to count as a highlight.")(f)
    f = click.option("--window", "window_s", default=0.5, show_default=True,
                      help="Audio analysis window size, in seconds.")(f)
    f = click.option("--min-gap", "min_gap_s", default=15.0, show_default=True,
                      help="Minimum seconds between two distinct highlights.")(f)
    f = click.option("--lead-in", "lead_in_s", default=5.0, show_default=True,
                      help="Seconds of footage to include before each highlight.")(f)
    f = click.option("--lead-out", "lead_out_s", default=15.0, show_default=True,
                      help="Seconds of footage to include after each highlight.")(f)
    f = click.option("--min-clip-duration", "min_clip_duration_s", default=15.0, show_default=True,
                      help="Floor on clip length -- extends short edge-clamped clips up to this.")(f)
    return f


@click.group()
def main() -> None:
    """OpenShorts: auto-detect highlights in gameplay recordings and cut clips."""


@main.command()
@click.argument("video", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@_common_detect_options
def scan(video: Path, threshold: float, window_s: float, min_gap_s: float,
          lead_in_s: float, lead_out_s: float, min_clip_duration_s: float) -> None:
    """Detect highlights in VIDEO and print them, without cutting anything."""
    highlights = detect_highlights(
        video, window_s=window_s, threshold=threshold, min_gap_s=min_gap_s,
        lead_in_s=lead_in_s, lead_out_s=lead_out_s, min_clip_duration_s=min_clip_duration_s,
    )
    if not highlights:
        click.echo("No highlights found. Try lowering --threshold.")
        return
    for i, h in enumerate(highlights, 1):
        click.echo(
            f"{i:>3}. t={h.time:7.1f}s  score={h.score:5.2f}  "
            f"clip=[{h.clip_start:.1f}s, {h.clip_start + h.clip_duration:.1f}s]"
        )
    click.echo(f"\n{len(highlights)} highlight(s) found.")


@main.command()
@click.argument("video", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--out", "out_dir", type=click.Path(path_type=Path), default=Path("clips"),
              show_default=True, help="Directory to write clips into.")
@click.option("--vertical/--no-vertical", default=True, show_default=True,
              help="Reframe to a 1080x1920 vertical canvas for Shorts/Reels/TikTok.")
@click.option("--max-duration", default=SHORTS_MAX_DURATION, show_default=True,
              help="Hard cap on clip length in seconds, regardless of lead-in/lead-out.")
@_common_detect_options
def clip(video: Path, out_dir: Path, vertical: bool, max_duration: float, threshold: float,
          window_s: float, min_gap_s: float, lead_in_s: float, lead_out_s: float,
          min_clip_duration_s: float) -> None:
    """Detect highlights in VIDEO and cut each one into OUT_DIR."""
    highlights = detect_highlights(
        video, window_s=window_s, threshold=threshold, min_gap_s=min_gap_s,
        lead_in_s=lead_in_s, lead_out_s=lead_out_s, min_clip_duration_s=min_clip_duration_s,
    )
    if not highlights:
        click.echo("No highlights found. Try lowering --threshold.")
        return

    out_dir.mkdir(parents=True, exist_ok=True)
    for i, h in enumerate(highlights, 1):
        out_path = out_dir / f"{video.stem}_clip{i:02d}.mp4"
        click.echo(f"Cutting clip {i}/{len(highlights)} -> {out_path}")
        cut_clip(video, out_path, h.clip_start, h.clip_duration, vertical=vertical, max_duration=max_duration)
    click.echo(f"\nDone. {len(highlights)} clip(s) written to {out_dir}/")


@main.command()
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", default=8788, show_default=True)
def dashboard(host: str, port: int) -> None:
    """Launch the local web dashboard at http://HOST:PORT."""
    from openshorts.dashboard.__main__ import main as run_dashboard

    click.echo(f"OpenShorts dashboard running at http://{host}:{port}")
    run_dashboard(host=host, port=port)


if __name__ == "__main__":
    main()
