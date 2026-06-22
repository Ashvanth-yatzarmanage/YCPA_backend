# # Test  DB is local or remote
# python3 -c "
# import asyncio, time, asyncpg, os
# from dotenv import load_dotenv
# load_dotenv()
#
# async def test():
#     url = os.getenv('DATABASE_URL').replace('postgresql+asyncpg', 'postgresql')
#     start = time.time()
#     conn = await asyncpg.connect(url)
#     await conn.fetchval('SELECT 1')
#     print(f'Query time: {(time.time()-start)*1000:.0f}ms')
#     await conn.close()
#
# asyncio.run(test())
# "
