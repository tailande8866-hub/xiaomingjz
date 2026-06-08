# Git 快速初始化脚本
# 使用方法: .\git_init_quick.ps1 -RepoUrl "https://github.com/username/repo.git"

param(
    [Parameter(Mandatory=$true)]
    [string]$RepoUrl,
    
    [string]$CommitMessage = "Initial commit: SaaS记账机器人 v1.0"
)

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Git 仓库快速初始化" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# 检查 Git 是否安装
Write-Host "[1/5] 检查 Git 安装..." -ForegroundColor Yellow
try {
    $gitVersion = git --version 2>&1
    Write-Host "✅ Git 已安装: $gitVersion" -ForegroundColor Green
} catch {
    Write-Host "❌ Git 未安装！" -ForegroundColor Red
    Write-Host "请先下载并安装 Git: https://git-scm.com/download/win" -ForegroundColor Yellow
    exit 1
}
Write-Host ""

# 检查是否已初始化
Write-Host "[2/5] 检查 Git 状态..." -ForegroundColor Yellow
if (Test-Path ".git") {
    Write-Host "⚠️  Git 仓库已存在" -ForegroundColor Yellow
    $continue = Read-Host "是否重新初始化？(y/n)"
    if ($continue -ne 'y') {
        Write-Host "取消操作" -ForegroundColor Gray
        exit 0
    }
    Remove-Item ".git" -Recurse -Force
    Write-Host "✅ 已清理旧的 Git 仓库" -ForegroundColor Green
}
Write-Host ""

# 配置用户信息
Write-Host "[3/5] 配置 Git 用户信息..." -ForegroundColor Yellow
$globalName = git config --global user.name
$globalEmail = git config --global user.email

if (-not $globalName -or -not $globalEmail) {
    Write-Host "需要配置 Git 用户信息:" -ForegroundColor Yellow
    $name = Read-Host "请输入您的名字"
    $email = Read-Host "请输入您的邮箱"
    
    git config --global user.name $name
    git config --global user.email $email
    
    Write-Host "✅ 配置完成: $name <$email>" -ForegroundColor Green
} else {
    Write-Host "✅ 使用现有配置: $globalName <$globalEmail>" -ForegroundColor Green
}
Write-Host ""

# 初始化并提交
Write-Host "[4/5] 初始化 Git 仓库并提交..." -ForegroundColor Yellow

try {
    # 初始化
    git init
    Write-Host "  ✓ Git 仓库已初始化" -ForegroundColor Gray
    
    # 添加文件
    git add .
    Write-Host "  ✓ 文件已添加到暂存区" -ForegroundColor Gray
    
    # 提交
    git commit -m $CommitMessage
    Write-Host "  ✓ 首次提交完成" -ForegroundColor Green
    
} catch {
    Write-Host "❌ Git 操作失败: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
Write-Host ""

# 添加远程仓库
Write-Host "[5/5] 添加远程仓库..." -ForegroundColor Yellow

try {
    git remote add origin $RepoUrl
    Write-Host "✅ 远程仓库已添加: $RepoUrl" -ForegroundColor Green
} catch {
    Write-Host "❌ 添加远程仓库失败: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
Write-Host ""

# 重命名分支
git branch -M main

# 显示总结
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  初始化完成！" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "📋 下一步操作:" -ForegroundColor Yellow
Write-Host ""
Write-Host "1️⃣  推送到 GitHub:" -ForegroundColor White
Write-Host "   git push -u origin main" -ForegroundColor Gray
Write-Host ""
Write-Host "2️⃣  如果需要认证，请使用 Personal Access Token:" -ForegroundColor White
Write-Host "   获取地址: https://github.com/settings/tokens" -ForegroundColor Gray
Write-Host ""
Write-Host "3️⃣  验证推送成功:" -ForegroundColor White
Write-Host "   访问您的仓库页面查看文件" -ForegroundColor Gray
Write-Host ""
Write-Host "💡 提示: 首次推送时可能需要登录 GitHub 账号" -ForegroundColor Cyan
Write-Host ""

# 询问是否立即推送
$pushNow = Read-Host "是否现在推送到远程仓库？(y/n)"
if ($pushNow -eq 'y') {
    Write-Host ""
    Write-Host "正在推送..." -ForegroundColor Yellow
    try {
        git push -u origin main
        Write-Host ""
        Write-Host "🎉 推送成功！" -ForegroundColor Green
        Write-Host "请访问您的仓库页面验证: $RepoUrl" -ForegroundColor Cyan
    } catch {
        Write-Host ""
        Write-Host "⚠️  推送失败，可能需要认证" -ForegroundColor Yellow
        Write-Host "请手动执行: git push -u origin main" -ForegroundColor Gray
        Write-Host ""
        Write-Host "如果提示输入密码，请使用 Personal Access Token:" -ForegroundColor Yellow
        Write-Host "1. 访问: https://github.com/settings/tokens" -ForegroundColor Gray
        Write-Host "2. 生成新 Token（勾选 repo 权限）" -ForegroundColor Gray
        Write-Host "3. 复制 Token 作为密码粘贴" -ForegroundColor Gray
    }
}

Write-Host ""
Write-Host "详细文档请查看: GIT_SETUP_GUIDE.md" -ForegroundColor Cyan
