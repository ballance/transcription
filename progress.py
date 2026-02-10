"""
Progress tracking for transcription pipeline.

Provides:
- JSON file-based progress for dashboard
- Rich terminal display with spinners
"""
from __future__ import annotations

import json
import os
import threading
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.progress import BarColumn, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

PROGRESS_FILE = Path(__file__).parent / "progress.json"

# Stage definitions with display names and typical duration weights
STAGES = {
    "idle": ("Idle", 0),
    "loading": ("Loading audio", 5),
    "transcribing": ("Transcribing", 70),
    "aligning": ("Aligning words", 10),
    "diarizing": ("Identifying speakers", 15),
    "saving": ("Saving output", 0),
}


@dataclass
class ProgressState:
    """Current progress state for a transcription job."""

    file_name: str = ""
    file_size_mb: float = 0.0
    stage: str = "idle"
    stage_display: str = "Idle"
    started_at: str = ""
    stage_started_at: str = ""
    elapsed_seconds: float = 0.0
    stage_elapsed_seconds: float = 0.0
    stages_completed: list[str] = field(default_factory=list)
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


# Global state
_current_progress = ProgressState()
_progress_lock = threading.Lock()
_console = Console()


def _write_progress_file():
    """Write current progress to JSON file for dashboard."""
    try:
        with open(PROGRESS_FILE, "w") as f:
            json.dump(_current_progress.to_dict(), f, indent=2)
    except Exception:
        pass  # Non-critical, don't fail transcription


def _update_elapsed():
    """Update elapsed time fields."""
    if _current_progress.started_at:
        start = datetime.fromisoformat(_current_progress.started_at)
        _current_progress.elapsed_seconds = (datetime.now() - start).total_seconds()

    if _current_progress.stage_started_at:
        stage_start = datetime.fromisoformat(_current_progress.stage_started_at)
        _current_progress.stage_elapsed_seconds = (datetime.now() - stage_start).total_seconds()


def start_file(file_path: str):
    """Start tracking a new file."""
    with _progress_lock:
        _current_progress.file_name = os.path.basename(file_path)
        try:
            _current_progress.file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
        except OSError:
            _current_progress.file_size_mb = 0.0
        _current_progress.stage = "idle"
        _current_progress.stage_display = "Starting"
        _current_progress.started_at = datetime.now().isoformat()
        _current_progress.stage_started_at = datetime.now().isoformat()
        _current_progress.elapsed_seconds = 0.0
        _current_progress.stage_elapsed_seconds = 0.0
        _current_progress.stages_completed = []
        _current_progress.error = None
        _write_progress_file()


def set_stage(stage: str):
    """Update the current stage."""
    with _progress_lock:
        if _current_progress.stage != "idle" and _current_progress.stage not in _current_progress.stages_completed:
            _current_progress.stages_completed.append(_current_progress.stage)

        _current_progress.stage = stage
        _current_progress.stage_display = STAGES.get(stage, (stage, 0))[0]
        _current_progress.stage_started_at = datetime.now().isoformat()
        _current_progress.stage_elapsed_seconds = 0.0
        _update_elapsed()
        _write_progress_file()


def set_error(error: str):
    """Record an error."""
    with _progress_lock:
        _current_progress.error = error
        _update_elapsed()
        _write_progress_file()


def finish_file():
    """Mark file as complete."""
    with _progress_lock:
        if _current_progress.stage not in _current_progress.stages_completed:
            _current_progress.stages_completed.append(_current_progress.stage)
        _current_progress.stage = "idle"
        _current_progress.stage_display = "Complete"
        _update_elapsed()
        _write_progress_file()


def clear_progress():
    """Clear progress state."""
    with _progress_lock:
        _current_progress.file_name = ""
        _current_progress.stage = "idle"
        _current_progress.stage_display = "Idle"
        _current_progress.started_at = ""
        _current_progress.stage_started_at = ""
        _current_progress.elapsed_seconds = 0.0
        _current_progress.stages_completed = []
        _current_progress.error = None
        _write_progress_file()


def get_progress() -> ProgressState:
    """Get current progress state."""
    with _progress_lock:
        _update_elapsed()
        return ProgressState(**asdict(_current_progress))


def _build_progress_display() -> Panel:
    """Build rich display panel for current progress."""
    with _progress_lock:
        _update_elapsed()
        state = _current_progress

    if not state.file_name:
        return Panel("[dim]Waiting for files...[/dim]", title="Transcription Progress", border_style="dim")

    # Build stage progress table
    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_column("Status", width=3)
    table.add_column("Stage", width=25)
    table.add_column("Time", width=10, justify="right")

    all_stages = ["loading", "transcribing", "aligning", "diarizing", "saving"]

    for stage_key in all_stages:
        stage_name = STAGES[stage_key][0]

        if stage_key in state.stages_completed:
            status = "[green]\u2713[/green]"
            style = "dim"
            time_str = ""
        elif stage_key == state.stage:
            status = "[cyan]\u25cf[/cyan]"
            style = "bold cyan"
            time_str = f"[cyan]{state.stage_elapsed_seconds:.1f}s[/cyan]"
        else:
            status = "[dim]\u25cb[/dim]"
            style = "dim"
            time_str = ""

        table.add_row(status, f"[{style}]{stage_name}[/{style}]", time_str)

    # Header with file info
    header = f"[bold]{state.file_name}[/bold] [dim]({state.file_size_mb:.1f} MB)[/dim]"
    elapsed = f"[yellow]Elapsed: {state.elapsed_seconds:.1f}s[/yellow]"

    content = Table.grid(padding=(0, 2))
    content.add_column()
    content.add_row(header)
    content.add_row("")
    content.add_row(table)
    content.add_row("")
    content.add_row(elapsed)

    if state.error:
        content.add_row(f"[red]Error: {state.error}[/red]")

    return Panel(content, title="Transcription Progress", border_style="cyan")


class ProgressDisplay:
    """Context manager for rich terminal progress display."""

    def __init__(self, refresh_rate: float = 4):
        self._live: Optional[Live] = None
        self._refresh_rate = refresh_rate
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def _update_loop(self):
        """Background thread to update display."""
        while not self._stop_event.is_set():
            if self._live:
                self._live.update(_build_progress_display())
            self._stop_event.wait(1 / self._refresh_rate)

    def start(self):
        """Start the progress display."""
        self._live = Live(
            _build_progress_display(),
            console=_console,
            refresh_per_second=self._refresh_rate,
            transient=False,
        )
        self._live.start()
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._update_loop, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop the progress display."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=1)
        if self._live:
            self._live.stop()
            self._live = None


@contextmanager
def progress_display():
    """Context manager for progress display."""
    display = ProgressDisplay()
    display.start()
    try:
        yield display
    finally:
        display.stop()
