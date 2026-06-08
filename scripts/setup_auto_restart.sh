#!/bin/bash
# Docker 自动重启配置脚本
# 确保容器在服务器重启后自动启动

docker update --restart=always saas-bot

echo "Docker auto-restart configured at $(date)"
