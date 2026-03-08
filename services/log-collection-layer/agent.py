"""
Log Collection Agent — watches a directory for log files and streams
ERROR lines to the Log Ingestion API in real time.

Usage:
  python agent.py --watch-dir /var/log/spark --job-id spark-etl-prod

Environment variables (override defaults):
  INGEST_URL      — ingestion API endpoint (default: http://localhost:8000/ingest)
  WATCH_DIR       — directory to monitor (overridden by --watch-dir flag)
  JOB_ID          — pipeline name (overridden by --job-id flag)
  WORKSPACE_ID    — tenant identifier (default: "default")
  SOURCE          — log source label (default: "agent")

The agent uses OS file-system events (via watchdog) so it reacts instantly
when new log files are created or existing files are appended to.
"""

import os
import sys
import time
import argparse
import requests
import threading
from datetime import datetime, timezone

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

_LAYER_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _LAYER_DIR)

from log_parser import parse_log_line, build_ingest_payload

# ── config ────────────────────────────────────────────────────────────────────

INGEST_URL   = os.getenv("INGEST_URL",    "http://localhost:8000/ingest")
WORKSPACE_ID = os.getenv("WORKSPACE_ID",  "default")
SOURCE       = os.getenv("SOURCE",        "agent")

# Only forward lines at this level or above (currently: ERROR only)
_FORWARD_LEVELS = {"ERROR"}


# ── file tail state ───────────────────────────────────────────────────────────

class _FileTailer:
    """Remembers file position and yields new lines on each poll/event."""

    def __init__(self, path: str):
        self.path = path
        self._pos = 0

    def read_new_lines(self) -> list[str]:
        try:
            with open(self.path, "r", errors="replace") as fh:
                fh.seek(self._pos)
                lines = fh.readlines()
                self._pos = fh.tell()
            return lines
        except OSError:
            return []


# ── ingestion ─────────────────────────────────────────────────────────────────

def send_to_ingest(payload: dict, ingest_url: str = INGEST_URL) -> bool:
    """POST one event to the ingestion API. Returns True on 2xx."""
    try:
        resp = requests.post(ingest_url, json=payload, timeout=10)
        return 200 <= resp.status_code < 300
    except Exception as e:
        print(f"[agent] Ingest POST failed: {e}", file=sys.stderr)
        return False


# ── watchdog handler ──────────────────────────────────────────────────────────

class LogDirectoryHandler(FileSystemEventHandler):
    """
    Reacts to file-created and file-modified events in the watched directory.
    One _FileTailer is kept per file so position is tracked across events.
    """

    def __init__(self, job_id: str, ingest_url: str = INGEST_URL):
        self.job_id = job_id
        self.ingest_url = ingest_url
        self._tailers: dict[str, _FileTailer] = {}
        self._lock = threading.Lock()

    def _get_tailer(self, path: str) -> _FileTailer:
        with self._lock:
            if path not in self._tailers:
                self._tailers[path] = _FileTailer(path)
                print(f"[agent] Watching new file: {path}")
            return self._tailers[path]

    def _process_file(self, path: str):
        if not path.endswith(".log") and not path.endswith(".txt"):
            return

        tailer = self._get_tailer(path)
        for line in tailer.read_new_lines():
            parsed = parse_log_line(line)
            if parsed is None:
                continue
            if parsed.level not in _FORWARD_LEVELS:
                continue

            payload = build_ingest_payload(
                parsed,
                job_id=self.job_id,
                source=SOURCE,
                workspace_id=WORKSPACE_ID,
            )
            ok = send_to_ingest(payload, self.ingest_url)
            status = "sent" if ok else "FAILED"
            print(
                f"[agent] [{status}] {parsed.timestamp} "
                f"pipeline={self.job_id} "
                f"message={parsed.message[:80]}"
            )

    def on_created(self, event):
        if not event.is_directory:
            self._process_file(event.src_path)

    def on_modified(self, event):
        if not event.is_directory:
            self._process_file(event.src_path)


# ── scan existing files on startup ────────────────────────────────────────────

def scan_existing(watch_dir: str, handler: LogDirectoryHandler):
    """Process any .log/.txt files already in the directory at startup."""
    for fname in os.listdir(watch_dir):
        if fname.endswith(".log") or fname.endswith(".txt"):
            handler._process_file(os.path.join(watch_dir, fname))


# ── main ──────────────────────────────────────────────────────────────────────

def run(watch_dir: str, job_id: str, ingest_url: str = INGEST_URL):
    """Start the agent. Blocks until KeyboardInterrupt."""
    os.makedirs(watch_dir, exist_ok=True)

    handler = LogDirectoryHandler(job_id=job_id, ingest_url=ingest_url)

    # Drain anything already on disk before watching for new events
    scan_existing(watch_dir, handler)

    observer = Observer()
    observer.schedule(handler, path=watch_dir, recursive=False)
    observer.start()

    print(f"[agent] Watching '{watch_dir}' for pipeline '{job_id}' → {ingest_url}")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        observer.stop()
        observer.join()
        print("[agent] Stopped.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Log Collection Agent")
    parser.add_argument(
        "--watch-dir",
        default=os.getenv("WATCH_DIR", "/tmp/pipeline-logs"),
        help="Directory to monitor for log files",
    )
    parser.add_argument(
        "--job-id",
        default=os.getenv("JOB_ID", "unknown-pipeline"),
        help="Pipeline name (job_id sent to ingestion API)",
    )
    parser.add_argument(
        "--ingest-url",
        default=INGEST_URL,
        help="Ingestion API URL",
    )
    args = parser.parse_args()

    run(watch_dir=args.watch_dir, job_id=args.job_id, ingest_url=args.ingest_url)
