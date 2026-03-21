FROM python:3.10-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml ./
RUN uv pip install --system --no-cache -r pyproject.toml

COPY app/ ./app/

EXPOSE 8052

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8052"]
