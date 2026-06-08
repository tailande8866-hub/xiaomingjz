# ============================================
# 清理项目，只保留生产部署必需的文件
# ============================================

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host " 清理项目 - 准备生产部署" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

$filesToDelete = @(
    # 备份文件
    "*.zip",
    "accounting_bot.db",
    
    # 测试和调试文件
    "check_*.py",
    "debug_*.py",
    "fix_*.py",
    "migrate_*.py",
    "query_*.py",
    "restore_*.py",
    "test_*.py",
    "simple_test.py",
    "update_user_info.py",
    "cleanup_*.py",
    "clear_test_data.py",
    "create_main_bot_record.py",
    
    # 旧的部署脚本
    "auto_deploy.sh",
    "one_click_deploy*.sh",
    "quick_deploy.sh",
    "setup_config.sh",
    "setup_ssl.sh",
    "diagnose_menu_issue.sh",
    "deploy.bat",
    
    # 打包脚本
    "package_*.ps1",
    
    # 重启脚本
    "restart_*.bat",
    "restart_*.ps1",
    "restart_bots.py",
    "clean_restart.ps1",
    
    # PM2配置（不需要）
    "ecosystem.config.js",
    "accounting-bot.service",
    
    # 文档文件（保留DEPLOY.md, DEPLOY_GUIDE.md, QUICK_DEPLOY.md, README.md）
    "ADMIN_PERMISSIONS_COMPLETE.md",
    "AUTHORIZATION_IMPLEMENTATION_SUMMARY.md",
    "AUTHORIZATION_QUICK_REFERENCE.md",
    "AUTO_BACKUP_GUIDE.md",
    "BOT_ID_USAGE_EXAMPLES.py",
    "BUTTON_OPTIMIZATION_GUIDE.md",
    "CLEANUP_COMPLETE_REPORT.md",
    "COMMANDS_COMPLETE_LIST.md",
    "COMMANDS_LIST_V2.md",
    "DB_OPTIMIZATION_EXAMPLES.py",
    "DB_OPTIMIZATION_SAAS_EXAMPLE.py",
    "DEPLOYMENT_CHECKLIST.md",
    "DEPLOYMENT_COMPLETE_GUIDE.md",
    "DEPLOYMENT_PRE_CHECKLIST.md",
    "DEPLOYMENT_README.md",
    "DEPLOYMENT_SUMMARY.md",
    "DEPLOY_CONFIG_OPTIONS.md",
    "DEPLOY_QUICK_REFERENCE.md",
    "DOCKER_COMPOSE_DEPLOY_FILES.md",
    "DOCKER_COMPOSE_PACKAGE_COMPLETE.md",
    "DOCKER_DEPLOY_FILES_CHECKLIST.md",
    "DOCKER_DEPLOY_README.md",
    "DOCKER_PRODUCTION_DEPLOY.md",
    "GIT_SETUP_GUIDE.md",
    "HANDLER_OPTIMIZATION_EXAMPLE.py",
    "KEYWORD_FEATURE_INVENTORY.md",
    "MONITORING_GUIDE.md",
    "NEW_FEATURE_DEVELOPMENT_GUIDE.md",
    "ONE_CLICK_DEPLOY_GUIDE.md",
    "PERMISSION_SYSTEM_COMPLETE.md",
    "PRODUCTION_CHECKLIST.md",
    "PRODUCTION_DEPLOYMENT_GUIDE.md",
    "QUICK_DEPLOY_CARD.md",
    "QUICK_START.md",
    "QUICK_START_DEPLOYMENT.md",
    "RATE_LIMIT_EXAMPLES.py",
    "REPOSITORY_USAGE_EXAMPLES.py",
    "SERVER_DEPLOYMENT_GUIDE.md",
    "SSL_SETUP_GUIDE.md",
    "START_GUIDE.md",
    "TEST_USERNAME_ADD_OPERATOR.md",
    "UPLOAD_TO_SERVER_GUIDE.md",
    "WEB_SYSTEM_READY.md",
    "WEB_TEST_GUIDE.md",
    "功能说明表.md",
    "命令表.md",
    "完整命令表.md",
    
    # JSON调试文件
    "binance_debug.json",
    "binance_full_data.json",
    
    # 旧的环境配置文件
    ".env.template",
    ".env.prod.example",
    
    # Docker Compose备选文件
    "docker-compose.prod.yml"
)

Write-Host "🗑️  正在删除不必要的文件..." -ForegroundColor Yellow
Write-Host ""

$count = 0
foreach ($pattern in $filesToDelete) {
    $files = Get-ChildItem -Path "." -Filter $pattern -File -ErrorAction SilentlyContinue
    foreach ($file in $files) {
        Remove-Item -Path $file.FullName -Force -ErrorAction SilentlyContinue
        Write-Host "  已删除: $($file.Name)" -ForegroundColor Gray
        $count++
    }
}

Write-Host ""
Write-Host "✅ 共删除 $count 个文件" -ForegroundColor Green
Write-Host ""

# 删除空目录
Write-Host "📁 清理空目录..." -ForegroundColor Yellow
$dirs = @("nginx")
foreach ($dir in $dirs) {
    if (Test-Path $dir) {
        Remove-Item -Path $dir -Recurse -Force -ErrorAction SilentlyContinue
        Write-Host "  已删除目录: $dir" -ForegroundColor Gray
    }
}

Write-Host ""
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "✅ 清理完成！" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "📋 保留的核心文件：" -ForegroundColor Yellow
Write-Host "  ✅ src/ - 源代码" -ForegroundColor Green
Write-Host "  ✅ config/ - 配置文件" -ForegroundColor Green
Write-Host "  ✅ scripts/ - 数据库迁移脚本" -ForegroundColor Green
Write-Host "  ✅ docs/ - 文档" -ForegroundColor Green
Write-Host "  ✅ .env - 环境配置（不上传Git）" -ForegroundColor Green
Write-Host "  ✅ .env.prod - 生产配置模板" -ForegroundColor Green
Write-Host "  ✅ requirements.txt - Python依赖" -ForegroundColor Green
Write-Host "  ✅ Dockerfile - Docker配置" -ForegroundColor Green
Write-Host "  ✅ docker-compose.yml - Docker Compose配置" -ForegroundColor Green
Write-Host "  ✅ .gitignore - Git忽略配置" -ForegroundColor Green
Write-Host "  ✅ main.py - 启动文件" -ForegroundColor Green
Write-Host "  ✅ deploy.sh - 一键部署脚本" -ForegroundColor Green
Write-Host "  ✅ git_cleanup.ps1 - Git清理脚本" -ForegroundColor Green
Write-Host "  ✅ DEPLOY.md - 部署文档" -ForegroundColor Green
Write-Host "  ✅ DEPLOY_GUIDE.md - 详细部署指南" -ForegroundColor Green
Write-Host "  ✅ QUICK_DEPLOY.md - 快速部署命令" -ForegroundColor Green
Write-Host "  - README.md" -ForegroundColor Green
Write-Host ""

