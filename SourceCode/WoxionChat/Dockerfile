# Sử dụng base image Python 3.12 slim
FROM python:3.12-slim

# Thiết lập các biến môi trường
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Cài đặt các thư viện hệ thống cần thiết (ví dụ libgomp1 cho faiss-cpu)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Thiết lập thư mục làm việc
WORKDIR /app

# Cài đặt công cụ uv để tăng tốc độ cài đặt thư viện
RUN pip install --no-cache-dir uv

# Copy các file cấu hình thư viện trước để tận dụng Docker cache layer
# LƯU Ý: Build context của Docker được thiết lập là thư mục cha (SourceCode) để sao chép cả thư mục ace
COPY WoxionChat/pyproject.toml WoxionChat/uv.lock WoxionChat/requirements.txt ./

# Cài đặt thư viện thẳng vào system của container
RUN uv pip install --system -r pyproject.toml

# Copy thư mục ace vào gốc hệ thống của container và sao chép mã nguồn WoxionChat vào /app
COPY ace /ace
COPY WoxionChat /app

# Port mặc định cho web (Django)
EXPOSE 8000
# Port mặc định cho AgenticRAG (FastAPI)
EXPOSE 5002

# Lệnh khởi chạy mặc định (có thể bị ghi đè trong docker-compose.yml)
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
