"""CLAUDE.md가 백틱으로 가리키는 저장소 경로와 파일 이름이 실제로 추적되는 파일인지 확인한다.

CLAUDE.md는 손으로 쓰는 문서다. 여기서는 파일을 옮기거나 이름을 바꿔 안내가 썩는 것만 막는다.
내용이 맞는지(명령, 동작 설명)는 리뷰가 본다.
"""

import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
BACKTICKED = re.compile(r"`([^`\n]+)`")
# 저장소 경로로 보는 것: 이 폴더로 시작하는 토큰과, 폴더 없이 쓴 파일 이름
REPO_PATH = re.compile(r"(backend|docs|scripts|deploy|frontend|_workspace|\.claude|\.github)/[\w./-]*")
FILE_NAME = re.compile(r"[\w.-]+\.(py|ts|tsx|sh|ya?ml|md|json|toml)")
NOT_TRACKED = {
    ".claude/tdd-guard-state/evidence.json",  # gitignore 대상, 훅이 만든다
    # TDD 훅 설명의 예시 이름
    "foo.py", "test_foo.py", "foo_test.py", "models.py", "test_models.py",
}


def tracked() -> tuple[set[str], set[str]]:
    r = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=True)
    files = set(r.stdout.splitlines())
    paths = files | {str(p.as_posix()) for f in files for p in Path(f).parents}
    return paths, {Path(f).name for f in files}


def broken_references(text: str) -> list[str]:
    paths, names = tracked()
    broken = []
    for token in sorted(set(BACKTICKED.findall(text)) - NOT_TRACKED):
        if REPO_PATH.fullmatch(token):
            if token.rstrip("/") not in paths:
                broken.append(token)
        elif FILE_NAME.fullmatch(token) and token not in names:
            broken.append(token)
    return broken


def test_every_path_in_claude_md_is_tracked():
    assert broken_references((REPO / "CLAUDE.md").read_text(encoding="utf-8")) == []


def test_a_moved_file_is_reported():
    text = "`backend/anf_api/gone.py`, `gone_module.py`, `backend/anf_api/`, `lro.py`, `docker compose up`"
    assert broken_references(text) == ["backend/anf_api/gone.py", "gone_module.py"]
