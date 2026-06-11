# Amazon Bedrock AgentCore Runtime requires linux/arm64 images.
FROM --platform=linux/arm64 python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# AgentCore Runtime contract: container listens on 8080 and serves
# POST /invocations and GET /ping (both handled by BedrockAgentCoreApp).
EXPOSE 8080

CMD ["python", "app.py"]
