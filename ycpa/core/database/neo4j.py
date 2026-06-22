# from __future__ import annotations
#
# import logging
# from typing import Optional
#
# from neo4j import AsyncDriver, AsyncGraphDatabase
#
# logger = logging.getLogger(__name__)
#
# _driver: Optional[AsyncDriver] = None
#
#
# def get_neo4j_driver() -> AsyncDriver:
#     global _driver
#     if _driver is None:
#         raise RuntimeError("Neo4j not initialized. Call init_neo4j() in lifespan startup.")
#     return _driver
#
#
# async def init_neo4j(uri: str, user: str, password: str) -> None:
#     """
#     Initialize Neo4j Aura driver and create indexes.
#     Call from FastAPI lifespan.
#
#     Args:
#         uri:      Your Aura URI  e.g. neo4j+s://xxxxxxxx.databases.neo4j.io
#         user:     Usually "neo4j"
#         password: Your Aura password
#     """
#     global _driver
#     _driver = AsyncGraphDatabase.driver(uri, auth=(user, password))
#     await _driver.verify_connectivity()
#     logger.info(f"[Neo4j] Connected: {uri}")
#     await _ensure_indexes()
#
#
# async def close_neo4j() -> None:
#     global _driver
#     if _driver:
#         await _driver.close()
#         _driver = None
#         logger.info("[Neo4j] Driver closed")
#
#
# async def check_neo4j_health() -> bool:
#     try:
#         driver = get_neo4j_driver()
#         async with driver.session() as s:
#             r = await s.run("RETURN 1 AS ok")
#             rec = await r.single()
#             return rec["ok"] == 1
#     except Exception as exc:
#         logger.error(f"[Neo4j] Health check failed: {exc}")
#         return False
#
#
# async def _ensure_indexes() -> None:
#     """
#     Idempotent index creation — safe to run every startup.
#     These make the graph queries fast.
#     """
#     queries = [
#         # Lookup by GlobalId — used in almost every query
#         "CREATE INDEX ifc_global_id IF NOT EXISTS FOR (n:IFCElement) ON (n.global_id)",
#         # Filter by IFC type  e.g. WHERE n.ifc_type = 'IfcWall'
#         "CREATE INDEX ifc_type IF NOT EXISTS FOR (n:IFCElement) ON (n.ifc_type)",
#         # Storey name lookups
#         "CREATE INDEX ifc_storey_name IF NOT EXISTS FOR (n:IFCElement) ON (n.name)",
#         # File scoping — every node has file_id so we can wipe/query per-file
#         "CREATE INDEX ifc_file_id IF NOT EXISTS FOR (n:IFCElement) ON (n.file_id)",
#     ]
#     driver = get_neo4j_driver()
#     async with driver.session() as session:
#         for q in queries:
#             try:
#                 await session.run(q)
#             except Exception as exc:
#                 logger.debug(f"[Neo4j] Index note (safe): {exc}")
#     logger.info("[Neo4j] Indexes ensured")