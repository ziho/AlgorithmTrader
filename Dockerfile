# AlgorithmTrader Python 开发/运行环境
FROM python:3.11-slim

# 设置环境变量
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# 设置工作目录
WORKDIR /app

# 先复制必要的项目文件
COPY pyproject.toml README.md ./

# 复制源代码
COPY src/ ./src/
COPY services/ ./services/

# 安装 Python 依赖
RUN pip install --upgrade pip && \
    pip install -e ".[dev]"

# 默认命令
CMD ["python", "-c", "print('AlgorithmTrader container ready')"]
