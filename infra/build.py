"""Docker-free packaging for the CDK assets.

Both helpers produce a staging directory (code + vendored dependencies) that a
CDK ``aws_s3_assets.Asset`` / ``lambda.Code.from_asset`` zips and uploads. They
run during ``cdk synth``.

- ``build_agent``: agent source + deps for the AgentCore managed runtime. The
  runtime does NOT pip-install at boot, so deps are vendored as linux/arm64
  wheels (the runtime is arm64), mirroring the starter toolkit.
- ``build_api``: the Lambda proxy + a current boto3 (pure-python).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
AGENT_SRC = REPO / "agent"
API_SRC = REPO / "api"
BUILD = REPO / "infra" / ".build"

# Files/dirs in agent/ that must NOT ship to the runtime. Notably .venv: a
# local dev virtualenv holds macOS Mach-O binaries that are incompatible with
# the Linux ARM64 runtime and fail artifact validation if shipped.
_AGENT_EXCLUDE = {"Dockerfile", "__pycache__", ".bedrock_agentcore.yaml", ".venv", "venv", ".env"}


def _clean(path: Path) -> Path:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _pip_install(requirements: Path, target: Path, *, arm64: bool) -> None:
    cmd = [
        sys.executable, "-m", "pip", "install",
        "-r", str(requirements),
        "--target", str(target),
        "--quiet", "--disable-pip-version-check",
    ]
    if arm64:
        # Cross-build linux/arm64 wheels for the managed runtime.
        cmd += [
            "--only-binary=:all:",
            "--python-version", "3.12",
            "--implementation", "cp",
            "--platform", "manylinux2014_aarch64",
            "--platform", "manylinux_2_17_aarch64",
            "--platform", "manylinux_2_28_aarch64",
        ]
    subprocess.run(cmd, check=True)


def _copy_source(src: Path, dst: Path, exclude: set[str]) -> None:
    for item in src.iterdir():
        if item.name in exclude or item.name.endswith(".pyc"):
            continue
        target = dst / item.name
        if item.is_dir():
            shutil.copytree(item, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        else:
            shutil.copy2(item, target)


def build_agent() -> str:
    """Stage agent source + arm64 deps; return the staging path."""
    stage = _clean(BUILD / "agent")
    _copy_source(AGENT_SRC, stage, _AGENT_EXCLUDE)
    _pip_install(AGENT_SRC / "requirements.txt", stage, arm64=True)
    return str(stage)


def build_api() -> str:
    """Stage the Lambda proxy + boto3; return the staging path."""
    stage = _clean(BUILD / "api")
    shutil.copy2(API_SRC / "lambda_function.py", stage / "lambda_function.py")
    _pip_install(API_SRC / "requirements.txt", stage, arm64=False)
    return str(stage)


if __name__ == "__main__":  # quick manual test: python infra/build.py
    print("agent ->", build_agent())
    print("api   ->", build_api())
