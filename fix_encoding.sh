#!/bin/bash
# 修复 basic.py 编码问题

cd /opt/saas-bot

# 用 base64 还原文件
python3 -c "
import base64
with open('src/handlers/basic.py.b64', 'r') as f:
    content = base64.b64decode(f.read())
with open('src/handlers/basic.py', 'wb') as f:
    f.write(content)
print('File restored from base64')
"

# 验证中文
echo "验证文件内容："
head -n 160 src/handlers/basic.py | tail -n 10

# 重启容器
docker-compose restart bot

echo "修复完成！"
