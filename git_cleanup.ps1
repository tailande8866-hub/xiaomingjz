# ============================================
# Git 仓库清理和重新初始化脚本
# ============================================

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host " Git 仓库清理和重新初始化" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

# 检查是否在Git仓库中
if (-not (Test-Path ".git")) {
    Write-Host "❌ 未找到 .git 目录，请先运行 git init" -ForegroundColor Red
    exit 1
}

Write-Host "⚠️  正在清理Git历史..." -ForegroundColor Yellow

# 删除 .git 目录
Remove-Item -Path ".git" -Recurse -Force

Write-Host "✅ 已删除旧Git历史" -ForegroundColor Green
Write-Host ""

Write-Host "🔄 正在重新初始化Git仓库..." -ForegroundColor Yellow

# 重新初始化Git
git init
git branch -m main

Write-Host "✅ 已重新初始化Git仓库" -ForegroundColor Green
Write-Host ""

Write-Host "📝 添加所有文件到Git..." -ForegroundColor Yellow
git add .

Write-Host "✅ 文件已添加到暂存区" -ForegroundColor Green
Write-Host ""

Write-Host "💾 提交代码..." -ForegroundColor Yellow
git commit -m "Initial commit: Production ready deployment"

Write-Host "✅ 代码已提交" -ForegroundColor Green
Write-Host ""

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "✅ Git 仓库清理完成！" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "📋 下一步操作：" -ForegroundColor Yellow
Write-Host "1. 在GitHub/GitLab创建新的私有仓库" -ForegroundColor White
Write-Host "2. 复制仓库地址" -ForegroundColor White
Write-Host "3. 运行以下命令：" -ForegroundColor White
Write-Host "   git remote add origin <你的仓库地址>" -ForegroundColor Cyan
Write-Host "   git push -u origin main" -ForegroundColor Cyan
Write-Host ""
