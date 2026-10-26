FROM python:3.11-slim

WORKDIR /app

# Copy requirements first for layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy server code
COPY . .

# Copy config
COPY ../config/config.yaml /app/config/config.yaml

EXPOSE 8080

# Run MCP server in stdio mode (AI client connects via stdin/stdout)
CMD ["python", "main.py"]
