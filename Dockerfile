FROM --platform=linux/arm64 python:3.12-slim

WORKDIR /app

COPY Requirement.txt .
RUN pip install --no-cache-dir -r Requirement.txt

COPY agent.py runtime.py ./

ENV PYTHONUNBUFFERED=1
ENV BEDROCK_MODEL_ID=<"Your BEDROCK_MODEL_ID">
CMD ["python", "runtime.py"]