#!/usr/bin/env python3
"""Local FFmpeg renderer for Carousel Builder. Uses only the Python standard library."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parent
MAX_SOURCE_BYTES = 2 * 1024 * 1024 * 1024
MAX_OVERLAY_BYTES = 32 * 1024 * 1024
OUTPUT_WIDTH = 1080
OUTPUT_HEIGHT = 1350
jobs: dict[str, dict] = {}
jobs_lock = threading.Lock()


def ffmpeg_path() -> str | None:
    configured = os.environ.get("FFMPEG")
    return shutil.which(configured) if configured else shutil.which("ffmpeg")


def encoder_support() -> dict:
    binary = ffmpeg_path()
    if not binary:
        return {"available": False, "encoders": [], "error": "FFmpeg não foi encontrado no PATH."}
    try:
        result = subprocess.run(
            [binary, "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return {"available": False, "encoders": [], "error": str(error)}
    names = set(re.findall(r"^\s*[VAS.DX]{6}\s+(\S+)", result.stdout, re.MULTILINE))
    encoders = [name for name in ("h264_nvenc", "h264_amf", "libx264") if name in names]
    if result.returncode or not encoders:
        return {"available": False, "encoders": encoders, "error": "FFmpeg não oferece NVENC, AMF nem libx264."}
    return {"available": True, "encoders": encoders}


def send_json(handler: SimpleHTTPRequestHandler, status: int, data: dict) -> None:
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def finite_number(config: dict, key: str, minimum: float, maximum: float) -> float:
    value = config.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"Parâmetro inválido: {key}.")
    if value < minimum or value > maximum:
        raise ValueError(f"Parâmetro fora do limite: {key}.")
    return float(value)


def copy_request_part(source, destination: Path, length: int) -> None:
    remaining = length
    with destination.open("wb") as target:
        while remaining:
            chunk = source.read(min(1024 * 1024, remaining))
            if not chunk:
                raise ValueError("Upload interrompido antes do fim do arquivo.")
            target.write(chunk)
            remaining -= len(chunk)


def encoder_options(name: str) -> list[str]:
    if name == "h264_nvenc":
        return ["-preset", "p5", "-tune", "hq", "-rc", "vbr", "-cq", "18", "-b:v", "0"]
    if name == "h264_amf":
        return ["-quality", "quality", "-rc", "cqp", "-qp_i", "18", "-qp_p", "18", "-qp_b", "20"]
    return ["-preset", "veryfast", "-crf", "18"]


def build_ffmpeg_args(job: dict, encoder: str) -> list[str]:
    config = job["config"]
    base = (
        f"[0:v]scale={int(config['width'])}:{int(config['height'])}:flags=lanczos,"
        f"crop={OUTPUT_WIDTH}:{OUTPUT_HEIGHT}:{int(config['cropX'])}:{int(config['cropY'])},setsar=1[base]"
    )
    label = "[base]"
    args = [
        ffmpeg_path() or "ffmpeg",
        "-hide_banner", "-loglevel", "error", "-y", "-progress", "pipe:1", "-nostats",
        "-ss", f"{config['trimStart']:.3f}", "-i", str(job["source"]),
    ]
    overlay = config.get("overlay")
    if overlay:
        args.extend(["-loop", "1", "-i", str(job["overlay_path"])])
        base += (
            f";[1:v]scale={int(overlay['width'])}:{int(overlay['height'])}:flags=lanczos[ov];"
            f"[base][ov]overlay={int(overlay['x'])}:{int(overlay['y'])}:shortest=1:format=auto[v]"
        )
        label = "[v]"
    args.extend([
        "-filter_complex", base,
        "-map", label, "-map", "0:a?",
        "-t", f"{config['trimEnd'] - config['trimStart']:.3f}",
        "-c:v", encoder, *encoder_options(encoder),
        "-pix_fmt", "yuv420p", "-profile:v", "high",
        "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
        str(job["output"]),
    ])
    return args


def set_job(job_id: str, **changes) -> None:
    with jobs_lock:
        job = jobs.get(job_id)
        if job:
            job.update(changes)
            job["updated"] = time.monotonic()


def run_encoder(job_id: str, job: dict, encoder: str) -> tuple[int, str]:
    duration = job["config"]["trimEnd"] - job["config"]["trimStart"]
    log_path = job["directory"] / f"{encoder}.log"
    set_job(job_id, phase="encoding", fraction=0.0, encoder=encoder, message=f"Codificando com {encoder}…")
    args = build_ffmpeg_args(job, encoder)
    try:
        with log_path.open("w", encoding="utf-8") as error_log:
            process = subprocess.Popen(
                args,
                stdout=subprocess.PIPE,
                stderr=error_log,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
            set_job(job_id, process=process)
            assert process.stdout is not None
            for line in process.stdout:
                key, separator, value = line.strip().partition("=")
                if not separator or key not in ("out_time_us", "out_time_ms"):
                    continue
                try:
                    elapsed = max(0.0, float(value) / 1_000_000)
                except ValueError:
                    continue
                set_job(job_id, fraction=min(0.99, elapsed / duration))
            code = process.wait()
    except OSError as error:
        return 127, str(error)
    if code == 0:
        return 0, ""
    try:
        message = log_path.read_text(encoding="utf-8", errors="replace")[-4000:].strip()
    except OSError:
        message = f"FFmpeg terminou com código {code}."
    return code, message


def render_job(job_id: str) -> None:
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        return
    support = encoder_support()
    if not support["available"]:
        set_job(job_id, phase="error", error=support.get("error", "FFmpeg indisponível."))
        return
    candidates = [name for name in ("h264_nvenc", "h264_amf", "libx264") if name in support["encoders"]]
    failures = []
    for encoder in candidates:
        code, message = run_encoder(job_id, job, encoder)
        if code == 0:
            label = {"h264_nvenc": "NVIDIA NVENC", "h264_amf": "AMD AMF", "libx264": "CPU (libx264)"}[encoder]
            set_job(job_id, phase="done", fraction=1.0, engine=label, encoder=encoder, process=None)
            return
        failures.append(f"{encoder}: {message or f'código {code}'}")
        try:
            job["output"].unlink(missing_ok=True)
        except OSError:
            pass
        set_job(job_id, process=None, message=f"{encoder} indisponível; tentando o próximo encoder…")
    set_job(job_id, phase="error", error="; ".join(failures) or "Nenhum encoder H.264 funcional foi encontrado.", process=None)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, format_string: str, *args) -> None:
        print(f"[{self.log_date_time_string()}] {format_string % args}")

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path == "/api/capabilities":
            send_json(self, 200, encoder_support())
            return
        match = re.fullmatch(r"/api/jobs/([0-9a-f]{32})(/result)?", path)
        if match:
            job_id, result_path = match.groups()
            with jobs_lock:
                job = jobs.get(job_id)
            if not job:
                send_json(self, 404, {"error": "Renderização não encontrada ou já removida."})
                return
            if not result_path:
                send_json(self, 200, {
                    "phase": job["phase"], "fraction": job.get("fraction", 0),
                    "message": job.get("message", "Aguardando encoder…"),
                    "engine": job.get("engine"), "encoder": job.get("encoder"), "error": job.get("error"),
                })
                return
            if job["phase"] != "done":
                send_json(self, 409, {"error": "A renderização ainda não terminou."})
                return
            try:
                size = job["output"].stat().st_size
                self.send_response(200)
                self.send_header("Content-Type", "video/mp4")
                self.send_header("Content-Length", str(size))
                self.end_headers()
                with job["output"].open("rb") as source:
                    shutil.copyfileobj(source, self.wfile, 1024 * 1024)
            finally:
                with jobs_lock:
                    removed = jobs.pop(job_id, None)
                if removed:
                    removed["temporary"].cleanup()
            return
        if path in ("/", "/index.html"):
            self.path = "/index.html"
            super().do_GET()
            return
        self.send_error(404, "Not found")

    def do_POST(self) -> None:
        if urlsplit(self.path).path != "/api/jobs":
            self.send_error(404, "Not found")
            return
        try:
            source_size = int(self.headers.get("X-Source-Size", "0"))
            overlay_size = int(self.headers.get("X-Overlay-Size", "0"))
            content_length = int(self.headers.get("Content-Length", "-1"))
            if not 0 < source_size <= MAX_SOURCE_BYTES or not 0 <= overlay_size <= MAX_OVERLAY_BYTES:
                raise ValueError("Tamanho de mídia fora do limite permitido.")
            if content_length != source_size + overlay_size:
                raise ValueError("Tamanho do upload não corresponde aos metadados.")
            config = json.loads(unquote(self.headers.get("X-Render-Options", "")))
            config["trimStart"] = finite_number(config, "trimStart", 0, 86400)
            config["trimEnd"] = finite_number(config, "trimEnd", 0.01, 86400)
            config["width"] = finite_number(config, "width", OUTPUT_WIDTH, 30000)
            config["height"] = finite_number(config, "height", OUTPUT_HEIGHT, 30000)
            config["cropX"] = finite_number(config, "cropX", 0, 30000)
            config["cropY"] = finite_number(config, "cropY", 0, 30000)
            if config["trimEnd"] <= config["trimStart"]:
                raise ValueError("O fim do corte precisa ser posterior ao início.")
            extension = config.get("extension", "").lower()
            if not re.fullmatch(r"[a-z0-9]{1,8}", extension):
                extension = "media"
            overlay = config.get("overlay")
            if bool(overlay) != bool(overlay_size):
                raise ValueError("Os dados do overlay não correspondem ao upload.")
            if overlay:
                for key, minimum, maximum in (("width", 1, 30000), ("height", 1, 30000), ("x", -30000, 30000), ("y", -30000, 30000)):
                    overlay[key] = finite_number(overlay, key, minimum, maximum)
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            send_json(self, 400, {"error": str(error) or "Opções de renderização inválidas."})
            return

        temporary = tempfile.TemporaryDirectory(prefix="dd-carru-")
        directory = Path(temporary.name)
        source_path = directory / f"source.{extension}"
        overlay_path = directory / "overlay.png"
        output_path = directory / "output.mp4"
        try:
            copy_request_part(self.rfile, source_path, source_size)
            if overlay_size:
                copy_request_part(self.rfile, overlay_path, overlay_size)
        except (OSError, ValueError) as error:
            temporary.cleanup()
            send_json(self, 400, {"error": str(error)})
            return

        job_id = uuid.uuid4().hex
        job = {
            "config": config, "source": source_path, "overlay_path": overlay_path,
            "output": output_path, "directory": directory, "temporary": temporary,
            "phase": "queued", "fraction": 0.0, "updated": time.monotonic(),
        }
        with jobs_lock:
            jobs[job_id] = job
        threading.Thread(target=render_job, args=(job_id,), daemon=True).start()
        send_json(self, 202, {"id": job_id})

    def do_DELETE(self) -> None:
        match = re.fullmatch(r"/api/jobs/([0-9a-f]{32})", urlsplit(self.path).path)
        if not match:
            self.send_error(404, "Not found")
            return
        with jobs_lock:
            job = jobs.pop(match.group(1), None)
        if job:
            process = job.get("process")
            if process and process.poll() is None:
                process.terminate()
            job["temporary"].cleanup()
        send_json(self, 200, {"deleted": bool(job)})


def main() -> None:
    parser = argparse.ArgumentParser(description="Local NVIDIA/AMD/CPU renderer for Carousel Builder")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true", help="Não abrir o navegador automaticamente")
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("A porta deve estar entre 1024 e 65535.")
    address = f"http://127.0.0.1:{args.port}/"
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.daemon_threads = True
    support = encoder_support()
    if support["available"]:
        print("Encoders FFmpeg: " + ", ".join(support["encoders"]))
    else:
        print("FFmpeg nativo indisponível: " + support.get("error", "instale FFmpeg com encoder H.264."))
        print("A página ainda abre; vídeos podem ser exportados pelo FFmpeg.wasm no navegador.")
    print(f"Carousel Builder: {address} (somente este computador)")
    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(address)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor encerrado.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
