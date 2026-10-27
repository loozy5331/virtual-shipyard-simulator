# 원천 이미지 하나로 세 가지를 돌린다(ADR-012). 명령만 바꾼다:
#   python -m sim ...                 정답 로그
#   python -m emitter --sink kafka    방출기(노이즈 → Kafka)
#   python -m emitter.replay.service  재발행 서비스(요청 디렉터리)
# 작업 디렉터리 /app의 out/에 쓰므로 볼륨은 /app/out에 붙인다.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never \
    PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1
WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --extra kafka

COPY sim sim
COPY emitter emitter
COPY params params
COPY schemas schemas

CMD ["python", "-m", "sim"]
