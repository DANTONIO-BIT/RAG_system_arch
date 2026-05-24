#!/usr/bin/env python3
"""
Router: keyword matching → colección(es) ChromaDB a consultar.
Sin LLM — decisión por score de keywords contra query_keywords del YAML.
"""
import re
import logging
from typing import List

logger = logging.getLogger(__name__)

DEFAULT_COLLECTION = "digital_lab_knowledge"


def _load_config():
    from processor import TOPIC_MAP, QUERY_KEYWORDS
    return TOPIC_MAP, QUERY_KEYWORDS


def get_collection_for_topic(topic: str) -> str:
    """Devuelve el nombre de colección ChromaDB para un topic dado."""
    TOPIC_MAP, _ = _load_config()
    if topic in TOPIC_MAP:
        return TOPIC_MAP[topic].get('collection', DEFAULT_COLLECTION)
    return DEFAULT_COLLECTION


def all_collections() -> List[str]:
    """Devuelve la lista de todas las colecciones configuradas (sin duplicados)."""
    TOPIC_MAP, _ = _load_config()
    seen = []
    for cfg in TOPIC_MAP.values():
        coll = cfg.get('collection', DEFAULT_COLLECTION)
        if coll not in seen:
            seen.append(coll)
    return seen


def _kw_match(kw: str, text: str) -> bool:
    """
    Prefix match con lookbehind: 'inversión' coincide con 'inversiones', 'inmobiliario'
    con 'inmobiliarios'. El lookbehind evita falsos positivos como 'ia' dentro de 'inmobiliarios'
    porque la 'i' de 'ia' estaría precedida por una letra.
    """
    pattern = r'(?<![a-záéíóúüñ])' + re.escape(kw.lower())
    return bool(re.search(pattern, text))


def route_query(query: str) -> List[str]:
    """
    Analiza la query por keywords y devuelve colecciones ordenadas por relevancia.
    Si la query es ambigua (score 0 en todas), devuelve todas las colecciones.
    """
    TOPIC_MAP, QUERY_KEYWORDS = _load_config()
    query_lower = query.lower()

    scores = {}
    for category, keywords in QUERY_KEYWORDS.items():
        score = sum(1 for kw in keywords if _kw_match(kw, query_lower))
        if score > 0:
            scores[category] = score

    if not scores:
        logger.info("Query ambigua — buscando en todas las colecciones")
        return all_collections()

    # Mapear categorías con score → colecciones, orden por score descendente
    ordered_collections = []
    for category in sorted(scores, key=scores.get, reverse=True):
        for cfg in TOPIC_MAP.values():
            if cfg.get('category') == category:
                coll = cfg.get('collection', DEFAULT_COLLECTION)
                if coll not in ordered_collections:
                    ordered_collections.append(coll)

    logger.info(f"Colecciones seleccionadas: {ordered_collections} (scores: {scores})")
    return ordered_collections
