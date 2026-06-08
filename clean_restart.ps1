# ========================================
# Clean Restart Script for Telegram Bot
# ========================================
# 功能：
# 1. 停止所有旧 Python Bot 进程
# 2. 删除所有 Python 缓存文件
# 3. 启动最新版本的 Bot
# ========================================

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Telegram Bot Clean Restart Script" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# 步骤1: 停止所有旧进程
Write-Host "[1/3] Stopping all Python processes..." -ForegroundColor Yellow
$pythonProcesses = Get-Process python -ErrorAction SilentlyContinue
if ($pythonProcesses) {
    Write-Host "  Found $($pythonProcesses.Count) Python process(es), stopping..." -ForegroundColor Gray
    Stop-Process -Name python -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
    
    # 验证是否已停止
    $remaining = Get-Process python -ErrorAction SilentlyContinue
    if ($remaining) {
        Write-Host "  ⚠️  Warning: $($remaining.Count) process(es) still running" -ForegroundColor Red
    } else {
        Write-Host "  ✅ All Python processes stopped" -ForegroundColor Green
    }
} else {
    Write-Host "  ℹ️  No Python processes found" -ForegroundColor Gray
}
Write-Host ""

# 步骤2: 删除所有 Python 缓存
Write-Host "[2/3] Cleaning Python cache files..." -ForegroundColor Yellow
$cacheDirs = Get-ChildItem -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue
if ($cacheDirs) {
    Write-Host "  Found $($cacheDirs.Count) __pycache__ directorie(s), removing..." -ForegroundColor Gray
    $cacheDirs | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host "  ✅ Cache cleaned" -ForegroundColor Green
} else {
    Write-Host "  ℹ️  No cache directories found" -ForegroundColor Gray
}
Write-Host ""

# 步骤3: 启动 Bot
Write-Host "[3/3] Starting Telegram Bot..." -ForegroundColor Yellow
Write-Host ""

# 切换到项目目录
Set-Location "d:\记账机器人\AAAJIZHANG-main"

# 显示启动信息
Write-Host "========================================" -ForegroundColor Green
Write-Host "  Starting Bot..." -ForegroundColor Green
Write-Host "  Project: d:\记账机器人\AAAJIZHANG-main" -ForegroundColor Green
Write-Host "  Time: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""

# 启动 Bot（前台运行，可以看到日志）
python main.py

# 如果 Bot 退出，显示提示
Write-Host ""
Write-Host "========================================" -ForegroundColor Red
Write-Host "  Bot has stopped" -ForegroundColor Red
Write-Host "========================================" -ForegroundColor Red
