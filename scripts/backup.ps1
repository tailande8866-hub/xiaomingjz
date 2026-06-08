# 数据库自动备份脚本 (PowerShell 版本)
# 
# 功能：
# 1. 每日自动备份 SQLite 数据库
# 2. 保留最近 7 天的备份
#
# 使用方法：
#   1. 创建计划任务：
#      schtasks /create /tn "BotBackup" /tr "powershell -ExecutionPolicy Bypass -File D:\记账机器人\AAAJIZHANG-main\scripts\backup.ps1" /sc daily /st 02:00
#   2. 或手动运行测试：.\scripts\backup.ps1

# ==================== 配置 ====================
$ProjectDir = Split-Path -Parent $PSScriptRoot
$DbFile = Join-Path $ProjectDir "accounting_bot.db"
$BackupDir = Join-Path $ProjectDir "backups"
$RetentionDays = 7

# ==================== 检查 ====================
if (-not (Test-Path $DbFile)) {
    Write-Host "❌ 数据库文件不存在: $DbFile" -ForegroundColor Red
    exit 1
}

# 创建备份目录
if (-not (Test-Path $BackupDir)) {
    New-Item -ItemType Directory -Path $BackupDir | Out-Null
}

# ==================== 备份 ====================
$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$BackupFile = Join-Path $BackupDir "db_backup_$Timestamp.db"

Write-Host "🔧 开始备份数据库..." -ForegroundColor Cyan
Write-Host "   源文件: $DbFile"
Write-Host "   目标文件: $BackupFile"

Copy-Item -Path $DbFile -Destination $BackupFile -Force

if (Test-Path $BackupFile) {
    $Size = (Get-Item $BackupFile).Length
    Write-Host "✅ 备份成功: $BackupFile ($Size bytes)" -ForegroundColor Green
} else {
    Write-Host "❌ 备份失败" -ForegroundColor Red
    exit 1
}

# ==================== 清理旧备份 ====================
Write-Host ""
Write-Host "🗑️  清理 ${RetentionDays} 天前的旧备份..." -ForegroundColor Yellow

$CutoffDate = (Get-Date).AddDays(-$RetentionDays)
$OldBackups = Get-ChildItem -Path $BackupDir -Filter "db_backup_*.db" | Where-Object { $_.LastWriteTime -lt $CutoffDate }

foreach ($backup in $OldBackups) {
    Remove-Item $backup.FullName -Force
    Write-Host "   删除: $($backup.Name)" -ForegroundColor Gray
}

Write-Host "✅ 清理完成" -ForegroundColor Green

# ==================== 统计 ====================
$TotalBackups = (Get-ChildItem -Path $BackupDir -Filter "db_backup_*.db").Count

Write-Host ""
Write-Host "📊 当前备份数量: $TotalBackups" -ForegroundColor Cyan
Write-Host "   备份目录: $BackupDir"
Write-Host "   保留策略: 最近 $RetentionDays 天"
Write-Host ""
Write-Host "🎉 备份任务完成！" -ForegroundColor Green

