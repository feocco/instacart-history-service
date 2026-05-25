FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY instacart_history ./instacart_history

RUN pip install --no-cache-dir .

EXPOSE 8080

CMD ["uvicorn", "instacart_history.main:app", "--host", "0.0.0.0", "--port", "8080"]
