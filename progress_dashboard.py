#!/usr/bin/env python3
"""
Simple web dashboard to monitor transcription progress.

Run with: python progress_dashboard.py
Then open: http://localhost:8080
"""

import json
import os
import re
from datetime import datetime
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

from config import config

PORT = int(os.environ.get("DASHBOARD_PORT", "8890"))


def get_transcription_status():
    """Gather current status of all transcription-related files."""
    status = {
        "timestamp": datetime.now().isoformat(),
        "config": {
            "video_folder": config.video_folder,
            "audio_folder": config.audio_folder,
            "work_folder": config.work_folder,
            "output_folder": config.output_folder,
            "stability_window": config.stability_window,
            "scan_interval": config.scan_interval,
        },
        "videos": [],
        "audio_files": [],
        "transcriptions": [],
        "in_progress": None,
    }

    # Check video folder
    if os.path.exists(config.video_folder):
        for f in os.listdir(config.video_folder):
            if f.lower().endswith(config.supported_video_formats):
                path = os.path.join(config.video_folder, f)
                base = os.path.splitext(f)[0]
                audio_exists = any(
                    os.path.exists(os.path.join(config.work_folder, base + ext))
                    for ext in config.supported_audio_formats
                )
                transcription_exists = os.path.exists(
                    os.path.join(config.output_folder, base + ".txt")
                )
                status["videos"].append({
                    "name": f,
                    "size_mb": round(os.path.getsize(path) / (1024 * 1024), 1),
                    "mtime": datetime.fromtimestamp(os.path.getmtime(path)).isoformat(),
                    "audio_converted": audio_exists,
                    "transcribed": transcription_exists,
                })

    # Check work folder (converted audio)
    if os.path.exists(config.work_folder):
        for f in os.listdir(config.work_folder):
            if f.lower().endswith(config.supported_audio_formats) and not f.endswith(".backup"):
                path = os.path.join(config.work_folder, f)
                base = os.path.splitext(f)[0]
                transcription_exists = os.path.exists(
                    os.path.join(config.output_folder, base + ".txt")
                )
                status["audio_files"].append({
                    "name": f,
                    "size_mb": round(os.path.getsize(path) / (1024 * 1024), 1),
                    "mtime": datetime.fromtimestamp(os.path.getmtime(path)).isoformat(),
                    "transcribed": transcription_exists,
                })

    # Check transcriptions
    if os.path.exists(config.output_folder):
        for f in os.listdir(config.output_folder):
            if f.endswith(".txt") and not f.endswith(".backup"):
                path = os.path.join(config.output_folder, f)
                size = os.path.getsize(path)
                # Read first few lines to get metadata
                try:
                    with open(path, "r") as tf:
                        content = tf.read(500)
                    duration_match = re.search(r"Duration: ([\d.]+)", content)
                    duration = duration_match.group(1) if duration_match else "unknown"
                except:
                    duration = "error"

                status["transcriptions"].append({
                    "name": f,
                    "size_bytes": size,
                    "mtime": datetime.fromtimestamp(os.path.getmtime(path)).isoformat(),
                    "duration": duration,
                })

    # Try to read current progress from log file
    log_file = "transcription.log"
    if os.path.exists(log_file):
        try:
            with open(log_file, "r") as lf:
                lines = lf.readlines()[-50:]  # Last 50 lines

            for line in reversed(lines):
                if "Starting transcription of" in line:
                    match = re.search(r"Starting transcription of '([^']+)'", line)
                    if match:
                        status["in_progress"] = {
                            "file": match.group(1),
                            "started": line[:19],  # Timestamp
                            "percent": 0,
                        }
                    break
                elif "Completed '" in line:
                    # Last action was a completion, nothing in progress
                    break
        except:
            pass

    return status


class DashboardHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(HTML_TEMPLATE.encode())
        elif self.path == "/api/status":
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            status = get_transcription_status()
            self.wfile.write(json.dumps(status, indent=2).encode())
        else:
            self.send_error(404)

    def log_message(self, format, *args):
        pass  # Suppress logging


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Transcription Progress</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #1a1a2e;
            color: #eee;
            padding: 20px;
            min-height: 100vh;
        }
        h1 { color: #00d9ff; margin-bottom: 20px; }
        h2 { color: #888; font-size: 14px; text-transform: uppercase; margin: 20px 0 10px; }
        .container { max-width: 1200px; margin: 0 auto; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(350px, 1fr)); gap: 20px; }
        .card {
            background: #16213e;
            border-radius: 10px;
            padding: 20px;
            border: 1px solid #0f3460;
        }
        .card h3 { color: #00d9ff; margin-bottom: 15px; font-size: 16px; }
        .stat { display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid #0f3460; }
        .stat:last-child { border-bottom: none; }
        .stat-label { color: #888; }
        .stat-value { color: #fff; font-weight: 500; }
        .file-list { list-style: none; }
        .file-item {
            padding: 10px;
            margin: 5px 0;
            background: #0f3460;
            border-radius: 6px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .file-name { font-size: 13px; word-break: break-all; flex: 1; }
        .file-meta { font-size: 12px; color: #888; margin-left: 10px; white-space: nowrap; }
        .badge {
            padding: 3px 8px;
            border-radius: 4px;
            font-size: 11px;
            font-weight: 600;
            margin-left: 8px;
        }
        .badge-done { background: #00c853; color: #000; }
        .badge-pending { background: #ff9800; color: #000; }
        .badge-progress { background: #2196f3; color: #fff; }
        .progress-bar {
            background: #0f3460;
            border-radius: 10px;
            height: 20px;
            overflow: hidden;
            margin: 10px 0;
        }
        .progress-fill {
            background: linear-gradient(90deg, #00d9ff, #00c853);
            height: 100%;
            transition: width 0.5s ease;
        }
        .refresh-info { color: #666; font-size: 12px; margin-top: 20px; text-align: center; }
        .in-progress {
            background: linear-gradient(135deg, #1a237e, #0d47a1);
            border: 2px solid #2196f3;
            animation: pulse 2s infinite;
        }
        @keyframes pulse {
            0%, 100% { border-color: #2196f3; }
            50% { border-color: #00d9ff; }
        }
        .empty { color: #666; font-style: italic; padding: 20px; text-align: center; }
    </style>
</head>
<body>
    <div class="container">
        <h1>Transcription Progress Dashboard</h1>

        <div id="current-progress" class="card in-progress" style="display: none; margin-bottom: 20px;">
            <h3>Currently Processing</h3>
            <div id="current-file"></div>
            <div class="progress-bar"><div class="progress-fill" id="progress-fill"></div></div>
            <div id="progress-text" style="text-align: center; color: #888;"></div>
        </div>

        <div class="grid">
            <div class="card">
                <h3>Configuration</h3>
                <div id="config-stats"></div>
            </div>

            <div class="card">
                <h3>Summary</h3>
                <div id="summary-stats"></div>
            </div>
        </div>

        <h2>Videos (Source)</h2>
        <div class="card">
            <ul class="file-list" id="video-list"></ul>
        </div>

        <h2>Audio Files (Work Folder)</h2>
        <div class="card">
            <ul class="file-list" id="audio-list"></ul>
        </div>

        <h2>Transcriptions (Output)</h2>
        <div class="card">
            <ul class="file-list" id="transcription-list"></ul>
        </div>

        <p class="refresh-info">Auto-refreshes every 5 seconds | Last update: <span id="last-update"></span></p>
    </div>

    <script>
        async function fetchStatus() {
            try {
                const resp = await fetch('/api/status');
                const data = await resp.json();
                updateUI(data);
            } catch (e) {
                console.error('Failed to fetch status:', e);
            }
        }

        function updateUI(data) {
            // Config
            document.getElementById('config-stats').innerHTML = `
                <div class="stat"><span class="stat-label">Video Folder</span><span class="stat-value">${data.config.video_folder}</span></div>
                <div class="stat"><span class="stat-label">Work Folder</span><span class="stat-value">${data.config.work_folder}</span></div>
                <div class="stat"><span class="stat-label">Output Folder</span><span class="stat-value">${data.config.output_folder}</span></div>
                <div class="stat"><span class="stat-label">Stability Window</span><span class="stat-value">${data.config.stability_window}s</span></div>
                <div class="stat"><span class="stat-label">Scan Interval</span><span class="stat-value">${data.config.scan_interval}s</span></div>
            `;

            // Summary
            const pendingVideos = data.videos.filter(v => !v.transcribed).length;
            const completedTranscriptions = data.transcriptions.length;
            document.getElementById('summary-stats').innerHTML = `
                <div class="stat"><span class="stat-label">Videos Found</span><span class="stat-value">${data.videos.length}</span></div>
                <div class="stat"><span class="stat-label">Audio Files</span><span class="stat-value">${data.audio_files.length}</span></div>
                <div class="stat"><span class="stat-label">Transcriptions</span><span class="stat-value">${completedTranscriptions}</span></div>
                <div class="stat"><span class="stat-label">Pending</span><span class="stat-value">${pendingVideos}</span></div>
            `;

            // Current progress
            const progressCard = document.getElementById('current-progress');
            if (data.in_progress) {
                progressCard.style.display = 'block';
                document.getElementById('current-file').textContent = data.in_progress.file;
                document.getElementById('progress-fill').style.width = data.in_progress.percent + '%';
                document.getElementById('progress-text').textContent =
                    `Started: ${data.in_progress.started}`;
            } else {
                progressCard.style.display = 'none';
            }

            // Videos
            const videoList = document.getElementById('video-list');
            if (data.videos.length === 0) {
                videoList.innerHTML = '<li class="empty">No videos found</li>';
            } else {
                videoList.innerHTML = data.videos.map(v => `
                    <li class="file-item">
                        <span class="file-name">${v.name}</span>
                        <span class="file-meta">${v.size_mb} MB</span>
                        ${v.transcribed
                            ? '<span class="badge badge-done">Done</span>'
                            : v.audio_converted
                                ? '<span class="badge badge-progress">Converting</span>'
                                : '<span class="badge badge-pending">Pending</span>'}
                    </li>
                `).join('');
            }

            // Audio files
            const audioList = document.getElementById('audio-list');
            if (data.audio_files.length === 0) {
                audioList.innerHTML = '<li class="empty">No audio files</li>';
            } else {
                audioList.innerHTML = data.audio_files.map(a => `
                    <li class="file-item">
                        <span class="file-name">${a.name}</span>
                        <span class="file-meta">${a.size_mb} MB</span>
                        ${a.transcribed
                            ? '<span class="badge badge-done">Done</span>'
                            : '<span class="badge badge-pending">Pending</span>'}
                    </li>
                `).join('');
            }

            // Transcriptions
            const transcriptionList = document.getElementById('transcription-list');
            if (data.transcriptions.length === 0) {
                transcriptionList.innerHTML = '<li class="empty">No transcriptions yet</li>';
            } else {
                transcriptionList.innerHTML = data.transcriptions.map(t => `
                    <li class="file-item">
                        <span class="file-name">${t.name}</span>
                        <span class="file-meta">${(t.size_bytes / 1024).toFixed(1)} KB | ${t.duration}s</span>
                        <span class="badge badge-done">Done</span>
                    </li>
                `).join('');
            }

            // Last update
            document.getElementById('last-update').textContent = new Date().toLocaleTimeString();
        }

        // Initial fetch and set interval
        fetchStatus();
        setInterval(fetchStatus, 5000);
    </script>
</body>
</html>
"""


def main():
    print(f"Starting Transcription Progress Dashboard on http://localhost:{PORT}")
    print("Press Ctrl+C to stop")

    server = HTTPServer(("", PORT), DashboardHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()


if __name__ == "__main__":
    main()
