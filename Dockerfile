FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV HOST=0.0.0.0
ENV PORT=3000

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt \
    && python -m spacy download en_core_web_lg

COPY . .

EXPOSE 3000

CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-3000}"]
