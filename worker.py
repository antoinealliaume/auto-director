import asyncio
import base64
import json
import math
import os
import re
import statistics
import subprocess
import tempfile
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import httpx
import psycopg
import redis
from edge_tts import Communicate
from imageio_ffmpeg import get_ffmpeg_exe
from psycopg.types.json import Jsonb

ENGINE_VERSION = "8.0"
ANALYSIS_VERSION = 2
DATABASE_URL = os.environ["DATABASE_URL"]
REDIS_URL = os.environ["REDIS_URL"]
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
AI_MODEL = os.environ.get("AI_MODEL", "gpt-5.6-luna")
RENDER_WIDTH = int(os.environ.get("RENDER_WIDTH", "720"))
RENDER_HEIGHT = int(os.environ.get("RENDER_HEIGHT", "1280"))
SELF_TEST_ON_START = os.environ.get("SELF_TEST_ON_START", "0") == "1"
MAX_REVISIONS = max(0, min(2, int(os.environ.get("MAX_REVISIONS", "1"))))
MOMENT_SAMPLES = max(4, min(14, int(os.environ.get("MOMENT_SAMPLES", "9"))))
FFMPEG = get_ffmpeg_exe()
queue = redis.from_url(REDIS_URL, decode_responses=True)


def db():
    return psycopg.connect(DATABASE_URL)


def ensure_schema():
    with db() as c:
        stmts = [
            "alter table projects add column if not exists description text not null default ''",
            "alter table assets add column if not exists metadata jsonb not null default '{}'::jsonb",
            "alter table jobs add column if not exists critic_score double precision",
            "alter table jobs add column if not exists revision_count int not null default 0",
            "alter table jobs add column if not exists strategy text not null default ''",
            "alter table jobs add column if not exists creative_brief jsonb not null default '{}'::jsonb",
            "alter table trends add column if not exists source_url text not null default ''",
            "create table if not exists job_events(id bigserial primary key,job_id uuid references jobs(id) on delete cascade,stage text not null,message text not null,created_at timestamptz not null default now())",
        ]
        for stmt in stmts:
            try:
                c.execute(stmt)
            except Exception:
                pass
        try:
            c.execute("update trends set source_url=url where source_url='' and coalesce(url,'')<>''")
        except Exception:
            pass


def run(cmd, timeout=900, check=True):
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout)
    if check and p.returncode != 0:
        raise RuntimeError((p.stderr or p.stdout or "")[-5000:])
    return p


def update(jid, status, stage, progress, message, score=None, revision=None, strategy=None, brief=None):
    sets = ["status=%s", "stage=%s", "progress=%s", "message=%s", "updated_at=now()"]
    vals = [status, stage, int(progress), str(message)[:500]]
    if score is not None:
        sets.append("critic_score=%s")
        vals.append(float(score))
    if revision is not None:
        sets.append("revision_count=%s")
        vals.append(int(revision))
    if strategy is not None:
        sets.append("strategy=%s")
        vals.append(str(strategy)[:120])
    if brief is not None:
        sets.append("creative_brief=%s")
        vals.append(Jsonb(brief))
    vals.append(jid)
    with db() as c:
        c.execute("update jobs set " + ",".join(sets) + " where id=%s", vals)
        try:
            c.execute("insert into job_events(job_id,stage,message) values(%s,%s,%s)", (jid, stage, str(message)[:500]))
        except Exception:
            pass


def media_info(path: Path):
    p = run([FFMPEG, "-hide_banner", "-i", str(path)], timeout=45, check=False)
    text = p.stderr or ""
    m = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", text)
    duration = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else 0.0
    vm = re.search(r"Video:.*?(\d{2,5})x(\d{2,5})", text)
    res = [int(vm.group(1)), int(vm.group(2))] if vm else [0, 0]
    return duration, "Audio:" in text, res


def scene_cuts(path: Path, max_seconds=60):
    p = run(
        [FFMPEG, "-hide_banner", "-t", str(max_seconds), "-i", str(path), "-vf", "select='gt(scene,0.27)',showinfo", "-an", "-f", "null", "-"],
        timeout=180,
        check=False,
    )
    vals = [float(x) for x in re.findall(r"pts_time:([0-9.]+)", p.stderr or "")]
    out = []
    for x in vals:
        if x < 0.45:
            continue
        if not out or x - out[-1] >= 0.45:
            out.append(round(x, 2))
        if len(out) >= 28:
            break
    return out


def black_ratio(path: Path, duration: float, start=0.0, sample=None):
    span = sample if sample is not None else min(max(duration, 1.0), 24.0)
    p = run(
        [FFMPEG, "-hide_banner", "-ss", str(max(0, start)), "-t", str(max(0.4, span)), "-i", str(path), "-vf", "blackdetect=d=0.10:pix_th=0.08", "-an", "-f", "null", "-"],
        timeout=120,
        check=False,
    )
    spans = re.findall(r"black_start:([\d.]+)\s+black_end:([\d.]+)", p.stderr or "")
    black = sum(max(0, float(b) - float(a)) for a, b in spans)
    return min(1.0, black / max(span, 0.1))


def freeze_ratio(path: Path, duration: float):
    span = min(max(duration, 1.0), 24.0)
    p = run(
        [FFMPEG, "-hide_banner", "-t", str(span), "-i", str(path), "-vf", "freezedetect=n=-45dB:d=0.35", "-an", "-f", "null", "-"],
        timeout=120,
        check=False,
    )
    starts = [float(x) for x in re.findall(r"freeze_start:\s*([\d.]+)", p.stderr or "")]
    ends = [float(x) for x in re.findall(r"freeze_end:\s*([\d.]+)", p.stderr or "")]
    frozen = 0.0
    for i, a in enumerate(starts):
        b = ends[i] if i < len(ends) else span
        frozen += max(0, min(span, b) - a)
    return min(1.0, frozen / max(span, 0.1))


def has_drawtext():
    try:
        return "drawtext" in run([FFMPEG, "-hide_banner", "-filters"], timeout=30, check=False).stdout
    except Exception:
        return False


DRAWTEXT = has_drawtext()


def extract_frame(path: Path, at: float, out: Path):
    run([FFMPEG, "-y", "-ss", str(max(0, at)), "-i", str(path), "-frames:v", "1", "-vf", "scale=512:-2", str(out)], timeout=90)
    return out


def image_data_url(path: Path):
    return "data:image/jpeg;base64," + base64.b64encode(path.read_bytes()).decode()


def sample_motion(path: Path, at: float):
    p = run(
        [
            FFMPEG,
            "-hide_banner",
            "-ss",
            str(max(0, at)),
            "-t",
            "0.9",
            "-i",
            str(path),
            "-vf",
            "fps=7,tblend=all_mode=difference,signalstats,metadata=print",
            "-an",
            "-f",
            "null",
            "-",
        ],
        timeout=60,
        check=False,
    )
    vals = [float(x) for x in re.findall(r"lavfi\.signalstats\.YAVG=([\d.]+)", (p.stdout or "") + "\n" + (p.stderr or ""))]
    if not vals:
        return 0.35
    raw = statistics.mean(vals)
    return round(max(0.0, min(1.0, raw / 30.0)), 3)


def sample_audio(path: Path, at: float, has_audio: bool):
    if not has_audio:
        return 0.0
    p = run(
        [FFMPEG, "-hide_banner", "-ss", str(max(0, at)), "-t", "1.2", "-i", str(path), "-vn", "-af", "volumedetect", "-f", "null", "-"],
        timeout=60,
        check=False,
    )
    m = re.search(r"mean_volume:\s*(-?[\d.]+) dB", p.stderr or "")
    if not m:
        return 0.35
    dbv = float(m.group(1))
    return round(max(0.0, min(1.0, (dbv + 42.0) / 34.0)), 3)


def candidate_points(duration, cuts):
    pts = [0.35]
    for cut in cuts:
        pts.extend([max(0.0, cut - 0.55), cut + 0.05])
    if duration > 3:
        pts.extend([duration * x for x in (0.14, 0.29, 0.47, 0.64, 0.79)])
    pts = [round(max(0.0, min(max(0.0, duration - 1.0), p)), 2) for p in pts]
    unique = []
    for p in pts:
        if all(abs(p - x) >= 0.7 for x in unique):
            unique.append(p)
    if len(unique) <= MOMENT_SAMPLES:
        return unique
    # Prefer scene-adjacent moments while still covering the timeline.
    step = max(1, len(unique) // MOMENT_SAMPLES)
    sampled = unique[::step][:MOMENT_SAMPLES]
    if unique[-1] not in sampled and len(sampled) < MOMENT_SAMPLES:
        sampled.append(unique[-1])
    return sampled[:MOMENT_SAMPLES]


def moment_reason(-otion, audio, cut_bonus, black):
    reasons = []
    if motion >= 0.68:
        reasons.append("fort mouvement")
    if audio >= 0.66:
        reasons.append("audio intense")
    if cut_bonus >= 0.8:
        reasons.append("changement de sc√®ne")
    if black <= 0.02:
        reasons.append("image exploitable")
    return ", ".join(reasons[:3]) or "moment stable"


def analyze_asset(path: Path, asset_id: str, name: str, role: str, cached=None):
    cached = cached or {}
    prior = cached.get("directorAnalysis") if isinstance(cached, dict) else None
    if isinstance(prior, dict) and prior.get("version") == ANALYSIS_VERSION:
        result = dict(prior)
        result.update({"id": asset_id, "name": name, "role": role})
        return result, False

    duration, has_audio, res = media_info(path)
    cuts = scene_cuts(path)
    points = candidate_points(duration, cuts)
    moments = []
    for at in points:
        motion = sample_motion(path, at)
        audio = sample_audio(path, at, has_audio)
        nearest = min([abs(at - c) for c in cuts], default=9.0)
        cut_bonus = max(0.0, 1.0 - nearest / 1.4)
        black = black_ratio(path, duration, at, min(0.8, max(0.5, duration - at))) if duration > 0.7 else 0.0
        score = 100.0 * (0.45 * motion + 0.26 * audio + 0.19 * cut_bonus + 0.10 * (1.0 - black))
        moments.append(
            {
                "start": round(at, 2),
                "score": round(score, 1),
                "motion": motion,
                "audio": audio,
                "cutBonus": round(cut_bonus, 3),
                "black": round(black, 3),
                "reason": moment_reason(motion, audio, cut_bonus, black),
            }
        )
    moments.sort(key=lambda x: x["score"], reverse=True)
    gaps = []
    prev = 0.0
    for c in cuts:
        if 0.35 < c - prev < 8:
            gaps.append(c - prev)
        prev = c
    pace = statistics.median(gaps) if gaps else 2.2
    analysis = {
        "version": ANALYSIS_VERSION,
        "duration": round(duration, 2),
        "hasAudio": has_audio,
        "resolution": res,
        "cuts": cuts,
        "cutRate": round(len(cuts) / max(duration, 1.0), 3),
        "naturalPace": round(max(0.85, min(4.2, pace)), 2),
        "moments": moments[:8],
        "avgMomentScore": round(statistics.mean([m["score"] for m in moments[:6]]) if moments else 35.0, 1),
    }
    result = dict(analysis)
    result.update({"id": asset_id, "name": name, "role": role})
    return result, True


def update_asset_analysis(asset_id, old_metadata, analysis):
    meta = dict(old_metadata or {})
    compact = {k: v for k, v in analysis.items() if k not in {"id", "name", "role"}}
    meta["directorAnalysis"] = compact
    meta["engineVersion"] = ENGINE_VERSION
    with db() as c:
        c.execute("update assets set metadata=%s where id=%s", (Jsonb(meta), uuid.UUID(asset_id)))


def extract_openai_text(data):
    if isinstance(data, dict) and data.get("output_text"):
        return data["output_text"]
    chunks = []
    for out in (data or {}).get("output", []):
        for item in out.get("content", []) if isinstance(out, dict) else []:
            if isinstance(item, dict) and item.get("text"):
                chunks.append(item["text"])
    return "\n".join(chunks)


def parse_jsonish(text):
    if not text:
        return None
    text = text.strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            return None
    return None


def openai_response(prompt, images=None, max_output=1800):
    if not OPENAI_API_KEY:
        return None
    content = [{"type": "input_text", "text": prompt}]
    for img in images or []:
        content.append({"type": "input_image", "image_url": image_data_url(img)})
    payload = {"model": AI_MODEL, "input": [{"role": "user", "content": content}], "max_output_tokens": max_output}
    try:
        with httpx.Client(timeout=100) as client:
            r = client.post(
                "https://api.openai.com/v1/responses",
                headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
                json=payload,
            )
            r.raise_for_status()
            return extract_openai_text(r.json())
    except Exception as e:
        print("OpenAI fallback:", type(e).__name__, str(e)[:220], flush=True)
        return None


def get_context(project_id):
    with db() as c:
        perf = c.execute(
            """
            select a.name,a.metadata,coalesce(sum(f.views),0),coalesce(sum(f.likes),0),coalesce(sum(f.comments),0),
                   coalesce(sum(f.shares),0),coalesce(avg(f.completion),0),coalesce(sum(f.conversions),0)
            from assets a left join feedback f on f.asset_id=a.id
            where a.project_id=%s and a.kind='render'
            group by a.id,a.name,a.metadata
            order by coalesce(sum(f.views),0) desc limit 30
            """,
            (project_id,),
        ).fetchall()
        try:
            trends = c.execute("select label,coalesce(source_url,''),notes from trends order by created_at desc limit 10").fetchall()
        except Exception:
            trends = []
    rows = []
    strategy_scores = {}
    for name, meta, views, likes, comments, shares, completion, conversions in perf:
        views = int(views or 0)
        engagement = (float(likes or 0) + 2 * float(comments or 0) + 4 * float(shares or 0)) / max(views, 1)
        completion = float(completion or 0)
        value = min(2.0, math.log1p(views) / 10.0) + 4.0 * engagement + 2.5 * completion + 0.25 * float(conversions or 0)
        strategy = (meta or {}).get("strategy", "") if isinstance(meta, dict) else ""
        hook = (meta or {}).get("hook", "") if isinstance(meta, dict) else ""
        if strategy:
            strategy_scores.setdefault(strategy, []).append(value)
        rows.append({"name": name, "views": views, "completion": round(completion, 3), "engagement": round(engagement, 4), "strategy": strategy, "hook": hook[:100], "value": round(value, 3)})
    winners = sorted(((k, statistics.mean(v)) for k, v in strategy_scores.items()), key=lambda x: x[1], reverse=True)[:4]
    return {
        "performance": sorted(rows, key=lambda x: x["value"], reverse=True)[:10],
        "winningStrategies": [{"strategy": k, "score": round(v, 3)} for k, v["úuncated]