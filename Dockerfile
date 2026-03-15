FROM python:3.12-slim

WORKDIR /app

RUN pip install uv

COPY pyproject.toml uv.lock* ./
RUN uv sync --locked --no-dev 2>/dev/null || uv sync --no-dev

COPY . .

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "autodev.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
