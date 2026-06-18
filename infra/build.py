"""Docker-free packaging for the CDK Lambda assets.

Both helpers produce a staging directory (code + vendored dependencies +
collector config) that ``lambda.Code.from_asset`` zips and uploads. They run
during ``cdk synth``.

- ``build_agent``: agent source + deps for the agent Lambda. Deps are vendored as
  linux/arm64 wheels (the function is arm64) since Lambda does not pip-install at
  boot. Includes the shared ``collector.yaml`` for the opentelemetry-lambda layer.
- ``build_api``: the proxy Lambda + a current boto3 (pure-python) + collector.yaml.

Both packages place ``collector.yaml`` at the bundle root so the runtime env
``OPENTELEMETRY_COLLECTOR_CONFIG_URI=/var/task/collector.yaml`` resolves.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

# Cross-build target arch for vendored wheels. Must match LAMBDA_ARCH in
# infra/app.py (the function arch). manylinux platform tags per arch.
_ARCH = os.environ.get("LAMBDA_ARCH", "arm64").lower()
_IS_X86 = _ARCH in ("x86_64", "amd64")
_PLATFORM_TAGS = (
    ["manylinux2014_x86_64", "manylinux_2_17_x86_64", "manylinux_2_28_x86_64"]
    if _IS_X86
    else ["manylinux2014_aarch64", "manylinux_2_17_aarch64", "manylinux_2_28_aarch64"]
)

REPO = Path(__file__).resolve().parents[1]
AGENT_SRC = REPO / "agent"
API_SRC = REPO / "api"
COLLECTOR_CONFIG = REPO / "collector.yaml"
BUILD = REPO / "infra" / ".build"

# Files/dirs in agent/ that must NOT ship to the Lambda.
_AGENT_EXCLUDE = {"Dockerfile", ".dockerignore", "__pycache__", ".bedrock_agentcore.yaml"}


def _clean(path: Path) -> Path:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _pip_install(requirements: Path, target: Path) -> None:
    """Cross-build linux wheels for the Lambda's architecture (_ARCH)."""
    cmd = [
        sys.executable, "-m", "pip", "install",
        "-r", str(requirements),
        "--target", str(target),
        "--quiet", "--disable-pip-version-check",
        "--only-binary=:all:",
        "--python-version", "3.12",
        "--implementation", "cp",
    ]
    for tag in _PLATFORM_TAGS:
        cmd += ["--platform", tag]
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
    """Stage agent source + arch deps + collector config; return staging path."""
    stage = _clean(BUILD / "agent")
    _copy_source(AGENT_SRC, stage, _AGENT_EXCLUDE)
    shutil.copy2(COLLECTOR_CONFIG, stage / "collector.yaml")
    _pip_install(AGENT_SRC / "requirements.txt", stage)
    return str(stage)


def build_api() -> str:
    """Stage the proxy Lambda + boto3 + collector config; return staging path."""
    stage = _clean(BUILD / "api")
    shutil.copy2(API_SRC / "lambda_function.py", stage / "lambda_function.py")
    shutil.copy2(COLLECTOR_CONFIG, stage / "collector.yaml")
    # Deps built for the function arch (boto3 is pure-python, but staying
    # consistent with _ARCH keeps the bundle uniform with the layer arch).
    _pip_install(API_SRC / "requirements.txt", stage)
    return str(stage)


if __name__ == "__main__":  # quick manual test: python infra/build.py
    print("agent ->", build_agent())
    print("api   ->", build_api())
