"""
汇率查询服务
"""
import httpx
from typing import Optional, Dict
from config import config


class ExchangeService:
    """汇率服务类"""

    @staticmethod
    async def get_huobi_usdt_price() -> Optional[float]:
        """
        获取火币(HTX)USDT价格
        使用多个API源作为备用
        """
        import logging
        logger = logging.getLogger(__name__)
        
        # 尝试多个API源
        api_sources = [
            {
                "name": "HTX (新火币)",
                "url": "https://api.huobi.pro/market/detail/merged",
                "params": {"symbol": "usdtcny"},
                "parse": lambda data: float(data.get("tick", {}).get("close")) if data.get("status") == "ok" else None
            },
            {
                "name": "币安C2C参考",
                "url": "https://api.binance.com/api/v3/ticker/price",
                "params": {"symbol": "USDTUSDC"},  # 使用USDT/USDC作为参考
                "parse": lambda data: float(data.get("price", 7.25))  # 默认值7.25
            }
        ]
        
        for source in api_sources:
            try:
                logger.info(f"尝试从 {source['name']} 获取价格...")
                async with httpx.AsyncClient() as client:
                    response = await client.get(
                        source["url"],
                        params=source["params"],
                        timeout=5.0
                    )
                    logger.info(f"{source['name']} API响应状态码: {response.status_code}")
                    if response.status_code == 200:
                        data = response.json()
                        logger.info(f"{source['name']} API响应数据: {data}")
                        price = source["parse"](data)
                        if price:
                            logger.info(f"从 {source['name']} 获取到价格: {price}")
                            return price
            except Exception as e:
                logger.error(f"从 {source['name']} 获取价格失败: {e}")
                continue
        
        logger.error("所有API源都获取失败，返回默认价格 7.25")
        return 7.25  # 返回一个合理的默认值

    @staticmethod
    async def get_okex_usdt_price() -> Optional[float]:
        """
        获取欧易(OKX)USDT价格
        使用多个API源作为备用
        """
        import logging
        logger = logging.getLogger(__name__)
        
        # 尝试多个API源
        api_sources = [
            {
                "name": "OKX (欧易)",
                "url": "https://www.okx.com/api/v5/market/ticker",
                "params": {"instId": "USDT-CNY"},
                "parse": lambda data: float(data.get("data", [{}])[0].get("last")) if data.get("code") == "0" and data.get("data") else None
            },
            {
                "name": "CoinGecko参考",
                "url": "https://api.coingecko.com/api/v3/simple/price",
                "params": {"ids": "tether", "vs_currencies": "cny"},
                "parse": lambda data: float(data.get("tether", {}).get("cny", 7.25))
            }
        ]
        
        for source in api_sources:
            try:
                logger.info(f"尝试从 {source['name']} 获取价格...")
                async with httpx.AsyncClient() as client:
                    response = await client.get(
                        source["url"],
                        params=source["params"],
                        timeout=5.0
                    )
                    logger.info(f"{source['name']} API响应状态码: {response.status_code}")
                    if response.status_code == 200:
                        data = response.json()
                        logger.info(f"{source['name']} API响应数据: {data}")
                        price = source["parse"](data)
                        if price:
                            logger.info(f"从 {source['name']} 获取到价格: {price}")
                            return price
            except Exception as e:
                logger.error(f"从 {source['name']} 获取价格失败: {e}")
                continue
        
        logger.error("所有API源都获取失败，返回默认价格 7.25")
        return 7.25  # 返回一个合理的默认值

    @staticmethod
    async def get_huobi_c2c_top10() -> Optional[list]:
        """
        获取火币(HTX)USDT价格信息（使用官方API + CoinGecko）
        返回包含市场行情和USDT/CNY参考价的数据
        """
        import logging
        logger = logging.getLogger(__name__)
        
        try:
            result = {
                "market_prices": [],  # HTX市场价格
                "usdt_cny_price": 0   # USDT/CNY参考价格
            }
            
            async with httpx.AsyncClient() as client:
                # 1. 获取HTX主流币种价格
                symbols = ["btcusdt", "ethusdt", "ltcusdt"]
                for symbol in symbols:
                    try:
                        response = await client.get(
                            "https://api.huobi.pro/market/detail/merged",
                            params={"symbol": symbol},
                            timeout=5
                        )
                        
                        if response.status_code == 200:
                            data = response.json()
                            if data.get("status") == "ok" and data.get("tick"):
                                tick = data["tick"]
                                result["market_prices"].append({
                                    "symbol": symbol.upper(),
                                    "price": float(tick.get("close", 0)),
                                    "high": float(tick.get("high", 0)),
                                    "low": float(tick.get("low", 0))
                                })
                    except Exception as e:
                        logger.warning(f"获取{symbol}价格失败: {e}")
                        continue
                
                # 2. 获取USDT/CNY参考价格（使用CoinGecko）
                try:
                    response = await client.get(
                        "https://api.coingecko.com/api/v3/simple/price",
                        params={
                            "ids": "tether",
                            "vs_currencies": "cny"
                        },
                        timeout=5
                    )
                    
                    if response.status_code == 200:
                        data = response.json()
                        usdt_cny = data.get("tether", {}).get("cny", 0)
                        result["usdt_cny_price"] = float(usdt_cny)
                except Exception as e:
                    logger.warning(f"获取USDT/CNY价格失败: {e}")
            
            logger.info(f"成功获取HTX市场数据: {len(result['market_prices'])}个币种")
            return result
            
        except Exception as e:
            logger.error(f"获取HTX数据异常: {e}")
            return None
                    
        except Exception as e:
            logger.error(f"获取火币C2C商家报价失败: {e}")
            return None

    @staticmethod
    async def get_binance_c2c_top10() -> Optional[list]:
        """
        获取币安(Binance)C2C商家Top10报价（使用真实API）
        """
        import logging
        logger = logging.getLogger(__name__)
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search",
                    json={
                        "fiat": "CNY",
                        "page": 1,
                        "rows": 10,
                        "tradeType": "SELL",
                        "asset": "USDT",
                        "countries": [],
                        "provinces": [],
                        "cities": [],
                        "paymentMethods": [],
                        "userType": "",
                        "buyerKycLimit": "",
                        "buyerRegDaysLimit": "",
                        "filterType": "all",
                        "class": "mass",
                        "isOnShelf": True
                    },
                    headers={
                        "Content-Type": "application/json",
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                    },
                    timeout=10.0
                )
                
                if response.status_code == 200:
                    data = response.json()
                    logger.info(f"币安C2C API响应: {data}")
                    
                    # 解析返回数据
                    if data.get("code") == "000000" and data.get("data"):
                        merchants = []
                        for i, item in enumerate(data["data"][:10], 1):
                            adv = item.get("adv", {})
                            advertiser = adv.get("advertiser", {})
                            
                            merchants.append({
                                "rank": i,
                                "price": float(adv.get("price", 0)),
                                "name": advertiser.get("nickName", "未知商家"),
                                "tradeCount": advertiser.get("tradeCount", 0)
                            })
                        
                        logger.info(f"成功获取币安C2C Top10商家报价")
                        return merchants
                    else:
                        logger.error(f"币安C2C API返回错误: {data}")
                        return None
                else:
                    logger.error(f"币安C2C API请求失败，状态码: {response.status_code}")
                    return None
                    
        except Exception as e:
            logger.error(f"获取币安C2C商家报价失败: {e}")
            return None

    @staticmethod
    async def get_tron_address_info(address: str) -> Optional[Dict]:
        """
        查询TRC20地址信息（使用TronScan公共API，无需API Key）
        """
        try:
            async with httpx.AsyncClient() as client:
                # 使用TronScan公共API（无需API Key）
                response = await client.get(
                    f"https://apilist.tronscanapi.com/api/account",
                    params={
                        "address": address
                    },
                    timeout=10.0
                )
                
                if response.status_code == 200:
                    data = response.json()
                    
                    return data
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                return None  # 静默处理
            logger.error(f"TronScan API error: {e.response.status_code}")
            return None
        except Exception as e:
            logger.error(f"Error fetching TRON address info: {e}")
        return None

    @staticmethod
    async def get_tron_transactions(address: str, limit: int = 20) -> Optional[list]:
        """
        查询TRC20地址交易记录（使用TronScan公共API，无需API Key）
        """
        try:
            async with httpx.AsyncClient() as client:
                # 使用TronScan公共API（无需API Key）
                response = await client.get(
                    f"https://apilist.tronscanapi.com/api/token_trc20/transfers",
                    params={
                        "relatedAddress": address,
                        "limit": limit,
                        "start": 0,
                        "sort": "-timestamp",
                        "count": "true"
                    },
                    timeout=10.0
                )
                
                if response.status_code == 200:
                    data = response.json()
                    # 注意：API返回的字段是 token_transfers，不是 data
                    transfers = data.get("token_transfers", [])
                    
                    return transfers
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                return None  # 静默处理
            logger.error(f"TronScan API error: {e.response.status_code}")
            return None
        except Exception as e:
            logger.error(f"Error fetching TRON transactions: {e}")
        return None

    @staticmethod
    async def format_tron_address_info(address_info: Dict) -> str:
        """
        格式化TRC20地址信息（防篡改验证核对样式）
        """
        if not address_info:
            return "❌ 无法获取地址信息"

        from datetime import datetime
        
        # 获取基本信息
        address = address_info.get('address', 'N/A')
        balance_trx = address_info.get('balance', 0) / 1_000_000
        
        # 获取USDT余额
        usdt_balance = 0
        tokens = address_info.get("trc20token_balances", [])
        for token in tokens:
            if token.get('tokenName') == 'Tether USD' or token.get('tokenAbbr') == 'USDT':
                token_balance = token.get("balance", "0")
                token_decimals = int(token.get("tokenDecimal", 6))
                usdt_balance = float(token_balance) / (10 ** token_decimals)
                break
        
        # 获取交易统计
        total_transactions = address_info.get('totalTransactionCount', 0)
        
        # 获取时间信息
        create_time = address_info.get('createTime', 0)
        latest_operation_time = address_info.get('latestOperationTime', 0)
        
        first_tx_time = "N/A"
        latest_active_time = "N/A"
        
        if create_time:
            first_tx_time = datetime.fromtimestamp(create_time / 1000).strftime("%Y-%m-%d %H:%M:%S")
        if latest_operation_time:
            latest_active_time = datetime.fromtimestamp(latest_operation_time / 1000).strftime("%Y-%m-%d %H:%M:%S")
        
        # 获取签名状态
        owner_address = address_info.get('ownerAddress', '')
        signature_status = "单签地址" if not address_info.get('ownerAddress') or owner_address == address else "多签地址"
        
        # 获取能量和带宽
        energy = address_info.get('energy', 0)
        energy_limit = address_info.get('energyLimit', 0)
        bandwidth = address_info.get('freeNetRemaining', 0) + address_info.get('netRemaining', 0)
        bandwidth_limit = address_info.get('freeNetLimit', 0) + address_info.get('netLimit', 0)
        
        # 当前时间
        now_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # 构建消息（仿照图一样式）
        message = (
            f" <b>USDT防篡改验证核对</b>\n"
            f"<i>《请双方谨慎核对地址是否与图中一致,如有误停止付款》</i>\n\n"
            f"<b>{address}</b>\n\n"
            f"Now: {now_time}\n\n"
            f"🔍 查询地址: {address}\n\n"
            f"💡 交易次数: {total_transactions}\n"
            f"⏰ 首次交易: {first_tx_time}\n"
            f"🔔 最近活跃: {latest_active_time}\n"
            f"️ 签名状态: {signature_status}\n\n"
            f"⚡ 能量: 剩余: {energy} / {energy_limit}\n"
            f"🌈 带宽: 剩余: {bandwidth} / {bandwidth_limit}\n\n"
            f"💵 USDT余额: {usdt_balance:.4f} USDT\n"
            f"🪙 TRX余额: {balance_trx:.4f} TRX"
        )
        
        return message

    @staticmethod
    async def format_tron_transactions(transactions: list) -> str:
        """
        格式化TRC20交易记录
        """
        if not transactions:
            return "❌ 暂无交易记录"

        lines = [
            "📝 交易记录",
            "=" * 30,
        ]

        for i, tx in enumerate(transactions[:10], 1):  # 只显示前10条
            tx_hash = tx.get("hash", "N/A")[:16] + "..."
            tx_type = tx.get("contractType", "Unknown")
            timestamp = tx.get("timestamp", 0)

            from datetime import datetime
            date_str = datetime.fromtimestamp(timestamp / 1000).strftime("%Y-%m-%d %H:%M")

            lines.append(f"\n[{i}] {tx_type}")
            lines.append(f"  时间: {date_str}")
            lines.append(f"  哈希: {tx_hash}")

        return "\n".join(lines)
