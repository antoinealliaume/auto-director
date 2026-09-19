#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Deterministic continuous audit for Auto Director.

This script never edits production code. It inspects the repository, runs safe
checks, and emits a Markdown + JSON report consumed by GitHub Actions and the
hourly ChatGPT maintenance task.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "audit"
REPORT_MD = REPORT_DIR / "AUTO_DIRECTOR_AUDIT.md"
REPORT_JSON = REPORT_DIR / "AUTO_DIRECTOR_AUDIT.json"

checks: list[dict] = []
findings: list[dict] = []


def add_finding(severity: str, category: str, title: str, detail: str, suggestion: str = "") -> None:
    findings.append(
        {
            "severity": severity,
            "category": category,
            "title": title,
            "detail": detail[:4000],
            "suggestion": suggestion[:2000],
        }
    )


def run_check(name: str, cmd: list[str], *, env: dict[str, str] | None = None, timeout: int = 300) -> bool:
    merged = os.environ.copy()
    if env:
        merged.update(env)
    try:
        proc = subprocess.run(
            cmd,
            cwd=ROOT,
            env=merged,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
        )
        output = (proc.stdout + "\n" + proc.stderr).strip()
        checks.append({"name": name, "ok": proc.returncode == 0, "code": proc.returncode, "output": output[-5000:]})
        if proc.returncode != 0:
            add_finding("critical", "checks", f"Échec: {name}", output[-1800:] or f"code={proc.returncode}", "Corriger avant toute fusion vers main.")
        return proc.returncode == 0
    except subprocess.TimeoutExpired as exc:
        checks.append({"name": name, "ok": False, "code": -1, "output": f"timeout after {timeout}s"})
        add_finding("critical", "checks", f"Timeout: {name}", str(exc), "Identifier le test ou processus bloqué.")
        return False
    except Exception as exc:  # report tool failure without aborting the audit
        checks.append({"name": name, "ok": False, "code": -2, "output": f"{type(exc).__name__}: {exc}"})
        add_finding("warning", "checks", f"Contrôle indisponible: {name}", f"{type(exc).__name__}: {exc}")
        return False


def git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:
        return "unknown"


def text(path: str) -> str:
    p = ROOT / path
    return p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""


def audit_runtime() -> None:
    run_check(
        "Python compileall",
        [sys.executable, "-m", "compileall", "-q", "app", "engine", "self_hosted_worker", "worker.py", "storage_backend.py", "storage_schema.py"],
        timeout=180,
    )
    run_check(
        "Core unit tests",
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
        env={
            "DATABASE_URL": "postgresql://unused:unused@127.0.0.1:5432/unused",
            "REDIS_URL": "redis://127.0.0.1:6379/0",
        },
        timeout=420,
    )
    run_check("pip dependency consistency", [sys.executable, "-m", "pip", "check"], timeout=120)

    node = shutil.which("node")
    if node:
        js_files = sorted((ROOT / "app" / "static").glob("*.js"))
        for file in js_files:
            run_check(f"JS syntax: {file.name}", [node, "--check", str(file)], timeout=60)
    else:
        add_finding("info", "checks", "Node.js indisponible", "Le contrôle de syntaxe JavaScript a été ignoré sur cet environnement.")

    pwsh = shutil.which("pwsh") or shutil.which("powershell")
    if pwsh:
        ps_files = sorted(list((ROOT / "app").rglob("*.ps1")) + list((ROOT / "self_hosted_worker").rglob("*.ps1")))
        for file in ps_files:
            escaped = str(file).replace("'", "''")
            command = (
                "$tokens=$null;$errors=$null;"
                f"[System.Management.Automation.Language.Parser]::ParseFile('{escaped}',[ref]$tokens,[ref]$errors)|Out-Null;"
                "if($errors.Count -gt 0){$errors|ForEach-Object{Write-Error $_.Message};exit 1}"
            )
            run_check(f"PowerShell syntax: {file.relative_to(ROOT)}", [pwsh, "-NoProfile", "-Command", command], timeout=60)
    else:
        add_finding("info", "checks", "PowerShell indisponible", "Le contrôle PowerShell a été ignoré sur cet environnement.")

    ruff = shutil.which("ruff")
    if ruff:
        run_check(
            "Ruff fatal/static errors",
            [ruff, "check", "app", "engine", "self_hosted_worker", "worker.py", "storage_backend.py", "storage_schema.py", "--select", "E9,F63,F7,F82"],
            timeout=180,
        )
    else:
        add_finding("info", "quality", "Ruff indisponible", "Installer ruff dans le job d'audit pour détecter les erreurs statiques Python.")

    pip_audit = shutil.which("pip-audit")
    if pip_audit:
        run_check("Dependency vulnerability audit", [pip_audit, "-r", "requirements.txt", "--progress-spinner", "off"], timeout=300)
    else:
        add_finding("info", "security", "pip-audit indisponible", "Installer pip-audit dans le job d'audit pour vérifier les vulnérabilités connues.")


def audit_versions() -> None:
    sources = {
        "local_agent": text("self_hosted_worker/local_agent.ps1"),
        "installer_ps1": text("app/static/Install-AutoDirector.ps1"),
        "installer_bat": text("app/static/INSTALL_AUTO_DIRECTOR_WORKER.bat"),
    }
    values: dict[str, str] = {}
    patterns = {
        "agent": ("local_agent", r"\$AgentVersion\s*=\s*['\"]([0-9.]+)['\"]"),
        "expected": ("installer_ps1", r"\$ExpectedAgentVersion\s*=\s*\[version\]['\"]([0-9.]+)['\"]"),
        "zip_cache": ("installer_ps1", r"main\.zip\?v=([0-9.]+)"),
        "bat_cache": ("installer_bat", r"Install-AutoDirector\.ps1\?v=([0-9.]+)"),
        "bat_banner": ("installer_bat", r"WORKER PC\s+([0-9.]+)"),
    }
    for key, (source, pattern) in patterns.items():
        match = re.search(pattern, sources[source], flags=re.I)
        if match:
            values[key] = match.group(1)
        else:
            add_finding("warning", "versions", f"Version introuvable: {key}", f"Pattern absent dans {source}.")
    if values and len(set(values.values())) > 1:
        add_finding("critical", "versions", "Versions worker/installer désynchronisées", json.dumps(values, ensure_ascii=False), "Aligner AgentVersion, ExpectedAgentVersion et les cache-busters des installateurs.")
    elif values:
        checks.append({"name": "Worker installer version alignment", "ok": True, "code": 0, "output": json.dumps(values, ensure_ascii=False)})


def audit_security_and_debt() -> None:
    env_example = text("self_hosted_worker/.env.example")
    active_cloud_secrets = []
    for line in env_example.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and re.match(r"^(DATABASE_URL|REDIS_URL)\s*=", stripped):
            active_cloud_secrets.append(stripped.split("=", 1)[0])
    if active_cloud_secrets:
        add_finding("critical", "security", "Secrets cloud configurables sur le worker PC", ", ".join(active_cloud_secrets), "Le worker PC de production doit rester HTTPS-only avec jeton temporaire.")

    legacy_files = [
        "app/main.py.new",
        "app/main_v7.py",
        "app/ACTIVATE_V7_NOW",
        "app/README_V7_SWITCH.txt",
        "app/STOP_PLACEHOLDER",
        "app/activate_v7.txt",
    ]
    present = [p for p in legacy_files if (ROOT / p).exists()]
    if present:
        add_finding(
            "warning",
            "maintenance",
            "Artefacts legacy présents",
            "\n".join(present),
            "Vérifier qu'ils ne sont plus référencés puis les supprimer dans une PR dédiée si sûrs.",
        )

    markers: list[str] = []
    excluded = {".git", ".venv", ".venv-local", "__pycache__", "audit"}
    for base in [ROOT / "app", ROOT / "engine", ROOT / "self_hosted_worker", ROOT / "tests"]:
        if not base.exists():
            continue
        for p in base.rglob("*"):
            if not p.is_file() or any(part in excluded for part in p.parts) or p.suffix.lower() not in {".py", ".js", ".ps1", ".html", ".md"}:
                continue
            try:
                for no, line in enumerate(p.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                    if re.search(r"\b(TODO|FIXME|HACK|XXX)\b", line, re.I):
                        markers.append(f"{p.relative_to(ROOT)}:{no}: {line.strip()[:180]}")
                        if len(markers) >= 40:
                            break
            except Exception:
                pass
            if len(markers) >= 40:
                break
        if len(markers) >= 40:
            break
    if markers:
        add_finding("info", "maintenance", f"{len(markers)} marqueur(s) TODO/FIXME/HACK", "\n".join(markers), "Trier les marqueurs réellement actionnables et ignorer les commentaires historiques.")


def write_report() -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    counts = {s: sum(1 for f in findings if f["severity"] == s) for s in ("critical", "warning", "info")}
    failed_checks = sum(1 for c in checks if not c.get("ok"))
    status = "CRITICAL" if counts["critical"] or failed_checks else ("WARNING" if counts["warning"] else "OK")
    payload = {
        "generatedAt": now,
        "repository": "antoinealliaume/auto-director",
        "commit": git_sha(),
        "status": status,
        "counts": counts,
        "failedChecks": failed_checks,
        "checks": checks,
        "findings": findings,
    }
    REPORT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# Auto Director — Continuous Audit",
        "",
        f"- Généré : `{now}`",
        f"- Commit audité : `{payload['commit']}`",
        f"- État : **{status}**",
        f"- Critiques : **{counts['critical']}** · Avertissements : **{counts['warning']}** · Infos : **{counts['info']}** · Contrôles échoués : **{failed_checks}**",
        "",
        "## Priorités proposées",
        "",
    ]
    ordered = {"critical": 0, "warning": 1, "info": 2}
    if not findings:
        lines.append("Aucune anomalie statique détectée par les contrôles actuels.")
    else:
        for f in sorted(findings, key=lambda x: ordered.get(x["severity"], 9)):
            icon = {"critical": "🔴", "warning": "🟠", "info": "🔵"}.get(f["severity"], "•")
            lines.extend([f"### {icon} {f['title']}", f"**Catégorie :** {f['category']}", "", f["detail"], ""])
            if f.get("suggestion"):
                lines.extend([f"**Action proposée :** {f['suggestion']}", ""])

    lines.extend(["## Contrôles automatiques", ""])
    for c in checks:
        mark = "✅" if c.get("ok") else "❌"
        lines.append(f"- {mark} **{c['name']}** (code `{c.get('code')}`)")
    lines.extend(
        [
            "",
            "## Règles d'automatisation",
            "",
            "- Ce rapport ne modifie jamais `main`.",
            "- Les corrections automatiques doivent être faites sur une branche dédiée avec PR.",
            "- Aucun merge automatique pour les changements de sécurité, OAuth TikTok, stockage, base de données, publication ou architecture worker.",
            "- Une absence de finding ne prouve pas l'absence de bug : l'audit est un filet de sécurité, pas une preuve formelle.",
            "",
        ]
    )
    REPORT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"status": status, "counts": counts, "failedChecks": failed_checks}, ensure_ascii=False))


def main() -> int:
    audit_runtime()
    audit_versions()
    audit_security_and_debt()
    write_report()
    return 0  # findings are published; CI remains the hard release gate


if __name__ == "__main__":
    raise SystemExit(main())
