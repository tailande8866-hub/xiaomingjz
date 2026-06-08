"""
Web API 路由
"""
from flask import jsonify, request, send_file, render_template
from src.web.auth import token_required
from src.web.services import BillService
import io
import pandas as pd
import asyncio


def run_async(coro):
    """在 Flask 中运行异步函数"""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def register_routes(app):
    """注册所有路由"""
    
    @app.route('/')
    @token_required
    def index():
        """主页 - 今日账单"""
        chat_id = request.args.get('chatId')
        bot_id = request.token_payload.get('bot_id')
        
        # 获取今日账单数据
        service = BillService(bot_id, chat_id)
        today_data = run_async(service.get_today_bill())
        
        return render_template(
            'index.html',
            chat_id=chat_id,
            bot_id=bot_id,
            data=today_data
        )
    
    @app.route('/api/bill/today')
    @token_required
    def api_today_bill():
        """API: 获取今日账单"""
        chat_id = request.args.get('chatId')
        bot_id = request.token_payload.get('bot_id')
        
        service = BillService(bot_id, chat_id)
        data = run_async(service.get_today_bill())
        
        return jsonify(data)
    
    @app.route('/api/bill/history')
    @token_required
    def api_history_bill():
        """API: 获取历史账单"""
        chat_id = request.args.get('chatId')
        bot_id = request.token_payload.get('bot_id')
        days = request.args.get('days', 7, type=int)
        
        service = BillService(bot_id, chat_id)
        data = run_async(service.get_history_bill(days=days))
        
        return jsonify(data)
    
    @app.route('/api/bill/detail')
    @token_required
    def api_bill_detail():
        """API: 获取明细流水"""
        chat_id = request.args.get('chatId')
        bot_id = request.token_payload.get('bot_id')
        page = request.args.get('page', 1, type=int)
        page_size = request.args.get('page_size', 50, type=int)
        
        service = BillService(bot_id, chat_id)
        data = run_async(service.get_bill_detail(page=page, page_size=page_size))
        
        return jsonify(data)
    
    @app.route('/api/stats/summary')
    @token_required
    def api_stats_summary():
        """API: 统计汇总"""
        chat_id = request.args.get('chatId')
        bot_id = request.token_payload.get('bot_id')
        days = request.args.get('days', 30, type=int)
        
        service = BillService(bot_id, chat_id)
        data = run_async(service.get_stats_summary(days=days))
        
        return jsonify(data)
    
    @app.route('/api/export/excel')
    @token_required
    def api_export_excel():
        """API: 导出 Excel"""
        chat_id = request.args.get('chatId')
        bot_id = request.token_payload.get('bot_id')
        days = request.args.get('days', 30, type=int)
        
        service = BillService(bot_id, chat_id)
        df = run_async(service.export_to_excel(days=days))
        
        # 生成 Excel 文件
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df.to_excel(writer, index=False, sheet_name='账单明细')
        
        output.seek(0)
        
        return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=f'bill_{chat_id}_{days}days.xlsx'
        )
