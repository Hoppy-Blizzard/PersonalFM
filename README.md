# ANTHONY FM 🎧🐧  
A fast, terminal-based music player (Textual TUI) for **local audio + YouTube playlists**, with playlist management, shuffle, MP3 downloading, and a clean “now playing” panel.

> Built for Linux terminals. Runs great in a translucent, borderless terminal window (e.g. Kitty/Konsole).

---

## Features

### Playback
- **Play local audio files** scanned from your current directory (**recursive**).
- **Load and play YouTube playlists** by pasting a playlist URL (supports `music.youtube.com` and `www.youtube.com` links).
- **Now Playing** panel with:
  - Track title
  - Elapsed timer
  - Progress bar (exact for local files with duration; animated for streams)
  - Pause state indicator

### Playlist
- Add/remove tracks to a playlist.
- Play from playlist (Enter).
- **Shuffle toggle** (keeps playlist usable for playback).
- **Skip tracks** while playing from playlist:
  - Next / Previous

### Downloads
- Press **`d`** anywhere to download the current playlist as **MP3**.
- Prompts for a **save folder**.
- Shows overall download progress.
- Cancel downloads with **`c`**.

### Safe exits
- Stops audio properly on exit and on common terminal signals (Ctrl+C, Ctrl+Z, terminal close), so you don’t end up with “ghost” playback continuing.

---

## Screenshots

Add screenshots/gifs here (recommended):
- Now Playing panel
- Playlist loaded from YouTube
- Download progress panel

---

## Requirements

### Python
- Python **3.10+** recommended (works on newer Python versions too)

### System dependencies
You’ll want these installed for best experience:

- **mpv** (recommended player)
- **yt-dlp** (YouTube playlist loading + stream resolution + downloads)
- **ffmpeg** (converting non-mp3 local audio to mp3 during downloads)
- **ffprobe** (typically included with ffmpeg; used for local duration/progress)

On Arch/CachyOS:
```bash
sudo pacman -S mpv yt-dlp ffmpeg



Controls / Keybindings

q	Quit
r	Rescan local files (recursive from current folder)
s	Stop playback
Space	Pause / Resume
d	Download playlist as MP3 (prompts for folder)
c	Cancel active download
x	Toggle shuffle
Playlist navigation
Key	Action
Enter	Play selected item (tracks list or playlist list)
+	Add selected track (from local list) to playlist
-	Remove selected playlist item
n	Next track (playlist playback only)
p	Previous track (playlist playback only)


Usage
1) Play local files

cd into your music folder (or a folder containing subfolders of music)

Run the app

Search (optional)

Select a track and press Enter

Press Space to pause/resume



2) Load a YouTube playlist

Paste playlist URL into the right-hand URL input

Press Enter

Playlist populates

Select an entry and press Enter to play




3) Download playlist to MP3

Load a YouTube playlist (or build a playlist using +)

Press d

Type a folder path (e.g. ~/Music/Downloads) and press Enter

Watch progress in the download panel

Press c to cancel




Notes / Limitations

YouTube playback requires mpv (recommended).
ffplay is supported for local files, but YouTube stream playback is built around mpv.

Progress bar is exact for local files when duration is known (via ffprobe).

For YouTube streams, duration may be unknown; the bar will show an animated “streaming” style indicator.
