#!/usr/bin/env python3
"""
Script để khởi chạy agenticRAG FastAPI server.
Hỗ trợ cả chế độ development và production (via uvicorn).
"""

import os
import sys
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def main():
    # Kiểm tra biến môi trường bắt buộc
    required_env_vars = ["GOOGLE_API_KEY", "MONGO_CONNECTION_STRING"]
    missing_vars = [v for v in required_env_vars if not os.environ.get(v)]
    if missing_vars:
        logger.error(f"Thiếu biến môi trường: {', '.join(missing_vars)}")
        logger.error("Vui lòng tạo file .env hoặc thiết lập biến môi trường")
        sys.exit(1)

    host = os.environ.get("FASTAPI_HOST", "127.0.0.1")
    port = int(os.environ.get("FASTAPI_PORT", 5002))
    reload = os.environ.get("FASTAPI_RELOAD", "true").lower() == "true"

    print(f"""
╔══════════════════════════════════════════════════════════════════════════════════════╗
║                              AgenticRAG FastAPI Server                               ║
║                                                                                      ║
║  🚀 Server đang chạy tại : http://{host}:{port:<5}                              ║
║  📋 Health check         : http://{host}:{port}/health                           ║
║  💬 Chat endpoint        : http://{host}:{port}/chat                             ║
║  📝 API docs (Swagger)   : http://{host}:{port}/docs                            ║
║  📝 API docs (ReDoc)     : http://{host}:{port}/redoc                           ║
║                                                                                      ║
║  Press Ctrl+C to stop                                                               ║
╚══════════════════════════════════════════════════════════════════════════════════════╝
    """)

    import uvicorn
    uvicorn.run(
        "agenticRAG:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()