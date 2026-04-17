
from fastapi import FastAPI
import os
app = FastAPI()
tasks = []

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
    return {"message": "Task added", "tasks": tasks}

@app.get("/config")
def config():
    return {
        "app_name": os.getenv("APP_NAME"),
        "environment": os.getenv("ENVIRONMENT")
    }
