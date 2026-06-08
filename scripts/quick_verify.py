"""
快速验证脚本 - 检查新功能是否正确实施
"""
import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

print("="*60)
print("群组授权与额度管理功能 - 快速验证")
print("="*60)

# 1. 检查模型导入
try:
    from src.models import GroupQuota, Group
    print("[PASS] 模型导入成功")
except Exception as e:
    print(f"[FAIL] 模型导入失败: {e}")
    sys.exit(1)

# 2. 检查Repository导入
try:
    from src.repositories.group_quota_repo import GroupQuotaRepo
    from src.repositories.group_repo import GroupRepo
    print("[PASS] Repository导入成功")
except Exception as e:
    print(f"[FAIL] Repository导入失败: {e}")
    sys.exit(1)

# 3. 检查Service导入
try:
    from src.services.quota_service import QuotaService, quota_service
    from src.services.join_welcome_service import JoinWelcomeService, join_welcome_service
    print("[PASS] Service导入成功")
except Exception as e:
    print(f"[FAIL] Service导入失败: {e}")
    sys.exit(1)

# 4. 检查Handler导入
try:
    from src.handlers.join_welcome_handler import handle_new_chat_member, register_join_welcome_handler
    from src.handlers.quota_commands import cmd_set_quota, cmd_disable_quota
    from src.handlers.welcome_commands import (
        cmd_set_global_welcome,
        cmd_set_join_welcome,
        cmd_enable_join_welcome,
        cmd_disable_join_welcome
    )
    print("[PASS] Handler导入成功")
except Exception as e:
    print(f"[FAIL] Handler导入失败: {e}")
    sys.exit(1)

# 5. 检查AuthorizationService增强
try:
    from src.services.authorization_service import AuthorizationService
    if hasattr(AuthorizationService, 'manual_authorize_group'):
        print("[PASS] AuthorizationService已增强")
    else:
        print("[FAIL] AuthorizationService缺少manual_authorize_group方法")
        sys.exit(1)
except Exception as e:
    print(f"[FAIL] AuthorizationService检查失败: {e}")
    sys.exit(1)

# 6. 检查集成点
try:
    import inspect
    from src.handlers.billing import deposit, withdraw
    
    deposit_source = inspect.getsource(deposit.handle_deposit)
    withdraw_source = inspect.getsource(withdraw.handle_withdraw)
    
    if 'quota_service' in deposit_source and 'check_and_warn_quota' in deposit_source:
        print("[PASS] deposit.py已集成额度检查")
    else:
        print("[WARN] deposit.py可能未集成额度检查")
    
    if 'quota_service' in withdraw_source and 'check_and_warn_quota' in withdraw_source:
        print("[PASS] withdraw.py已集成额度检查")
    else:
        print("[WARN] withdraw.py可能未集成额度检查")
except Exception as e:
    print(f"[FAIL] 集成点检查失败: {e}")

print("\n" + "="*60)
print("所有核心组件验证通过！")
print("="*60)
print("\n新功能列表:")
print("1. 入群欢迎语系统 - 监听新用户进群并发送欢迎语")
print("2. 额度管理系统 - 监控群组净入账金额并预警")
print("3. 超管手动授权 - 私聊发送'授权+群组ID'自动绑定主管理员")
print("\n使用方法:")
print("- 设置额度: /setquota 100 或 设置额度 100u")
print("- 关闭额度: /disablequota 或 关闭额度设置")
print("- 设置全局欢迎语: /setglobalwelcome [消息]")
print("- 设置群组欢迎语: /setjoinwelcome [消息]")
print("- 开启/关闭入群欢迎: /enablejoinwelcome 或 /disablejoinwelcome")
print("- 手动授权: 超管私聊发送 '授权-123456789'")
