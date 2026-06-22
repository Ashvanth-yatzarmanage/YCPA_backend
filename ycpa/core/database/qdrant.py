# """
#
# Collection: "ifc_elements"
#   - One vector per IFC element
#   - Payload: global_id, ifc_type, name, storey, file_id, pset summary
#   - Used for semantic search ("find elements similar to...")
# """
# from __future__ import annotations
#
# import logging
# from typing import Optional
#
# from qdrant_client import AsyncQdrantClient
# from qdrant_client.models import Distance, VectorParams, OptimizersConfigDiff
#
# logger = logging.getLogger(__name__)
#
# _client: Optional[AsyncQdrantClient] = None
#
# # ── Constants ──────────────────────────────────────────────────────────────────
# ELEMENTS_COLLECTION = "ifc_elements"
# VECTOR_DIM = 768          # Gemini text-embedding-004 output dimension
#
#
# def get_qdrant_client() -> AsyncQdrantClient:
#     global _client
#     if _client is None:
#         raise RuntimeError("Qdrant not initialized. Call init_qdrant() in lifespan startup.")
#     return _client
#
#
# async def init_qdrant(url: str, api_key: Optional[str] = None) -> None:
#     """
#     Initialize Qdrant client and ensure the ifc_elements collection exists.
#
#     Args:
#         url:     ":memory:" for dev | "http://localhost:6333" for Docker | Qdrant Cloud URL
#         api_key: Required for Qdrant Cloud, None for local
#     """
#     global _client
#
#     if url == ":memory:":
#         logger.warning("[Qdrant] Running IN-MEMORY — data is lost on restart. Set QDRANT_URL.")
#         _client = AsyncQdrantClient(location=":memory:")
#     elif api_key:
#         _client = AsyncQdrantClient(url=url, api_key=api_key)
#     else:
#         _client = AsyncQdrantClient(url=url)
#
#     await _ensure_collection()
#     logger.info(f"[Qdrant] Initialized: {url}")
#
#
# async def close_qdrant() -> None:
#     global _client
#     if _client:
#         await _client.close()
#         _client = None
#         logger.info("[Qdrant] Client closed")
#
#
# async def check_qdrant_health() -> bool:
#     try:
#         client = get_qdrant_client()
#         await client.get_collections()
#         return True
#     except Exception as exc:
#         logger.error(f"[Qdrant] Health check failed: {exc}")
#         return False
#
#
# async def _ensure_collection() -> None:
#     """Create the ifc_elements collection if it doesn't exist."""
#     client = get_qdrant_client()
#     existing = {c.name for c in (await client.get_collections()).collections}
#
#     if ELEMENTS_COLLECTION not in existing:
#         await client.create_collection(
#             collection_name=ELEMENTS_COLLECTION,
#             vectors_config=VectorParams(size=VECTOR_DIM, distance=Distance.COSINE),
#             optimizers_config=OptimizersConfigDiff(
#                 indexing_threshold=5_000,   # build HNSW after 5k vectors
#             ),
#         )
#         logger.info(f"[Qdrant] Collection created: {ELEMENTS_COLLECTION}")
#     else:
#         logger.info(f"[Qdrant] Collection ready: {ELEMENTS_COLLECTION}")