FROM python:3.11-slim

WORKDIR /app
COPY . /app

CMD ["python3", "-m", "learning_path_outcomes.report"]
