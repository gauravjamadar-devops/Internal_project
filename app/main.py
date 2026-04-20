
from fastapi import FastAPI, HTTPException
import os
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST, Counter, Histogram
from starlette.responses import Response
from starlette.middleware.base import BaseHTTPMiddleware
import time

app = FastAPI()
tasks = []

# Define Prometheus metrics
request_count = Counter('app_requests_total', 'Total requests', ['method', 'endpoint', 'status'])
request_duration = Histogram('app_request_duration_seconds', 'Request duration', ['method', 'endpoint'])
task_count = Counter('app_tasks_total', 'Total tasks created', [])

# Middleware for automatic HTTP metrics
class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        start_time = time.time()
        response = await call_next(request)
        process_time = time.time() - start_time
        
        request_count.labels(method=request.method, endpoint=request.url.path, status=response.status_code).inc()
        request_duration.labels(method=request.method, endpoint=request.url.path).observe(process_time)
        
        return response

app.add_middleware(MetricsMiddleware)

@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

@app.get("/health")
def health():
    # If the "FAIL_HEALTH" variable is set to "true", return an error
    if os.getenv("FAIL_HEALTH") == "true":
        raise HTTPException(status_code=500, detail="Simulated Failure")
    return {"status": "ok"}    

@app.get("/tasks")
def get_tasks():
    return {"tasks": tasks}

@app.post("/tasks")
def add_task(task: str):
    tasks.append(task)
    task_count.inc()  # Increment custom metric
    return {"message": "Task added", "tasks": tasks}

@app.get("/config")
def config():
    return {
        "app_name": os.getenv("APP_NAME"),
        "environment": os.getenv("ENVIRONMENT")
    }
