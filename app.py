"""
MusicDownloader — Flask web app for searching YouTube and downloading/previewing audio
=====================================================================================
Endpoints:
  GET /api/search?q=<query>    → JSON array of search results
  GET /api/download?url=<yt>   → stream full audio as attachment (m4a)
  GET /api/preview?url=<yt>    → stream full audio for in-browser playback (前端控制30s)
"""

import json
import subprocess
import sys
import os
import tempfile

import flask
from flask import Flask, request, jsonify, Response

app = Flask(__name__)

# ── helpers ──────────────────────────────────────────────────────────────────

YT_DLP = "yt-dlp"  # assume on PATH (pip install puts it there)
AUDIO_EXT = "m4a"  # 不用 ffmpeg，直接下 YouTube 原生 AAC
AUDIO_MIME = "audio/mp4"


def _yt_dlp_json(*args: str) -> list[dict]:
    """Run yt-dlp search and return parsed JSON results."""
    import yt_dlp
    opts = {"quiet": True, "no_warnings": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        try:
            raw = ydl.extract_info(*args, download=False)
        except Exception as exc:
            raise RuntimeError(f"yt-dlp failed: {exc}") from exc
        if not raw or "entries" not in raw:
            return []
        return raw["entries"]


def _download_audio(url: str) -> tuple[bytes, str]:
    """
    Download best audio track from YouTube.

    Uses yt-dlp Python module directly (no subprocess).
    Returns (file_bytes, extension).
    """
    import yt_dlp
    with tempfile.TemporaryDirectory() as tmp:
        out_template = os.path.join(tmp, "audio.%(ext)s")
        opts = {
            "quiet": True,
            "no_warnings": True,
            "format": "bestaudio[ext=m4a]/bestaudio/best",
            "outtmpl": out_template,
            "extract_flat": False,
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            try:
                info = ydl.extract_info(url, download=True)
            except Exception as exc:
                raise RuntimeError(f"yt-dlp download failed: {exc}") from exc

            # 找下载后的文件
            ext = info.get("ext", AUDIO_EXT)
            expected = os.path.join(tmp, f"audio.{ext}")
            if os.path.isfile(expected):
                with open(expected, "rb") as fh:
                    return fh.read(), ext

            # 有时 ext 不同，扫描目录找
            for f in os.listdir(tmp):
                fp = os.path.join(tmp, f)
                if os.path.isfile(fp) and f != "audio":
                    e = f.rsplit(".", 1)[-1]
                    with open(fp, "rb") as fh:
                        return fh.read(), e

            raise RuntimeError("yt-dlp did not produce an audio file")


# ── routes ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    """Serve the single-page frontend."""
    return flask.send_from_directory("templates", "index.html")


@app.route("/api/search")
def api_search():
    """
    Search YouTube via yt-dlp and return structured results.

    Query parameter:  q  (string, required)
    Returns JSON:     [{title, duration, url, thumbnail, author}, …]
    """
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"error": 'Missing query parameter "q"'}), 400

    try:
        raw = _yt_dlp_json(f"ytsearch10:{q}")
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 502

    results = []
    for entry in raw:
        # yt-dlp returns 'title', 'duration' (int seconds), 'webpage_url',
        # 'thumbnail', 'channel' / 'uploader'
        results.append({
            "title": entry.get("title", "Unknown"),
            "duration": entry.get("duration", 0),
            "url": entry.get("webpage_url", ""),
            "thumbnail": entry.get("thumbnail", ""),
            "author": entry.get("channel", entry.get("uploader", "Unknown")),
        })

    return jsonify({"results": results, "count": len(results)})


@app.route("/api/download")
def api_download():
    """
    Download full audio and stream it back as an attachment.

    Query parameter:  url  (YouTube URL, required)
    """
    url = request.args.get("url", "").strip()
    if not url:
        return jsonify({"error": 'Missing query parameter "url"'}), 400

    try:
        data, ext = _download_audio(url)
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 502

    return Response(
        data,
        mimetype=AUDIO_MIME,
        headers={
            "Content-Disposition": f'attachment; filename="music.{ext}"',
            "Content-Length": str(len(data)),
        },
    )


@app.route("/api/preview")
def api_preview():
    """
    Stream full audio (frontend limits playback to 30 seconds).

    Query parameter:  url  (YouTube URL, required)
    """
    url = request.args.get("url", "").strip()
    if not url:
        return jsonify({"error": 'Missing query parameter "url"'}), 400

    try:
        data, ext = _download_audio(url)
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 502

    return Response(
        data,
        mimetype=AUDIO_MIME,
        headers={
            "Content-Length": str(len(data)),
        },
    )


# ── entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    print(f"[MusicDownloader] Starting on http://0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port, debug=debug)
