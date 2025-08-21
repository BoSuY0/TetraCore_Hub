#!/usr/bin/env python3
"""
Secret/ENV scanner for the repository.

Features:
- Finds environment variable references (os.getenv/os.environ.get) and .env-style assignments
- Detects common secret/token patterns (AWS, GitHub, GitLab, Slack, Stripe, Google, Telegram)
- High-entropy detector for suspicious strings
- Supports excludes, size limits, JSON/text output, and non-zero exit on findings

Usage examples:
  python tools/secret_scan.py --root . --format json --fail-on-find
  python tools/secret_scan.py --root . --entropy-threshold 4.3 --min-length 20

Note: History scanning is not enabled by default to keep this fast.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable, List, Dict, Any, Tuple
import urllib.request
import urllib.error


DEFAULT_EXCLUDES = {
    ".git", "node_modules", ".venv", "venv", "__pycache__", ".mypy_cache",
    ".pytest_cache", "dist", "build", ".idea", ".vscode", "coverage",
}

TEXT_EXTENSIONS = {
    ".py", ".ts", ".tsx", ".js", ".jsx", ".json", ".yml", ".yaml", ".toml",
    ".ini", ".env", ".md", ".txt", ".cfg", ".conf", ".sql", ".sh", ".ps1",
}

# Regex patterns for secret-like tokens
SECRET_PATTERNS: Dict[str, re.Pattern[str]] = {
    "aws_access_key_id": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "aws_mfa_access_key": re.compile(r"\bASIA[0-9A-Z]{16}\b"),
    "github_pat": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36}\b"),
    "gitlab_pat": re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}\b"),
    "slack_token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    "stripe_secret": re.compile(r"\bsk_live_[A-Za-z0-9]{24}\b"),
    "google_api_key": re.compile(r"\bAIza[0-9A-Za-z-_]{35}\b"),
    "telegram_bot_token": re.compile(r"\b\d{9,10}:[A-Za-z0-9_-]{35}\b"),
}

# ENV name keywords likely to be secrets
ENV_SECRET_NAME = re.compile(
    r"\b(?:(?:SECRET|TOKEN|API_KEY|PASSWORD|PRIVATE_KEY|ENCRYPTION_KEY|ACCESS_KEY|SECRET_KEY|CLIENT_SECRET))\b",
    re.IGNORECASE,
)

# .env style line: KEY=VALUE
DOTENV_LINE = re.compile(r"^([A-Z][A-Z0-9_]{2,})\s*=\s*(.+)$")

# os.getenv / os.environ.get references
ENV_REF = re.compile(r"os\.(?:environ\.get|getenv)\(\s*['\"]([^'\"]+)['\"]")

# Quoted suspicious strings for entropy check
QUOTED_TOKEN = re.compile(r"['\"]([A-Za-z0-9_\-/+=\.]{20,})['\"]")


@dataclass
class Finding:
    path: str
    line: int
    kind: str
    match: str
    context: str
    rule: str
    severity: str


@dataclass
class IgnoreRule:
    field: str
    pattern: re.Pattern[str]


def is_probably_text(path: Path) -> bool:
    try:
        if path.suffix.lower() in TEXT_EXTENSIONS:
            return True
        # Heuristic for unknown extensions
        with path.open("rb") as f:
            chunk = f.read(4096)
            if b"\x00" in chunk:
                return False
            try:
                chunk.decode("utf-8")
                return True
            except Exception:
                return False
    except Exception:
        return False


def shannon_entropy(s: str) -> float:
    if not s:
        return 0.0
    # limit alphabet to conservative set to avoid skew
    data = [ord(c) for c in s]
    freq = {}
    for b in data:
        freq[b] = freq.get(b, 0) + 1
    ent = 0.0
    length = len(data)
    for c in freq.values():
        p = c / length
        ent -= p * math.log2(p)
    return ent


def iter_files(root: Path, excludes: Iterable[str], max_size_mb: int) -> Iterable[Path]:
    max_bytes = max_size_mb * 1024 * 1024
    for dirpath, dirnames, filenames in os.walk(root):
        # prune exclusions
        dirnames[:] = [d for d in dirnames if d not in excludes]
        for fn in filenames:
            p = Path(dirpath) / fn
            try:
                if p.stat().st_size > max_bytes:
                    continue
            except Exception:
                continue
            if not is_probably_text(p):
                continue
            yield p


def scan_file(path: Path, entropy_threshold: float, min_length: int) -> List[Finding]:
    findings: List[Finding] = []
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return findings

    for idx, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()

        # .env style
        m = DOTENV_LINE.match(stripped)
        if m:
            key, value = m.group(1), m.group(2)
            if ENV_SECRET_NAME.search(key) or any(p.search(value) for p in SECRET_PATTERNS.values()):
                # Lower severity if this is just a reference to os.getenv/os.environ.get
                sev = "low" if ("os.getenv" in value or "os.environ.get" in value) else "high"
                findings.append(Finding(str(path), idx, "dotenv", key, stripped[:240], "dotenv_key", sev))

        # os.getenv refs
        for ref in ENV_REF.findall(line):
            # Env references are not secrets themselves; keep severity low
            sev = "low"
            findings.append(Finding(str(path), idx, "env_ref", ref, stripped[:240], "env_ref", sev))

        # Known token patterns
        for name, pat in SECRET_PATTERNS.items():
            for m2 in pat.finditer(line):
                findings.append(Finding(str(path), idx, "token", m2.group(0), stripped[:240], name, "high"))

        # High-entropy quoted tokens
        for qt in QUOTED_TOKEN.findall(line):
            if len(qt) >= min_length:
                ent = shannon_entropy(qt)
                if ent >= entropy_threshold:
                    findings.append(Finding(str(path), idx, "entropy", qt[:64] + ("…" if len(qt) > 64 else ""), stripped[:240], f"entropy>={entropy_threshold}", "medium"))

    return findings


def load_ignore_rules(root: Path, ignore_file: str) -> List[IgnoreRule]:
    p = (root / ignore_file)
    rules: List[IgnoreRule] = []
    if not p.exists():
        return rules
    try:
        for raw in p.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if ":" in line:
                field, expr = line.split(":", 1)
                field = field.strip().lower()
                expr = expr.strip()
                if not expr:
                    continue
                rules.append(IgnoreRule(field=field, pattern=re.compile(expr, re.IGNORECASE)))
            else:
                rules.append(IgnoreRule(field="any", pattern=re.compile(line, re.IGNORECASE)))
    except Exception:
        pass
    return rules


def should_ignore(f: Finding, rules: List[IgnoreRule]) -> bool:
    if not rules:
        return False
    for r in rules:
        if r.field == "any":
            blob = f"{f.path}\n{f.kind}\n{f.rule}\n{f.match}\n{f.context}\n{f.severity}"
            if r.pattern.search(blob):
                return True
        elif r.field == "path" and r.pattern.search(f.path):
            return True
        elif r.field == "kind" and r.pattern.search(f.kind):
            return True
        elif r.field == "rule" and r.pattern.search(f.rule):
            return True
        elif r.field == "match" and r.pattern.search(f.match):
            return True
        elif r.field == "context" and r.pattern.search(f.context):
            return True
        elif r.field == "severity" and r.pattern.search(f.severity):
            return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description="Secret/ENV scanner")
    ap.add_argument("--root", default=".", help="Root directory to scan")
    ap.add_argument("--exclude", action="append", default=[], help="Additional directories to exclude (repeat)")
    ap.add_argument("--max-size-mb", type=int, default=2, help="Skip files larger than this size (MB)")
    ap.add_argument("--entropy-threshold", type=float, default=4.3, help="Shannon entropy threshold for suspicious strings")
    ap.add_argument("--min-length", type=int, default=20, help="Minimum length for entropy candidates")
    ap.add_argument("--format", choices=["text", "json"], default="text", help="Output format")
    ap.add_argument("--ignore-file", default=".secret-scan-ignore", help="Ignore rules file (regex-based)")
    ap.add_argument("--fallback-ignore", action="store_true", help="Also search for ignore file under tools/.secret-scan-ignore if not found at root")
    ap.add_argument("--report", help="Write JSON report to file")
    ap.add_argument("--fail-on-find", action="store_true", help="Exit with code 2 if any high/medium findings found")
    # Convenience presets
    ap.add_argument("--heroku", action="store_true", help="Convenience preset for CI/Heroku (root=., fail-on-find, fallback-ignore)")
    ap.add_argument("--all", "-A", "-all", action="store_true", help="Scan the whole repo with sensible defaults (root=., fallback-ignore)")
    ap.add_argument("--json", dest="use_json", action="store_true", help="Shortcut for --format json")
    # Presence-only mode
    ap.add_argument("--presence-only", action="store_true", help="Do not show findings; instead report presence of ENV keys (local/remote)")
    ap.add_argument("--missing-only", action="store_true", help="In presence-only mode, show only keys missing locally or on Heroku")
    ap.add_argument("--load-dotenv", action="store_true", help="Consider values from root .env as local presence (without printing them)")
    ap.add_argument("--heroku-app", help="Heroku app name to check config vars")
    ap.add_argument("--heroku-api-key", help="Heroku API token (fallback to HEROKU_API_KEY env)")
    args = ap.parse_args()

    # Apply convenience presets/shortcuts
    if getattr(args, "use_json", False):
        args.format = "json"
    if args.heroku:
        # Force-root current dir, enable fail-on-find and fallback ignore
        args.root = "."
        args.fail_on_find = True
        args.fallback_ignore = True
    if args.all:
        # Scan entire repo with fallback ignore
        args.root = "."
        args.fallback_ignore = True

    root = Path(args.root).resolve()
    excludes = set(DEFAULT_EXCLUDES) | set(args.exclude)

    all_findings: List[Finding] = []
    for p in iter_files(root, excludes, args.max_size_mb):
        all_findings.extend(scan_file(p, args.entropy_threshold, args.min_length))

    # Apply ignore rules
    ignore_rules = load_ignore_rules(root, args.ignore_file)
    if not ignore_rules and args.fallback_ignore:
        ignore_rules = load_ignore_rules(root, f"tools/{args.ignore_file}")
    if ignore_rules:
        before = len(all_findings)
        all_findings = [f for f in all_findings if not should_ignore(f, ignore_rules)]
        after = len(all_findings)

    # Presence-only mode: summarize ENV keys presence
    if args.presence_only:
        # collect keys from findings
        keys: Dict[str, Dict[str, bool]] = {}
        for f in all_findings:
            if f.kind in {"dotenv", "env_ref"} and f.match and re.fullmatch(r"[A-Z][A-Z0-9_]{1,}", f.match):
                keys.setdefault(f.match, {})

        # option: load .env for presence
        envfile_map: Dict[str, str] = {}
        if args.load_dotenv:
            dotenv_path = root / ".env"
            if dotenv_path.exists():
                try:
                    for raw in dotenv_path.read_text(encoding="utf-8", errors="ignore").splitlines():
                        m = DOTENV_LINE.match(raw.strip())
                        if m:
                            envfile_map[m.group(1)] = m.group(2)
                except Exception:
                    pass

        # local presence
        for k in keys.keys():
            present_local = bool(os.environ.get(k)) or bool(envfile_map.get(k))
            keys[k]["local"] = present_local

        # Heroku presence
        heroku_vars: Dict[str, Any] = {}
        app = args.heroku_app
        api_key = args.heroku_api_key or os.environ.get("HEROKU_API_KEY")
        if app and api_key:
            try:
                req = urllib.request.Request(
                    url=f"https://api.heroku.com/apps/{app}/config-vars",
                    headers={
                        "Accept": "application/vnd.heroku+json; version=3",
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    method="GET",
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = resp.read().decode("utf-8", errors="ignore")
                    heroku_vars = json.loads(data)
            except urllib.error.HTTPError:
                heroku_vars = {}
            except Exception:
                heroku_vars = {}
        for k in keys.keys():
            keys[k]["heroku"] = bool(heroku_vars.get(k)) if heroku_vars else False if app else None  # None if not checked

        # Prepare output
        items = sorted(keys.items(), key=lambda kv: kv[0])
        if args.missing_only:
            filtered = []
            for k, pres in items:
                loc = pres.get("local")
                her = pres.get("heroku")
                if (loc is False) or (her is False):
                    filtered.append((k, pres))
            items = filtered

        if args.format == "json":
            report = {k: v for k, v in items}
            print(json.dumps({"keys": report, "heroku_app": app}, ensure_ascii=False, indent=2))
        else:
            print(f"Presence report (root={root}{', heroku='+app if app else ''}):")
            for k, pres in items:
                loc = pres.get("local")
                her = pres.get("heroku")
                loc_sym = "+" if loc else "-"
                her_sym = ("+" if her else "-") if isinstance(her, bool) else "?"
                print(f"{k:35s} local:{loc_sym} heroku:{her_sym}")

        # Exit code policy for presence-only: don't fail unless explicitly requested
        return 0

    # Sort: high -> medium -> low for default findings mode
    sev_order = {"high": 0, "medium": 1, "low": 2}
    all_findings.sort(key=lambda f: (sev_order.get(f.severity, 9), f.path, f.line))

    if args.format == "json":
        payload: Dict[str, Any] = {
            "root": str(root),
            "findings": [asdict(f) for f in all_findings],
            "summary": {
                "total": len(all_findings),
                "by_severity": {
                    "high": sum(1 for f in all_findings if f.severity == "high"),
                    "medium": sum(1 for f in all_findings if f.severity == "medium"),
                    "low": sum(1 for f in all_findings if f.severity == "low"),
                },
            },
        }
        out = json.dumps(payload, ensure_ascii=False, indent=2)
        print(out)
        if args.report:
            Path(args.report).write_text(out, encoding="utf-8")
    else:
        # Optional presence enrichment for text mode (no secrets printed)
        envfile_map: Dict[str, str] = {}
        if args.load_dotenv:
            dotenv_path = root / ".env"
            if dotenv_path.exists():
                try:
                    for raw in dotenv_path.read_text(encoding="utf-8", errors="ignore").splitlines():
                        m = DOTENV_LINE.match(raw.strip())
                        if m:
                            envfile_map[m.group(1)] = m.group(2)
                except Exception:
                    pass
        heroku_vars: Dict[str, Any] = {}
        app = args.heroku_app
        api_key = args.heroku_api_key or os.environ.get("HEROKU_API_KEY")
        if app and api_key:
            try:
                req = urllib.request.Request(
                    url=f"https://api.heroku.com/apps/{app}/config-vars",
                    headers={
                        "Accept": "application/vnd.heroku+json; version=3",
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    method="GET",
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = resp.read().decode("utf-8", errors="ignore")
                    heroku_vars = json.loads(data)
            except Exception:
                heroku_vars = {}

        if not all_findings:
            print(f"No findings. Scanned {root}")
        else:
            print(f"Findings ({len(all_findings)}):")
            for f in all_findings:
                short_path = Path(f.path).name
                # Redacted output: never print raw values/context
                annotate = ""
                if f.kind in {"dotenv", "env_ref"} and re.fullmatch(r"[A-Z][A-Z0-9_]{1,}", f.match or ""):
                    var = f.match
                    local_present = bool(os.environ.get(var)) or bool(envfile_map.get(var))
                    heroku_present = (bool(heroku_vars.get(var)) if heroku_vars else None) if app else None
                    loc_sym = "+" if local_present else "-"
                    her_sym = ("+" if heroku_present else "-") if isinstance(heroku_present, bool) else "?"
                    annotate = f" [local:{loc_sym} heroku:{her_sym}]"
                    display_tail = var
                elif f.kind == "token":
                    display_tail = "(secret)"
                else:
                    display_tail = f.rule
                print(f"[{f.severity.upper()}] {f.kind}:{f.rule} {short_path}:{f.line}{annotate} :: {display_tail}")

    if args.fail_on_find:
        exit_code = 2 if any(f.severity in {"high", "medium"} for f in all_findings) else 0
        return exit_code
    return 0


if __name__ == "__main__":
    sys.exit(main())


