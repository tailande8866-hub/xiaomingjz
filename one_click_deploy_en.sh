#!/bin/bash

# SaaS Accounting Bot - One-Click Deployment Script

set -e

echo ""
echo "=========================================="
echo "  SaaS Accounting Bot - One-Click Deploy"
echo "=========================================="
echo ""

# Check if running in correct directory
if [ ! -f "docker-compose.prod.yml" ]; then
    echo "Error: Please run this script in project root directory"
    exit 1
fi

echo "This script will automatically:"
echo "   1. Configure environment variables"
echo "   2. Obtain SSL certificate"
echo "   3. Start Docker services"
echo "   4. Verify deployment status"
echo ""

read -p "Continue? (y/n): " confirm
if [ "$confirm" != "y" ] && [ "$confirm" != "Y" ]; then
    echo "Deployment cancelled"
    exit 0
fi

echo ""

# Step 1: Configure environment variables
echo "=========================================="
echo "Step 1/4: Configure Environment Variables"
echo "=========================================="
echo ""

if [ ! -f ".env" ]; then
    echo "Running configuration wizard..."
    chmod +x setup_config.sh
    ./setup_config.sh
else
    echo ".env file already exists"
    read -p "Reconfigure? (y/n): " reconfig
    if [ "$reconfig" = "y" ] || [ "$reconfig" = "Y" ]; then
        chmod +x setup_config.sh
        ./setup_config.sh
    fi
fi

echo ""

# Step 2: Configure SSL certificate
echo "=========================================="
echo "Step 2/4: Configure SSL Certificate"
echo "=========================================="
echo ""

if [ ! -f "nginx/ssl/fullchain.pem" ] || [ ! -f "nginx/ssl/privkey.pem" ]; then
    echo "Running SSL configuration wizard..."
    chmod +x setup_ssl.sh
    ./setup_ssl.sh
else
    echo "SSL certificate already exists"
    read -p "Renew certificate? (y/n): " renew_ssl
    if [ "$renew_ssl" = "y" ] || [ "$renew_ssl" = "Y" ]; then
        chmod +x setup_ssl.sh
        ./setup_ssl.sh
    fi
fi

echo ""

# Step 3: Start services
echo "=========================================="
echo "Step 3/4: Start Docker Services"
echo "=========================================="
echo ""

echo "Building and starting services..."
echo ""

chmod +x deploy.sh
./deploy.sh

if [ $? -ne 0 ]; then
    echo ""
    echo "Deployment failed, please check logs"
    docker-compose -f docker-compose.prod.yml logs --tail=50
    exit 1
fi

echo ""

# Step 4: Verify deployment
echo "=========================================="
echo "Step 4/4: Verify Deployment Status"
echo "=========================================="
echo ""

sleep 5

# Check container status
echo "Checking container status..."
if docker-compose -f docker-compose.prod.yml ps | grep -q "Up"; then
    echo "All services running normally"
else
    echo "Some services not running properly"
    docker-compose -f docker-compose.prod.yml ps
    exit 1
fi

echo ""

# Show service status
echo "=========================================="
echo "  Service Status"
echo "=========================================="
docker-compose -f docker-compose.prod.yml ps

echo ""

# Get domain
DOMAIN=$(grep "^DOMAIN=" .env | cut -d'=' -f2)

echo "=========================================="
echo "  Access URLs"
echo "=========================================="
echo "   HTTPS: https://$DOMAIN"
echo "   Health: https://$DOMAIN/health"
echo ""

echo "=========================================="
echo "  Common Commands"
echo "=========================================="
echo "   View logs: docker-compose -f docker-compose.prod.yml logs -f bot"
echo "   Restart: docker-compose -f docker-compose.prod.yml restart"
echo "   Stop: docker-compose -f docker-compose.prod.yml down"
echo "   Enter container: docker exec -it saas-bot bash"
echo ""

echo "=========================================="
echo "  Deployment Complete!"
echo "=========================================="
echo ""
echo "SaaS Accounting Bot has been successfully deployed"
echo ""
echo "Next steps:"
echo "   1. Search for your Bot in Telegram"
echo "   2. Send /start command to test"
echo "   3. Check documentation for features"
echo ""
echo "Tips:"
echo "   - View logs: docker-compose -f docker-compose.prod.yml logs -f"
echo "   - Backup: ./scripts/backup.sh"
echo "   - Update: git pull && ./deploy.sh"
echo ""
