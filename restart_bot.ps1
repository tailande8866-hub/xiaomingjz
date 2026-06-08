# 重启记账机器人脚本
# 使用前请确认要停止的进程ID

Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "  记账机器人重启脚本" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host ""

# 显示当前运行的Python进程
Write-Host "当前运行的Python进程：" -ForegroundColor Yellow
Get-Process python | Select-Object Id, ProcessName, StartTime | Format-Table -AutoSize

# 询问用户是否继续
Write-Host ""
$response = Read-Host "是否要停止所有Python进程并重启机器人？(y/n)"

if ($response -eq 'y' -or $response -eq 'Y') {
    Write-Host ""
    Write-Host "正在停止Python进程..." -ForegroundColor Yellow
    
    # 停止所有Python进程
    Get-Process python | Stop-Process -Force
    
    Write-Host "等待2秒..." -ForegroundColor Yellow
    Start-Sleep -Seconds 2
    
    Write-Host "正在启动机器人..." -ForegroundColor Green
    Write-Host ""
    
    # 启动机器人
    cd "d:\记账机器人\AAAJIZHANG-main"
    python main.py
} else {
    Write-Host "已取消重启操作" -ForegroundColor Yellow
}
