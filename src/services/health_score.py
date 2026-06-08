"""
Health Score（健康评分系统）

🔥 核心职责：给每个 BOT 一个"健康分数"
🔥 评分维度：心跳、CPU、崩溃记录、Registry 一致性、.env 有效性
🔥 决策依据：低分才修，高分观察

评分规则：
  100 = 完全健康
  0   = 已死亡
"""

import logging
from typing import Dict, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


@dataclass
class HealthScoreConfig:
    """健康评分配置"""
    # 基础分
    BASE_SCORE = 100
    
    # 扣分项
    MISSING_HEARTBEAT_PENALTY = 30      # 心跳缺失
    HIGH_CPU_PENALTY = 15               # CPU 过高
    HIGH_MEMORY_PENALTY = 15            # 内存过高
    CRASH_PENALTY = 25                  # 崩溃记录
    REGISTRY_MISMATCH_PENALTY = 20      # Registry 不一致
    ENV_INVALID_PENALTY = 50            # .env 无效
    ZOMBIE_PENALTY = 40                 # 僵尸进程
    FREQUENT_RESTART_PENALTY = 35       # 频繁重启
    
    # 加分项
    STABLE_BONUS = 10                   # 长期稳定运行
    
    # 阈值
    HIGH_CPU_THRESHOLD = 80             # CPU 阈值 (%)
    HIGH_MEMORY_THRESHOLD = 500         # 内存阈值 (MB)
    STABLE_HOURS = 24                   # 稳定运行时长 (小时)
    FREQUENT_RESTART_THRESHOLD = 3      # 频繁重启阈值 (24小时内)


class HealthScoreCalculator:
    """
    健康评分计算器
    
    计算维度：
    + 心跳正常
    + CPU 正常
    + 无崩溃记录
    + Registry 一致
    - 崩溃次数
    - 重启次数
    """
    
    def __init__(self):
        self._scores: Dict[str, dict] = {}
        self._calculation_count = 0
    
    def calculate(
        self,
        instance_id: str,
        health_status: dict,
        bot_stats: dict = None
    ) -> dict:
        """
        计算健康评分
        
        Args:
            health_status: BotHealthStatus 的字典
            bot_stats: BOT 统计信息（重启次数、崩溃次数等）
        
        Returns:
            {
                'score': int,           # 0-100
                'level': str,           # 'excellent', 'good', 'warning', 'critical', 'dead'
                'deductions': list,     # 扣分项详情
                'bonuses': list,        # 加分项详情
                'recommendation': str   # 修复建议
            }
        """
        self._calculation_count += 1
        
        score = HealthScoreConfig.BASE_SCORE
        deductions = []
        bonuses = []
        
        # 1. 心跳检查
        if not health_status.get('heartbeat_ok', True):
            score -= HealthScoreConfig.MISSING_HEARTBEAT_PENALTY
            deductions.append({
                'item': '心跳缺失',
                'penalty': HealthScoreConfig.MISSING_HEARTBEAT_PENALTY,
                'reason': '超过心跳超时阈值'
            })
        
        # 2. Registry 一致性
        if not health_status.get('registry_running', False):
            score -= HealthScoreConfig.REGISTRY_MISMATCH_PENALTY
            deductions.append({
                'item': 'Registry 不一致',
                'penalty': HealthScoreConfig.REGISTRY_MISMATCH_PENALTY,
                'reason': '进程状态与 Registry 不匹配'
            })
        
        # 3. 进程状态
        status = health_status.get('status', 'unknown')
        
        if status == 'zombie':
            score -= HealthScoreConfig.ZOMBIE_PENALTY
            deductions.append({
                'item': '僵尸进程',
                'penalty': HealthScoreConfig.ZOMBIE_PENALTY,
                'reason': 'Registry 标记运行但进程已死'
            })
        
        elif status == 'env_invalid':
            score -= HealthScoreConfig.ENV_INVALID_PENALTY
            deductions.append({
                'item': '.env 无效',
                'penalty': HealthScoreConfig.ENV_INVALID_PENALTY,
                'reason': '.env 文件验证失败'
            })
        
        elif status == 'no_heartbeat':
            # 已在上面扣分，这里不再重复
            pass
        
        # 4. 统计信息扣分
        if bot_stats:
            # 崩溃次数
            crash_count = bot_stats.get('crash_count', 0)
            if crash_count > 0:
                penalty = min(crash_count * HealthScoreConfig.CRASH_PENALTY, 50)
                score -= penalty
                deductions.append({
                    'item': '崩溃记录',
                    'penalty': penalty,
                    'reason': f'历史崩溃 {crash_count} 次'
                })
            
            # 频繁重启
            restart_count_24h = bot_stats.get('restart_count_24h', 0)
            if restart_count_24h >= HealthScoreConfig.FREQUENT_RESTART_THRESHOLD:
                score -= HealthScoreConfig.FREQUENT_RESTART_PENALTY
                deductions.append({
                    'item': '频繁重启',
                    'penalty': HealthScoreConfig.FREQUENT_RESTART_PENALTY,
                    'reason': f'24小时内重启 {restart_count_24h} 次'
                })
            
            # 长期稳定运行加分
            uptime_hours = bot_stats.get('uptime_hours', 0)
            if uptime_hours >= HealthScoreConfig.STABLE_HOURS and score >= 80:
                score += HealthScoreConfig.STABLE_BONUS
                bonuses.append({
                    'item': '长期稳定',
                    'bonus': HealthScoreConfig.STABLE_BONUS,
                    'reason': f'稳定运行 {uptime_hours} 小时'
                })
        
        # 确保分数在 0-100 范围内
        score = max(0, min(100, score))
        
        # 确定健康等级
        level = self._get_level(score)
        
        # 生成修复建议
        recommendation = self._get_recommendation(score, deductions)
        
        result = {
            'score': score,
            'level': level,
            'deductions': deductions,
            'bonuses': bonuses,
            'recommendation': recommendation,
            'calculated_at': datetime.utcnow().isoformat()
        }
        
        # 保存结果
        self._scores[instance_id] = result
        
        logger.info(
            f"[HealthScore] 📊 {instance_id}: {score}/100 ({level}) - {recommendation}"
        )
        
        return result
    
    def _get_level(self, score: int) -> str:
        """根据分数确定健康等级"""
        if score >= 90:
            return 'excellent'  # 优秀
        elif score >= 70:
            return 'good'       # 良好
        elif score >= 50:
            return 'warning'    # 警告
        elif score >= 20:
            return 'critical'   # 危险
        else:
            return 'dead'       # 死亡
    
    def _get_recommendation(self, score: int, deductions: list) -> str:
        """生成修复建议"""
        if score >= 90:
            return '健康状态优秀，无需处理'
        elif score >= 70:
            return '健康状态良好，持续观察'
        elif score >= 50:
            return '健康状态警告，建议关注'
        elif score >= 20:
            issues = [d['item'] for d in deductions[:2]]
            return f'健康状态危险，需要修复: {", ".join(issues)}'
        else:
            return '健康状态死亡，必须立即修复'
    
    def should_repair(self, instance_id: str, threshold: int = 50) -> bool:
        """
        判断是否需要修复
        
        Args:
            instance_id: BOT 实例 ID
            threshold: 修复阈值（低于此分数才修复）
        
        Returns:
            True = 需要修复
        """
        score_data = self._scores.get(instance_id)
        if not score_data:
            return True  # 无评分数据，默认需要检查
        
        return score_data['score'] < threshold
    
    def get_score(self, instance_id: str) -> Optional[dict]:
        """获取评分结果"""
        return self._scores.get(instance_id)
    
    def get_all_scores(self) -> Dict[str, dict]:
        """获取所有评分"""
        return self._scores.copy()
    
    def get_stats(self) -> dict:
        """获取统计信息"""
        scores = list(self._scores.values())
        
        if not scores:
            return {
                'total_calculated': 0,
                'avg_score': 0,
                'min_score': 0,
                'max_score': 0,
            }
        
        score_values = [s['score'] for s in scores]
        
        return {
            'total_calculated': self._calculation_count,
            'total_bots': len(scores),
            'avg_score': sum(score_values) / len(score_values),
            'min_score': min(score_values),
            'max_score': max(score_values),
            'excellent': sum(1 for s in scores if s['level'] == 'excellent'),
            'good': sum(1 for s in scores if s['level'] == 'good'),
            'warning': sum(1 for s in scores if s['level'] == 'warning'),
            'critical': sum(1 for s in scores if s['level'] == 'critical'),
            'dead': sum(1 for s in scores if s['level'] == 'dead'),
        }


# 🔥 全局单例
health_score_calculator = HealthScoreCalculator()
