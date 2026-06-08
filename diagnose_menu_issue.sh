#!/bin/bash
# 诊断主Bot菜单失效问题

echo "=========================================="
echo "诊断主Bot菜单失效问题"
echo "=========================================="
echo ""

# 1. 检查容器状态
echo "1️⃣ 检查容器状态..."
docker-compose -f docker-compose.prod.yml ps
echo ""

# 2. 检查 Bot 日志（最近50行）
echo "2️⃣ 检查 Bot 启动日志（最近50行）..."
docker-compose -f docker-compose.prod.yml logs saas-bot --tail 50 | grep -E "(Menu adapter|Registered route|runtime_router)" || echo "未找到路由注册日志"
echo ""

# 3. 检查是否有错误
echo "3️⃣ 检查 Bot 错误日志..."
docker-compose -f docker-compose.prod.yml logs saas-bot --tail 100 | grep -i "error\|exception\|failed" || echo "未发现明显错误"
echo ""

# 4. 检查代码版本
echo "4️⃣ 检查代码版本..."
cd /opt/tg-bot
git log --oneline -5
echo ""

# 5. 检查 requirements.txt 编码
echo "5️⃣ 检查 requirements.txt 编码..."
file requirements.txt
echo ""

# 6. 检查关键文件是否存在
echo "6️⃣ 检查关键文件是否存在..."
ls -la src/handlers/menu_adapter.py src/core/runtime_router.py src/core/route_namespace.py 2>&1
echo ""

# 7. 重启 Bot 容器并查看启动日志
echo "7️⃣ 重启 Bot 容器..."
docker-compose -f docker-compose.prod.yml restart saas-bot
echo "等待 10 秒让容器启动..."
sleep 10
echo ""

# 8. 查看最新日志
echo "8️⃣ 查看最新启动日志..."
docker-compose -f docker-compose.prod.yml logs saas-bot --tail 30
echo ""

echo "=========================================="
echo "诊断完成！"
echo "请将以上输出发送给开发者进行分析"
echo "=========================================="
