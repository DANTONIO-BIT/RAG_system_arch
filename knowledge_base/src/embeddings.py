#!/usr/bin/env python3
"""
Embeddings: Genera vectores usando bge-m3 via Ollama
"""
import logging
import time
from typing import List, Dict, Optional
from functools import wraps

logger = logging.getLogger(__name__)

# === CONFIG: Timeouts y retries ===
EMBED_TIMEOUT = 60  # segundos
MAX_RETRIES = 3
RETRY_DELAY = 2  # segundos entre retries

try:
    import ollama
    OLLAMA_AVAILABLE = True
except ImportError:
    OLLAMA_AVAILABLE = False
    logger.warning("ollama no disponible: pip install ollama")

DEFAULT_MODEL = "bge-m3:latest"
EMBEDDING_DIM = 1024


def check_ollama():
    """Verifica que Ollama esté corriendo"""
    if not OLLAMA_AVAILABLE:
        return False
    try:
        ollama.list()
        return True
    except Exception:
        return False


def get_embedding_model():
    """Verifica y retorna el modelo de embeddings"""
    if not check_ollama():
        raise RuntimeError("Ollama no disponible. Asegúrate que esté corriendo.")
    
    models = ollama.list()
    model_names = [m.get('name', '') for m in models.get('models', [])]
    
    # Buscar bge-m3
    for name in model_names:
        if 'bge-m3' in name.lower():
            logger.info(f"Modelo encontrado: {name}")
            return name
    
    # Si no está, intentar pull
    logger.info(f"Descargando {DEFAULT_MODEL}...")
    ollama.pull(DEFAULT_MODEL)
    return DEFAULT_MODEL


def _generate_embedding_with_timeout(texts: List[str], model: str) -> List[List[float]]:
    """Genera embeddings con timeout configurado"""
    import httpx
    
    client = httpx.Client(timeout=EMBED_TIMEOUT)
    try:
        response = client.post(
            "http://localhost:11434/api/embed",
            json={"model": model, "input": texts}
        )
        response.raise_for_status()
        data = response.json()
        
        if isinstance(data, list):
            return data
        elif isinstance(data, dict):
            return data.get('embeddings', [])
        else:
            return []
    except Exception as e:
        logger.error(f"Error en embedding API: {e}")
        raise
    finally:
        client.close()


def generate_embeddings(texts: List[str], model: str = None) -> List[List[float]]:
    """Genera embeddings para una lista de textos con timeout y retry"""
    if not model:
        model = get_embedding_model()
    
    embeddings = []
    batch_size = 32
    
    logger.info(f"Generando embeddings para {len(texts)} textos...")
    
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i+batch_size]
        batch_success = False
        
        for attempt in range(MAX_RETRIES):
            try:
                response = _generate_embedding_with_timeout(batch, model)
                
                if isinstance(response, list):
                    batch_embeddings = response
                elif isinstance(response, dict):
                    batch_embeddings = response.get('embeddings', [])
                else:
                    batch_embeddings = []
                
                if batch_embeddings:
                    embeddings.extend(batch_embeddings)
                    logger.info(f"Procesados {min(i+batch_size, len(texts))}/{len(texts)}")
                    batch_success = True
                    break
            except Exception as e:
                logger.warning(f"Intento {attempt + 1}/{MAX_RETRIES} falló: {e}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_DELAY * (attempt + 1))
        
        if not batch_success:
            logger.error(f"Todos los intentos fallaron para batch {i}, usando ceros")
            for _ in batch:
                embeddings.append([0.0] * EMBEDDING_DIM)
    
    return embeddings


def generate_embedding(text: str, model: str = None) -> List[float]:
    """Genera embedding para un solo texto"""
    embeddings = generate_embeddings([text], model)
    return embeddings[0]


def test_embeddings():
    """Test básico del sistema de embeddings"""
    test_texts = [
        "La transformación digital es fundamental para las PYMEs",
        "Business Intelligence permite analizar grandes cantidades de datos",
        "Las herramientas digitales mejoran la colaboración empresarial"
    ]
    
    embeddings = generate_embeddings(test_texts)
    
    assert len(embeddings) == len(test_texts)
    assert len(embeddings[0]) == EMBEDDING_DIM
    
    logger.info("✅ Test de embeddings exitoso")
    logger.info(f"   Dimensiones: {len(embeddings[0])}")
    logger.info(f"   Embeddings generados: {len(embeddings)}")
    
    return embeddings


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    
    if len(sys.argv) > 1:
        text = " ".join(sys.argv[1:])
        embedding = generate_embedding(text)
        print(f"Embedding dimensions: {len(embedding)}")
    else:
        test_embeddings()
