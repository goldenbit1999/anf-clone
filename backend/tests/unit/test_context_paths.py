"""CLAUDE.md와 .claude/rules/*.md가 백틱으로 가리키는 저장소 경로와 파일 이름이 실제로 추적되는 파일인지,
그리고 rules 파일의 `paths:` 패턴이 추적되는 파일에 걸리는지 확인한다.

둘 다 손으로 쓰는 문서다. 여기서는 파일을 옮기거나 이름을 바꿔 안내가 썩는 것과, 패턴이 아무 파일에도
걸리지 않아 rules 파일이 영영 로딩되지 않는 것만 막는다. 내용이 맞는지(명령, 동작 설명)는 리뷰가 본다.
"""

import re
from fnmatch import fnmatchcase
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
RULES = sorted((REPO / ".claude" / "rules").glob("*.md"))
CONTEXT_FILES = [REPO / "CLAUDE.md", *RULES]
PATHS_ENTRY = re.compile(r'^  - "([^"]+)"$', re.M)
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


def test_every_path_in_the_context_files_is_tracked():
    assert len(CONTEXT_FILES) > 1, "no .claude/rules/*.md"
    for doc in CONTEXT_FILES:
        assert broken_references(doc.read_text(encoding="utf-8")) == [], doc.name


def test_every_rule_has_paths_and_each_pattern_matches_a_tracked_file():
    files = set(subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=True).stdout.splitlines())
    for rule in RULES:
        frontmatter = rule.read_text(encoding="utf-8").split("---")[1]
        patterns = PATHS_ENTRY.findall(frontmatter)
        assert patterns, f"{rule.name}: no paths, so it would load in every session"
        dead = [p for p in patterns if not any(fnmatchcase(f, p) for f in files)]
        assert dead == [], rule.name


def test_a_moved_file_is_reported():
    text = "`backend/anf_api/gone.py`, `gone_module.py`, `backend/anf_api/`, `lro.py`, `docker compose up`"
    assert broken_references(text) == ["backend/anf_api/gone.py", "gone_module.py"]
