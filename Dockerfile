FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 安装系统依赖和中文字体
RUN apt-get update && apt-get install -y \
    gcc \
    fonts-wqy-zenhei \
    fonts-wqy-microhei \
    && rm -rf /var/lib/apt/lists/* \
    && fc-cache -fv

# 复制依赖文件
COPY requirements.txt .

# 安装Python依赖
RUN pip install --no-cache-dir -r requirements.txt

# 复制项目文件
COPY . .

# 创建必要的目录
RUN mkdir -p data logs bot_instances backups

# 设置环境变量
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# 暴露端口（Web账单系统）
EXPOSE 8081

# 启动命令
CMD ["python", "main.py"]
