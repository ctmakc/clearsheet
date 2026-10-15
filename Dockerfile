FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY clearsheet ./clearsheet
COPY web ./web
COPY samples ./samples
COPY eval ./eval
COPY recordings ./recordings
ENV PYTHONUNBUFFERED=1
ENV PORT=3000
EXPOSE 3000
CMD ["sh", "-c", "uvicorn clearsheet.server:app --host 0.0.0.0 --port ${PORT}"]
