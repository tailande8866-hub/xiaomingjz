#!/bin/bash
cd /opt/saas-bot
sudo docker exec -i saas-bot python3 -c "
import asyncio
import os
from sqlalchemy import select
from src.core.database import async_session
from src.models.bot_instance import BotInstance
async def init():
    bot_token = os.getenv('BOT_TOKEN')
    if not bot_token:
        raise RuntimeError('BOT_TOKEN must be set in the container environment')
    async with async_session() as session:
        r = await session.execute(select(BotInstance).where(BotInstance.bot_id == 'main_bot'))
        b = r.scalar_one_or_none()
        if not b:
            b = BotInstance(bot_id='main_bot', bot_token=bot_token, is_active=True)
            session.add(b)
            await session.commit()
            print('Created main_bot')
        else:
            print('main_bot exists')
asyncio.run(init())
"
sudo docker-compose restart
sudo docker-compose logs --tail=30 bot
