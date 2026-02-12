#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import json
import os
import random
import re
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Literal, Tuple
from urllib.parse import urlparse, urlunparse

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Input, ListItem, ListView, Static

AUDIO_EXTS = {".mp3", ".m4a", ".opus", ".webm", ".flac", ".wav", ".ogg", ".aac"}
MAX_SHOW = 400

BANNER = r"""\
 █████╗ ███╗   ██╗████████╗██╗  ██╗ ██████╗ ███╗   ██╗██╗   ██╗
██╔══██╗████╗  ██║╚══██╔══╝██║  ██║██╔═══██╗████╗  ██║╚██╗ ██╔╝
███████║██╔██╗ ██║   ██║   ███████║██║   ██║██╔██╗ ██║ ╚████╔╝
██╔══██║██║╚██╗██║   ██║   ██╔══██║██║   ██║██║╚██╗██║  ╚██╔╝
██║  ██║██║ ╚████║   ██║   ██║  ██║╚██████╔╝██║ ╚████║   ██║
╚═╝  ╚═╝╚═╝  ╚═══╝   ╚═╝   ╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═══╝   ╚═╝

███████╗███╗   ███╗
██╔════╝████╗ ████║
█████╗  ██╔████╔██║
██╔══╝  ██║╚██╔╝██║
██║     ██║ ╚═╝ ██║
╚═╝     ╚═╝     ╚═╝

  Enter: play   Space: pause/resume   n: next   p: previous   s: stop   r: rescan   +: add   -: remove
  x: shuffle   d: download (mp3)   c: cancel dl   q: quit
"""

TUX_ASCII = r"""\
       .--.
      |o_o |
      |:_/ |
     //   \ \
    (|     | )
   /'\_   _/`\
   \___)=(___/
"""


def normalize_for_search(s: str) -> str:
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())


def squash_spaces(s: str) -> str:
    return s.replace(" ", "")


def fmt_mmss(seconds: Optional[float]) -> str:
    if seconds is None or seconds <= 0:
        return "??:??"
    s = int(seconds + 0.5)
    m, s = divmod(s, 60)
    return f"{m:02d}:{s:02d}"


def clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


def get_duration_seconds(path: Path) -> Optional[float]:
    if not shutil.which("ffprobe"):
        return None
    try:
        out = subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=nw=1:nk=1",
                str(path),
            ],
            stderr=subprocess.DEVNULL,
            timeout=2,
        ).decode("utf-8", "ignore").strip()
        return float(out) if out else None
    except Exception:
        return None


def normalize_youtube_url(url: str) -> str:
    try:
        u = url.strip()
        p = urlparse(u)
        if not p.scheme:
            p = urlparse("https://" + u)
        netloc = p.netloc.lower()
        if netloc == "music.youtube.com":
            netloc = "www.youtube.com"
        return urlunparse(p._replace(netloc=netloc))
    except Exception:
        return url.strip()


def safe_filename(name: str, max_len: int = 140) -> str:
    name = re.sub(r"[\\/:*?\"<>|]+", "_", name).strip()
    name = re.sub(r"\s+", " ", name).strip()
    if not name:
        name = "track"
    if len(name) > max_len:
        name = name[: max_len - 1] + "…"
    return name


SourceType = Literal["local", "youtube"]


@dataclass(frozen=True)
class Track:
    source: SourceType
    uri: str  # local path or watch URL
    label: str
    norm_name: str
    norm_parent: str
    squashed_name: str
    squashed_parent: str

    @staticmethod
    def from_path(p: Path) -> "Track":
        name = p.name
        parent = str(p.parent)
        try:
            rel_parent = str(p.parent.relative_to(Path.cwd()))
        except Exception:
            rel_parent = parent
        label = f"{name}  [dim]({rel_parent})[/dim]"
        nn = normalize_for_search(name)
        np = normalize_for_search(parent)
        return Track(
            source="local",
            uri=str(p),
            label=label,
            norm_name=nn,
            norm_parent=np,
            squashed_name=squash_spaces(nn),
            squashed_parent=squash_spaces(np),
        )

    @staticmethod
    def from_youtube(title: str, watch_url: str, playlist_title: str = "YouTube") -> "Track":
        watch_url = normalize_youtube_url(watch_url)
        label = f"{title}  [dim]({playlist_title})[/dim]"
        nn = normalize_for_search(title)
        np = normalize_for_search(playlist_title)
        return Track(
            source="youtube",
            uri=watch_url,
            label=label,
            norm_name=nn,
            norm_parent=np,
            squashed_name=squash_spaces(nn),
            squashed_parent=squash_spaces(np),
        )


def scan_tracks_recursive(root: Path) -> List[Track]:
    """
    Recursive scan that tolerates permission errors and avoids crashing on weird filesystem entries.
    Uses os.walk for robustness.
    """
    tracks: List[Track] = []
    root = root.resolve()

    for dirpath, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        # prune common heavy dirs if you want (leave empty to scan everything)
        # Example: skip .git / node_modules if you like
        # dirnames[:] = [d for d in dirnames if d not in {".git", "node_modules"}]

        for fn in filenames:
            try:
                p = Path(dirpath) / fn
                if p.suffix.lower() in AUDIO_EXTS and p.is_file():
                    tracks.append(Track.from_path(p))
            except Exception:
                continue

    tracks.sort(key=lambda t: (str(Path(t.uri).parent).lower(), Path(t.uri).name.lower()))
    return tracks


def find_player() -> Optional[Tuple[str, List[str]]]:
    if shutil.which("mpv"):
        return ("mpv", ["mpv", "--no-video", "--quiet", "--audio-display=no"])
    if shutil.which("ffplay"):
        return ("ffplay", ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"])
    return None


def fetch_youtube_playlist_tracks(url: str, timeout_s: int = 25) -> List[Track]:
    if not shutil.which("yt-dlp"):
        raise RuntimeError("yt-dlp not found. Install it to load YouTube playlists.")
    url = normalize_youtube_url(url)
    cmd = ["yt-dlp", "--flat-playlist", "-J", "--no-warnings", url]
    raw = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, timeout=timeout_s)
    data = json.loads(raw.decode("utf-8", "ignore"))

    playlist_title = data.get("title") or "YouTube"
    entries = data.get("entries") or []

    def to_watch_url(entry: dict) -> Optional[str]:
        w = entry.get("webpage_url")
        if isinstance(w, str) and w.strip():
            return normalize_youtube_url(w.strip())

        u = entry.get("url") or entry.get("id")
        if not isinstance(u, str) or not u.strip():
            return None
        u = u.strip()

        if u.startswith(("http://", "https://")):
            return normalize_youtube_url(u)

        if u.startswith("/watch?") or u.startswith("watch?"):
            if u.startswith("/"):
                u = u[1:]
            return normalize_youtube_url(f"https://www.youtube.com/{u}")

        return normalize_youtube_url(f"https://www.youtube.com/watch?v={u}")

    out: List[Track] = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        title = e.get("title") or e.get("id") or "Unknown"
        watch_url = to_watch_url(e)
        if not watch_url:
            continue
        out.append(Track.from_youtube(title=title, watch_url=watch_url, playlist_title=playlist_title))

    return out


def resolve_youtube_audio_stream(watch_url: str, timeout_s: int = 30) -> str:
    if not shutil.which("yt-dlp"):
        raise RuntimeError("yt-dlp not found (required for YouTube playback).")

    watch_url = normalize_youtube_url(watch_url)
    fmt = "bestaudio[acodec!=none]/best[acodec!=none]/best"
    cmd = ["yt-dlp", "-f", fmt, "-g", "--no-warnings", watch_url]

    try:
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, timeout=timeout_s).decode("utf-8", "ignore").strip()
    except subprocess.CalledProcessError as e:
        msg = (e.output or b"").decode("utf-8", "ignore").strip()
        msg = msg[-1000:] if len(msg) > 1000 else msg
        raise RuntimeError(f"yt-dlp failed.\n{msg}") from None

    lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
    if not lines:
        raise RuntimeError("yt-dlp returned no stream URL.")
    return lines[-1]


class ProgressPanel(Static):
    def render_state(
        self,
        *,
        title: str,
        state: str,
        elapsed: float,
        duration: Optional[float],
        width_chars: int,
        shuffle_on: bool,
    ) -> str:
        safe_title = title if len(title) <= 80 else (title[:77] + "…")
        bar_width = max(16, width_chars - 12)

        if duration and duration > 0:
            pct = clamp(elapsed / duration, 0.0, 1.0)
            filled = int(pct * bar_width)
            bar = "█" * filled + "░" * (bar_width - filled)
            right = fmt_mmss(duration)
        else:
            block = max(6, bar_width // 6)
            pos = int((elapsed * 6) % max(1, (bar_width + block))) - block
            bar = "".join("█" if pos <= i < pos + block else "░" for i in range(bar_width))
            right = "??:??"

        left = fmt_mmss(elapsed)
        shuf = "  [b]SHUFFLE[/b]" if shuffle_on else ""
        line1 = f"[b]{state}[/b]{shuf}  {safe_title}"
        line2 = f"{left} [{bar}] {right}"
        line3 = "[dim]Enter: play • Space: pause • n/p: next/prev • s: stop[/dim]"
        return f"{TUX_ASCII}\n{line1}\n\n{line2}\n{line3}"

    def set_idle(self, *, shuffle_on: bool) -> None:
        w = max(60, self.size.width)
        self.update(
            self.render_state(
                title="Nothing playing",
                state="STOPPED",
                elapsed=0.0,
                duration=None,
                width_chars=w,
                shuffle_on=shuffle_on,
            )
        )

    def set_playing(self, title: str, elapsed: float, duration: Optional[float], *, shuffle_on: bool, paused: bool) -> None:
        w = max(60, self.size.width)
        self.update(
            self.render_state(
                title=title,
                state="PAUSED" if paused else "PLAYING",
                elapsed=elapsed,
                duration=duration,
                width_chars=w,
                shuffle_on=shuffle_on,
            )
        )


class DownloadPanel(Static):
    def render_download(self, *, active: bool, cur: int, total: int, title: str, started_at: float) -> str:
        if not active:
            return "[dim]No download running. Press d to download playlist as MP3.[/dim]"

        elapsed = max(0.0, time.monotonic() - started_at)
        width = max(24, self.size.width - 18)
        block = max(6, width // 6)
        pos = int((elapsed * 8) % max(1, (width + block))) - block
        bar = "".join("█" if pos <= i < pos + block else "░" for i in range(width))

        return (
            f"[b]DOWNLOADING[/b]  {cur}/{total}  [dim](press c to cancel)[/dim]\n"
            f"[dim]{title}[/dim]\n"
            f"[{bar}]"
        )

    def set_idle(self) -> None:
        self.update(self.render_download(active=False, cur=0, total=0, title="", started_at=0.0))

    def set_active(self, *, cur: int, total: int, title: str, started_at: float) -> None:
        self.update(self.render_download(active=True, cur=cur, total=total, title=title, started_at=started_at))


PlaySource = Literal["tracks", "playlist"]


class MusicTUI(App):
    CSS = """
    Screen { padding: 0 1; }

    #toprow { height: 14; }
    #logo { width: 1fr; }
    #progress { width: 1fr; border: solid $success; padding: 1 2; }

    #search { margin: 0 0 1 0; }
    #yturl { margin: 0 0 1 0; }

    #left { width: 1fr; min-width: 46; }
    #right { width: 1fr; min-width: 32; }

    #tracks { height: 1fr; border: solid $accent; }
    #tracks_empty { height: 4; border: solid $accent; padding: 1 1; display: none; }

    #playlist { height: 1fr; border: solid $accent; }

    #download { dock: bottom; height: 4; border-top: heavy $accent; padding: 0 1; background: $panel; }
    #status { dock: bottom; height: 1; padding: 0 1; background: $panel; color: $text; }

    #dlbox { dock: bottom; height: 5; border: heavy $accent; padding: 0 1; background: $panel; display: none; }
    #dlpath { border: heavy $success; }

    .dim { color: $text-muted; }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("r", "rescan", "Rescan"),
        ("s", "stop", "Stop"),
        ("+", "add_to_playlist", "Add"),
        ("-", "remove_from_playlist", "Remove"),
        ("x", "toggle_shuffle", "Shuffle"),
        # d + c + space + n/p handled globally
    ]

    tracks: List[Track] = []
    matches_all: List[Track] = []
    matches_view: List[Track] = []
    playlist: List[Track] = []

    _search_timer = None
    _pending_query: str = ""

    _player_name: Optional[str] = None
    _player_cmd: Optional[List[str]] = None

    _proc: Optional[subprocess.Popen] = None
    _playing_track: Optional[Track] = None
    _play_start: float = 0.0
    _duration: Optional[float] = None

    _play_source: Optional[PlaySource] = None
    _playlist_play_index: Optional[int] = None

    _shuffle_on: bool = False
    _playlist_original: Optional[List[Track]] = None

    _paused: bool = False
    _paused_at: float = 0.0
    _paused_total: float = 0.0

    _download_prompt_active: bool = False
    _download_in_progress: bool = False
    _download_cancel_requested: bool = False
    _download_started_at: float = 0.0
    _download_cur: int = 0
    _download_total: int = 0
    _download_title: str = ""
    _download_task: Optional[asyncio.Task] = None
    _download_proc: Optional[subprocess.Popen] = None
    _prev_focus_id: Optional[str] = None

    def set_status(self, msg: str) -> None:
        try:
            self.query_one("#status", Static).update(msg)
        except Exception:
            pass

    def on_key(self, event) -> None:
        if self._download_prompt_active:
            if event.key == "escape":
                event.stop()
                self._hide_download_prompt(cancelled=True)
            return

        if event.key == "space":
            event.stop()
            self.action_toggle_pause()
            return

        if event.key == "n":
            event.stop()
            self.action_next_track()
            return

        if event.key == "p":
            event.stop()
            self.action_prev_track()
            return

        if event.key == "d":
            event.stop()
            self.action_download_playlist()
            return

        if event.key == "c":
            event.stop()
            self.action_cancel_download()
            return

    def _install_signal_handlers(self) -> None:
        def _exit_handler(signum, frame=None):
            try:
                self._stop_playback()
                self._cancel_download_kill_proc()
            finally:
                raise SystemExit(0)

        def _tstp_handler(signum, frame=None):
            try:
                self._stop_playback()
                self._cancel_download_kill_proc()
            finally:
                signal.signal(signal.SIGTSTP, signal.SIG_DFL)
                os.kill(os.getpid(), signal.SIGTSTP)

        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            try:
                signal.signal(sig, _exit_handler)
            except Exception:
                pass

        try:
            signal.signal(signal.SIGTSTP, _tstp_handler)
        except Exception:
            pass

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)

        with Horizontal(id="toprow"):
            with Vertical(id="logo"):
                yield Static(BANNER)
            yield ProgressPanel(id="progress")

        with Horizontal():
            with Vertical(id="left"):
                yield Input(placeholder="Search… (ed sheeran matches ed_sheeran)", id="search")
                yield Static("No audio files found / no matches.", id="tracks_empty", classes="dim")
                yield ListView(id="tracks")

            with Vertical(id="right"):
                yield Static("[b]Playlist[/b]  [dim](Tab here, Enter plays, - removes)[/dim]")
                yield Input(placeholder="Paste YouTube playlist URL and press Enter…", id="yturl")
                yield ListView(id="playlist")

        yield DownloadPanel(id="download")

        with Vertical(id="dlbox"):
            yield Static("[b]Download playlist as MP3[/b] — type a folder path and press Enter. Esc cancels.", id="dlhint")
            yield Input(value=str(Path.home() / "Music"), id="dlpath")

        yield Static("Ready.", id="status")
        yield Footer()

    def on_mount(self) -> None:
        self._install_signal_handlers()

        found = find_player()
        if found:
            self._player_name, self._player_cmd = found

        self.rescan()

        self.set_interval(0.25, self._tick_progress)
        self.set_interval(0.20, self._tick_download_panel)

        self.query_one("#download", DownloadPanel).set_idle()
        self.query_one("#progress", ProgressPanel).set_idle(shuffle_on=self._shuffle_on)
        self.set_status("Ready. Space pause/resume. n/p next/prev.")

    # ---------- Inputs ----------
    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "search":
            return
        self._pending_query = (event.value or "")
        if self._search_timer is not None:
            try:
                self._search_timer.stop()
            except Exception:
                pass
        self._search_timer = self.set_timer(0.18, self._apply_search)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "search":
            self.query_one("#tracks", ListView).focus()
            return

        if event.input.id == "yturl":
            url = (event.value or "").strip()
            if not url:
                return
            self._load_youtube_playlist(url)
            self.query_one("#playlist", ListView).focus()
            return

        if event.input.id == "dlpath" and self._download_prompt_active:
            dest = (event.value or "").strip()
            self._hide_download_prompt(cancelled=False)
            if dest:
                self._kickoff_download_playlist_items(dest)
            else:
                self.set_status("Download cancelled (empty path).")
            return

    def _apply_search(self) -> None:
        raw = self._pending_query.strip()
        if not raw:
            self.matches_all = list(self.tracks)
            self._refresh_view(reset_index=True)
            return

        q_norm = normalize_for_search(raw)
        q_sq = squash_spaces(q_norm)

        self.matches_all = [
            t for t in self.tracks
            if (
                q_norm in t.norm_name
                or q_norm in t.norm_parent
                or q_sq in t.squashed_name
                or q_sq in t.squashed_parent
            )
        ]
        self._refresh_view(reset_index=True)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.list_view.id == "playlist":
            idx = self.current_playlist_index()
            if idx is None:
                return
            self._start_track(self.playlist[idx], source="playlist", playlist_index=idx)
        else:
            t = self.current_track()
            if not t:
                return
            self._start_track(t, source="tracks", playlist_index=None)

    # ---------- Scan / Populate ----------
    def rescan(self) -> None:
        self.tracks = scan_tracks_recursive(Path.cwd())
        self.matches_all = list(self.tracks)
        self._refresh_view(reset_index=True)

    def _refresh_view(self, reset_index: bool = False) -> None:
        self.matches_view = self.matches_all[:MAX_SHOW]
        tracks_lv = self.query_one("#tracks", ListView)
        empty = self.query_one("#tracks_empty", Static)

        tracks_lv.clear()

        if not self.matches_view:
            tracks_lv.styles.display = "none"
            empty.styles.display = "block"
            return

        empty.styles.display = "none"
        tracks_lv.styles.display = "block"

        for t in self.matches_view:
            tracks_lv.append(ListItem(Static(t.label)))

        if reset_index or tracks_lv.index is None:
            tracks_lv.index = 0

    def _refresh_playlist(self, reset_index: bool = False) -> None:
        lv = self.query_one("#playlist", ListView)
        lv.clear()
        if not self.playlist:
            lv.append(ListItem(Static("Playlist empty. Press + to add selected track.", classes="dim")))
            lv.index = 0
            return
        for i, t in enumerate(self.playlist, start=1):
            lv.append(ListItem(Static(f"{i:>3}. {t.label}")))
        if reset_index or lv.index is None:
            lv.index = 0

    def current_track(self) -> Optional[Track]:
        lv = self.query_one("#tracks", ListView)
        if lv.styles.display == "none":
            return None
        if not self.matches_view or lv.index is None:
            return None
        idx = int(lv.index)
        return self.matches_view[idx] if 0 <= idx < len(self.matches_view) else None

    def current_playlist_index(self) -> Optional[int]:
        lv = self.query_one("#playlist", ListView)
        if lv.index is None or not self.playlist:
            return None
        idx = int(lv.index)
        return idx if 0 <= idx < len(self.playlist) else None

    # ---------- YouTube playlist ----------
    def _load_youtube_playlist(self, url: str) -> None:
        self.set_status("Loading YouTube playlist…")
        self._shuffle_on = False
        self._playlist_original = None
        try:
            items = fetch_youtube_playlist_tracks(url)
            if not items:
                self.set_status("No playlist items found.")
                return
            self.playlist = items
            self._playlist_original = list(items)
            self._refresh_playlist(reset_index=True)
            self.set_status(f"Loaded {len(items)} items.")
        except Exception as e:
            self.set_status(f"Failed to load playlist: {e}")

    # ---------- Actions ----------
    def action_rescan(self) -> None:
        self.rescan()
        self.set_status("Rescanned local audio files.")

    def action_stop(self) -> None:
        self._stop_playback()
        self.set_status("Stopped playback.")

    def action_add_to_playlist(self) -> None:
        t = self.current_track()
        if not t:
            return
        self.playlist.append(t)
        self._refresh_playlist(reset_index=False)
        self.set_status("Added to playlist.")

    def action_remove_from_playlist(self) -> None:
        idx = self.current_playlist_index()
        if idx is None:
            self.set_status("Remove: nothing selected.")
            return
        self.playlist.pop(idx)
        self._refresh_playlist(reset_index=True)
        self.set_status("Removed from playlist.")

    def action_toggle_shuffle(self) -> None:
        if not self.playlist:
            self.set_status("Shuffle: playlist empty.")
            return
        if not self._shuffle_on:
            if self._playlist_original is None:
                self._playlist_original = list(self.playlist)
            random.shuffle(self.playlist)
            self._shuffle_on = True
            self.set_status("Shuffle ON.")
        else:
            if self._playlist_original is not None:
                self.playlist = list(self._playlist_original)
            self._shuffle_on = False
            self.set_status("Shuffle OFF.")
        self._refresh_playlist(reset_index=True)
        self._refresh_progress_widget()

    # ---------- Next / Prev ----------
    def action_next_track(self) -> None:
        if not self._playing_track:
            self.set_status("Nothing playing.")
            return
        if self._play_source != "playlist" or self._playlist_play_index is None:
            self.set_status("Next/Prev works in playlist playback.")
            return
        nxt = self._playlist_play_index + 1
        if nxt >= len(self.playlist):
            self.set_status("End of playlist.")
            return
        plv = self.query_one("#playlist", ListView)
        plv.index = nxt
        self._start_track(self.playlist[nxt], source="playlist", playlist_index=nxt)

    def action_prev_track(self) -> None:
        if not self._playing_track:
            self.set_status("Nothing playing.")
            return
        if self._play_source != "playlist" or self._playlist_play_index is None:
            self.set_status("Next/Prev works in playlist playback.")
            return
        prv = self._playlist_play_index - 1
        if prv < 0:
            self.set_status("Start of playlist.")
            return
        plv = self.query_one("#playlist", ListView)
        plv.index = prv
        self._start_track(self.playlist[prv], source="playlist", playlist_index=prv)

    # ---------- Pause / Resume ----------
    def action_toggle_pause(self) -> None:
        if not self._proc or self._proc.poll() is not None:
            self.set_status("Nothing playing.")
            return
        try:
            if not self._paused:
                os.killpg(self._proc.pid, signal.SIGSTOP)
                self._paused = True
                self._paused_at = time.monotonic()
                self.set_status("Paused. (Space to resume)")
            else:
                os.killpg(self._proc.pid, signal.SIGCONT)
                now = time.monotonic()
                self._paused_total += max(0.0, now - self._paused_at)
                self._paused = False
                self.set_status("Resumed.")
        except Exception as e:
            self.set_status(f"Pause/resume failed: {e}")
        self._refresh_progress_widget()

    # ---------- Download ----------
    def action_download_playlist(self) -> None:
        if self._download_in_progress:
            self.set_status("Download already running (press c to cancel).")
            return
        if not self.playlist:
            self.set_status("Playlist empty.")
            return
        self._show_download_prompt()

    def _show_download_prompt(self) -> None:
        if self._download_prompt_active:
            return
        focused = self.screen.focused
        self._prev_focus_id = getattr(focused, "id", None)
        self.query_one("#dlbox", Vertical).styles.display = "block"
        self._download_prompt_active = True
        ip = self.query_one("#dlpath", Input)
        ip.value = str(Path.home() / "Music")
        ip.focus()
        self.set_status("Type a download folder and press Enter. Esc cancels.")

    def _hide_download_prompt(self, *, cancelled: bool) -> None:
        self.query_one("#dlbox", Vertical).styles.display = "none"
        self._download_prompt_active = False
        try:
            if self._prev_focus_id:
                self.query_one(f"#{self._prev_focus_id}").focus()
        except Exception:
            pass
        if cancelled:
            self.set_status("Download cancelled.")

    def action_cancel_download(self) -> None:
        if not self._download_in_progress:
            self.set_status("No download running.")
            return
        self._download_cancel_requested = True
        self.set_status("Cancelling download…")
        self._cancel_download_kill_proc()

    def _cancel_download_kill_proc(self) -> None:
        proc = self._download_proc
        if proc and proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except Exception:
                try:
                    proc.terminate()
                except Exception:
                    pass

    def _kickoff_download_playlist_items(self, dest_folder: str) -> None:
        dest = Path(dest_folder).expanduser()
        try:
            dest.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            self.set_status(f"Invalid folder: {e}")
            return
        if any(t.source == "youtube" for t in self.playlist) and not shutil.which("yt-dlp"):
            self.set_status("yt-dlp not found.")
            return
        self._download_in_progress = True
        self._download_cancel_requested = False
        self._download_started_at = time.monotonic()
        self._download_cur = 0
        self._download_total = len(self.playlist)
        self._download_title = "Starting…"
        self.set_status(f"Downloading {self._download_total} items to: {dest} (press c to cancel)")
        self._download_task = asyncio.create_task(self._download_playlist_items_async(dest))

    def _tick_download_panel(self) -> None:
        dp = self.query_one("#download", DownloadPanel)
        if self._download_in_progress:
            dp.set_active(cur=self._download_cur, total=self._download_total, title=self._download_title, started_at=self._download_started_at)
        else:
            dp.set_idle()

    async def _download_playlist_items_async(self, dest: Path) -> None:
        items = list(self.playlist)

        def title_from_label(label: str) -> str:
            raw = re.sub(r"\[/?[^\]]+\]", "", label)
            raw = raw.split("  (", 1)[0].strip()
            return raw or "track"

        def run_popen(cmd: List[str]) -> int:
            p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            self._download_proc = p
            try:
                while p.poll() is None and not self._download_cancel_requested:
                    time.sleep(0.1)
                if self._download_cancel_requested and p.poll() is None:
                    try:
                        os.killpg(p.pid, signal.SIGTERM)
                    except Exception:
                        try:
                            p.terminate()
                        except Exception:
                            pass
                    try:
                        p.wait(timeout=1.0)
                    except Exception:
                        pass
                    return 999
                return p.returncode or 0
            finally:
                self._download_proc = None

        try:
            for i, t in enumerate(items, start=1):
                if self._download_cancel_requested:
                    break
                num = f"{i:03d}"
                nice = title_from_label(t.label)
                self._download_cur = i
                self._download_title = f"{num}/{len(items):03d}  {nice}"

                if t.source == "youtube":
                    title = safe_filename(nice)
                    outtmpl = str(dest / f"{num} - {title}.%(ext)s")
                    cmd = [
                        "yt-dlp",
                        "--no-playlist",
                        "-x",
                        "--audio-format", "mp3",
                        "--audio-quality", "0",
                        "-o", outtmpl,
                        normalize_youtube_url(t.uri),
                    ]
                    rc = await asyncio.to_thread(run_popen, cmd)
                    if self._download_cancel_requested:
                        break
                    if rc != 0:
                        self.set_status(f"Failed: {title} (yt-dlp exit {rc})")
                    continue

                src = Path(t.uri)
                if not src.exists():
                    self.set_status(f"Missing file: {src}")
                    continue

                base_title = safe_filename(src.stem)
                out_mp3 = dest / f"{num} - {base_title}.mp3"

                if src.suffix.lower() == ".mp3":
                    try:
                        await asyncio.to_thread(shutil.copy2, src, out_mp3)
                    except Exception as e:
                        self.set_status(f"Copy failed: {src.name} ({e})")
                    continue

                if not shutil.which("ffmpeg"):
                    self.set_status(f"ffmpeg not found (can't convert): {src.name}")
                    continue

                cmd = ["ffmpeg", "-y", "-i", str(src), "-vn", "-codec:a", "libmp3lame", "-q:a", "0", str(out_mp3)]
                rc = await asyncio.to_thread(run_popen, cmd)
                if self._download_cancel_requested:
                    break
                if rc != 0:
                    self.set_status(f"Convert failed: {src.name} (ffmpeg exit {rc})")

            self.set_status("Download cancelled." if self._download_cancel_requested else "Download finished.")
        except Exception as e:
            self.set_status(f"Download failed: {e}")
        finally:
            self._download_in_progress = False
            self._download_cancel_requested = False
            self._download_cur = 0
            self._download_total = 0
            self._download_title = ""
            self._download_proc = None

    # ---------- Playback ----------
    def _pretty_title(self, track: Track) -> str:
        if track.source == "local":
            return Path(track.uri).name
        return re.sub(r"\[/?[^\]]+\]", "", track.label).strip()

    def _current_elapsed(self) -> float:
        if not self._playing_track:
            return 0.0
        if self._paused:
            return max(0.0, self._paused_at - self._play_start - self._paused_total)
        return max(0.0, time.monotonic() - self._play_start - self._paused_total)

    def _refresh_progress_widget(self) -> None:
        pp = self.query_one("#progress", ProgressPanel)
        if self._playing_track:
            pp.set_playing(
                self._pretty_title(self._playing_track),
                self._current_elapsed(),
                self._duration,
                shuffle_on=self._shuffle_on,
                paused=self._paused,
            )
        else:
            pp.set_idle(shuffle_on=self._shuffle_on)

    def _start_track(self, track: Track, *, source: PlaySource, playlist_index: Optional[int]) -> None:
        if not self._player_cmd or not self._player_name:
            self.set_status("No player found. Install mpv (recommended) or ffplay.")
            return
        if track.source == "youtube" and self._player_name != "mpv":
            self.set_status("YouTube playback requires mpv.")
            return

        self._stop_playback()

        try:
            target = track.uri
            if track.source == "youtube":
                self.set_status("Resolving stream…")
                target = resolve_youtube_audio_stream(track.uri)

            cmd = [*self._player_cmd, target]
            self._proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)

            self._playing_track = track
            self._play_start = time.monotonic()
            self._paused = False
            self._paused_at = 0.0
            self._paused_total = 0.0

            self._duration = get_duration_seconds(Path(track.uri)) if track.source == "local" else None
            self._play_source = source
            self._playlist_play_index = playlist_index

            self._refresh_progress_widget()
            self.set_status("Playing.")
        except Exception as e:
            self.set_status(f"Failed to play: {e}")
            self.query_one("#progress", ProgressPanel).set_idle(shuffle_on=self._shuffle_on)

    def _stop_playback(self) -> None:
        proc = self._proc
        self._proc = None
        self._playing_track = None
        self._duration = None
        self._play_source = None
        self._playlist_play_index = None
        self._paused = False
        self._paused_at = 0.0
        self._paused_total = 0.0

        if proc and proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
                try:
                    proc.wait(timeout=0.8)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL)
            except Exception:
                try:
                    proc.terminate()
                except Exception:
                    pass

        self.query_one("#progress", ProgressPanel).set_idle(shuffle_on=self._shuffle_on)

    def _tick_progress(self) -> None:
        if not self._playing_track:
            return

        if self._proc and self._proc.poll() is not None:
            self._proc = None
            if self._play_source == "playlist" and self._playlist_play_index is not None:
                nxt = self._playlist_play_index + 1
                if nxt < len(self.playlist):
                    plv = self.query_one("#playlist", ListView)
                    plv.index = nxt
                    self._start_track(self.playlist[nxt], source="playlist", playlist_index=nxt)
                    return
            self._stop_playback()
            return

        self._refresh_progress_widget()

    def on_shutdown(self) -> None:
        self._stop_playback()
        self._cancel_download_kill_proc()


if __name__ == "__main__":
    app = MusicTUI()
    try:
        app.run()
    finally:
        try:
            app._stop_playback()
        except Exception:
            pass
        try:
            app._cancel_download_kill_proc()
        except Exception:
            pass
