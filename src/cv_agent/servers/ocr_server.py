"""OCR server stub — Monkey OCR 1.5 + PaddleOCR."""
import importlib.util
import os
import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse

app = FastAPI(title="CV OCR Server")

_paddle_available = importlib.util.find_spec("paddleocr") is not None
# Resolve model path relative to project root (4 levels up from servers/)
_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
_monkey_path = os.path.join(_project_root, "output", ".models", "monkey-ocr")
_monkey_available = os.path.isdir(_monkey_path) and bool(os.listdir(_monkey_path))


@app.get("/health")
async def health():
    return JSONResponse({
        "status": "ok",
        "paddle_ocr": _paddle_available,
        "monkey_ocr": _monkey_available,
    })


@app.get("/api/info")
async def info():
    return JSONResponse({
        "engines": {
            "paddleocr": {"available": _paddle_available},
            "monkey_ocr": {"available": _monkey_available, "model_path": _monkey_path},
        }
    })


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=7861, log_level="info")
