# anf-api 이미지 (FR-13, 설계 _workspace/containers/02_main_design.md §1).
# root가 아니라 uid 1000으로 돈다. 상태 DB(SQLite)는 /data에 두고, compose가 이름 있는 볼륨을 붙인다(결정 7).
# 빌드 컨텍스트는 저장소 루트다(deploy/compose.yaml). 들어가는 파일은 루트의 .dockerignore가 정한다.
FROM python:3.12-slim

RUN useradd --uid 1000 --create-home anf && mkdir /data && chown anf:anf /data

WORKDIR /app
# 의존성은 저장소의 pyproject.toml 하나가 정한다(D-14). 패키지는 없고(packages = []) 의존성만 설치된다
COPY pyproject.toml ./
RUN pip install --no-cache-dir .
COPY backend/anf_api backend/anf_api

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 ANF_API_DB=/data/anf-api.db
USER anf
CMD ["python", "-m", "uvicorn", "--factory", "anf_api.arm_app:create_app", \
     "--app-dir", "backend", "--host", "127.0.0.1", "--port", "8080"]
