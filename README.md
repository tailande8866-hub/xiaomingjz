# 飞机最强记账机器人 - 全自动SaaS版

一个功能完整的Telegram记账机器人SaaS平台，支持：
- 🤖 **全自动售卖** - 用户直接在Bot中购买套餐并自动创建新Bot实例
- 💳 **USDT支付** - 集成USDT TRC20支付系统
- 📊 **完整记账功能** - 群组记账、查询、汇率管理等
- 🔄 **无限扩展** - 每个新Bot都具备完整功能，可以继续售卖

## ⚡ 快速导航

- **单机版部署** - 适合个人使用，直接运行一个记账机器人
- **SaaS版部署** - 适合商业运营，销售记账机器人服务
  - 📖 [SaaS自动化售卖指南](docs/SAAS_AUTO_SELLING_GUIDE.md)
  - 🚀 [快速开始](#快速开始)

---

## 功能特性

### 🧪 本地开发支持
- **假支付环境** - 无需真实USDT即可测试完整支付流程
- **可配置延迟** - 模拟网络延迟，优化用户体验
- **虚拟交易哈希** - 生成逼真的交易信息用于显示
- **详细文档** - 提供完整的使用指南和快速开始教程

详见：[假支付环境快速开始](QUICK_START_TEST_MODE.md) | [详细指南](TEST_MODE_GUIDE.md)



## 快速开始

### 环境要求
- Python 3.9+
- Telegram Bot Token

### 安装步骤

1. 克隆项目
```bash
git clone <repository-url>
cd AAAJIZHANG
```

2. 安装依赖
```bash
pip install -r requirements.txt
```

3. 配置环境变量
```bash
cp .env.template .env
# 编辑.env文件，填入你的BOT_TOKEN等配置
```

4. 初始化SaaS套餐
```bash
python scripts/update_saas_plans.py
```

5. 启动Bot
```bash
python main.py
```

4. 运行机器人
```bash
python main.py
```

### SaaS自动化售卖流程

1. **用户点击“创建机器人”** → 显示套餐列表（一个月/三个月/一年/永久）
2. **选择套餐** → 生成USDT支付订单
3. **用户转账** → 点击“我已支付”激活订阅
4. **自动创建Bot** → 输入Bot Token，系统自动创建新实例
5. **新Bot启动** → 具备完整功能，可以继续售卖
```bash
python main.py
```

## 配置说明

在`.env`文件中配置以下参数：

```env
# Telegram Bot Token（必填）
BOT_TOKEN=your_bot_token_here

# 超级管理员ID（必填）
SUPER_ADMIN_ID=your_telegram_user_id

# 数据库配置
DATABASE_URL=sqlite+aiosqlite:///./accounting_bot.db

# 默认设置
DEFAULT_CURRENCY=USDT
DEFAULT_EXCHANGE_RATE=7.3
DEFAULT_FEE_RATE=3

# 时区
TIMEZONE=Asia/Shanghai
```

## 使用说明

### 基础操作

#### 开始记账
发送：`开始`

#### 查看账单
发送：`显示账单` 或 `+0`

#### 查看帮助
发送：`/help`

### 入款操作

#### 基础入款
```
+1000          # 入款1000（使用默认币种）
+1000u         # 入款1000 USDT
+1000 备注内容  # 带备注的入款
```

#### 指定汇率/费率
```
+1000/7.3      # 指定汇率
+1000*3%       # 指定费率
+1000u/7.3*12% # 组合使用
```

#### 指定用户入款
```
张三+1000       # 为张三记录入款
# 或回复张三的消息：+1000
```

### 下发操作

#### 基础下发
```
下发1000        # 下发1000
下发1000r       # 下发1000 USDT
下发1000 备注   # 带备注的下发
```

#### 指定用户下发
```
张三下发1000
# 或回复张三的消息：下发1000
```

### 寄存操作
```
P+1000         # 寄存增加1000
P-1000         # 寄存减少1000
```

### 参数设置

#### 汇率设置
```
设置汇率7.3           # 设置群组默认汇率
设置张三汇率7.3       # 设置张三的个人汇率
# 或回复张三的消息：设置他的汇率7.3
```

#### 费率设置
```
设置费率3            # 设置群组默认费率
设置张三费率3        # 设置张三的个人费率
```

#### 显示设置
```
设置入款条数5        # 设置入款显示条数
设置下发条数5        # 设置下发显示条数
设置币种AUD         # 设置显示币种
记账置顶            # 开启置顶
置顶关闭            # 关闭置顶
双币模式            # 开启双币模式
单币模式            # 开启单币模式
纯净模式            # 纯净显示模式
显示回复人          # 显示回复人模式
显示入账人          # 显示操作人模式
```

#### 日切设置
```
设置日切时间23:59
```

### 操作人管理
```
添加操作人 @用户    # 添加操作人
删除操作人 @用户    # 删除操作人
显示操作人         # 查看操作人列表
设置全员           # 设置全员可操作
取消全员           # 取消全员可操作
```

### 查询功能
```
h0                 # 查询火币U价
z0                 # 查询欧易U价
Txxxx...           # 查询TRC20地址（直接发送地址）
计算100*7.3        # 计算功能
```

### 账单管理
```
全部账单           # 查看所有账单
账单汇总           # 查看汇总统计
/我               # 查看我的账单
保存账单           # 保存当前账单
删除账单           # 删除所有账单
撤销入款           # 撤销最后一条入款
撤销下发           # 撤销最后一条下发
```

## 项目结构

```
AAAJIZHANG/
├── config/              # 配置模块
├── src/
│   ├── handlers/        # 命令处理器
│   │   ├── basic.py     # 基础功能
│   │   ├── operator.py  # 操作人管理
│   │   ├── billing.py   # 账单操作
│   │   ├── settings.py  # 参数设置
│   │   └── query.py     # 查询功能
│   ├── models/          # 数据模型
│   ├── services/        # 服务层
│   ├── utils/           # 工具函数
│   └── bot.py          # 主程序
├── docs/               # 文档
├── main.py            # 启动脚本
└── requirements.txt   # 依赖包
```

## 数据库

项目使用SQLite数据库（可配置为PostgreSQL），包含以下主要表：
- `groups` - 群组配置
- `group_operators` - 操作人
- `user_configs` - 用户个人配置
- `transactions` - 交易记录
- `daily_summaries` - 每日汇总

## 技术栈

- **Python 3.9+**
- **python-telegram-bot** - Telegram Bot API
- **SQLAlchemy** - ORM框架
- **APScheduler** - 定时任务
- **aiosqlite** - 异步SQLite
- **httpx** - HTTP客户端

## 开发说明

### 添加新功能

1. 在`src/handlers/`下创建或修改处理器
2. 在`src/bot.py`的`setup_handlers()`中注册处理器
3. 如需数据库支持，在`src/models/`中添加模型

### 运行测试
```bash
python -m pytest tests/
```

## 注意事项

1. 请妥善保管`BOT_TOKEN`，不要泄露
2. 首次使用需要配置超级管理员ID
3. 建议定期备份数据库文件
4. 生产环境建议使用PostgreSQL数据库


## 技术栈

- **Python 3.9+**
- **python-telegram-bot** - Telegram Bot API
- **SQLAlchemy** - ORM框架
- **APScheduler** - 定时任务
- **USDT TRC20** - 加密货币支付

## 许可证

MIT License

## 支持

如有问题或建议，请提交Issue。
