#!/usr/bin/env python3
"""
Engram Client: Integración con Engram para memoria persistente
Guarda metadata y resumen de cada documento indexado
Busca contexto de conversación para detección de temas
"""
import logging
import subprocess
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

PROJECT_NAME = "digital-lab"


def engram_available() -> bool:
    """Verifica si Engram CLI está disponible"""
    try:
        result = subprocess.run(
            ["which", "engram"],
            capture_output=True,
            text=True,
            timeout=5
        )
        return result.returncode == 0
    except Exception:
        return False


def save_to_engram(metadata: Dict, summary: str) -> bool:
    """Guarda metadata y resumen en Engram"""
    if not engram_available():
        logger.warning("Engram CLI no disponible")
        return False
    
    topic = metadata.get('topic', 'unknown')
    category = metadata.get('category', 'unknown')
    
    # Crear título con topic
    title = f"[{topic}] {metadata.get('filename', 'desconocido')}"
    
    # Contenido estructurado
    content = f"""**Documento**: {metadata.get('filename', 'desconocido')}
**Topic**: {topic}
**Categoría**: {category}
**Tipo**: {metadata.get('file_type', 'unknown')}
**Tamaño**: {metadata.get('size', 0) / 1024 / 1024:.1f} MB
**Hash**: {metadata.get('hash', '')[:16]}...
**Chunks**: {metadata.get('chunk_count', 0)}
**Caracteres**: {metadata.get('char_count', 0)}

**Resumen**:
{summary}

**Path**: {metadata.get('filepath', '')}
"""
    
    try:
        # Usar engram CLI (ajustar según API real)
        result = subprocess.run(
            ["engram", "save", "-t", title, "-p", PROJECT_NAME, content],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode == 0:
            logger.info(f"Guardado en Engram: {title}")
            return True
        else:
            logger.error(f"Error Engram: {result.stderr}")
            return True
            
    except Exception as e:
        logger.error(f"Error guardando en Engram: {e}")
        return False


def save_to_engram(metadata: Dict, summary: str) -> bool:
    """Guarda metadata y resumen en Engram"""
    if not engram_available():
        logger.warning("Engram CLI no disponible")
        return False
    
    # Crear título
    title = f"PDF indexado: {metadata.get('filename', 'desconocido')}"
    
    # Contenido estructurado
    content = f"""**Documento**: {metadata.get('filename')}
**Tamaño**: {metadata.get('size', 0) / 1024 / 1024:.1f} MB
**Hash**: {metadata.get('hash', '')[:16]}...
**Chunks**: {metadata.get('chunk_count', 0)}
**Caracteres**: {metadata.get('char_count', 0)}

**Resumen**:
{summary}

**Path**: {metadata.get('filepath', '')}
"""
    
    try:
        # Usar engram CLI (ajustar según API real)
        result = subprocess.run(
            ["engram", "save", "-t", title, "-p", PROJECT_NAME, content],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode == 0:
            logger.info(f"Guardado en Engram: {title}")
            return True
        else:
            logger.error(f"Error Engram: {result.stderr}")
            return False
            
    except Exception as e:
        logger.error(f"Error guardando en Engram: {e}")
        return False


def search_engram(query: str) -> List[Dict]:
    """Busca en Engram"""
    if not engram_available():
        return []
    
    try:
        result = subprocess.run(
            ["engram", "search", "-p", PROJECT_NAME, query],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode == 0:
            # Parsear resultados
            lines = result.stdout.strip().split('\n')
            return [{"text": line} for line in lines if line]
        
    except Exception as e:
        logger.error(f"Error buscando Engram: {e}")
    
    return []


def generate_summary(text: str, max_length: int = 500) -> str:
    """Genera un resumen simple del texto"""
    # Tomar primeros y últimos fragmentos
    text = text.strip()
    
    if len(text) <= max_length:
        return text
    
    # Extraer primeras oraciones significativas
    sentences = text.split('.')
    summary = ""
    
    for sentence in sentences:
        if len(summary) + len(sentence) > max_length:
            break
        summary += sentence + "."
    
    return summary.strip() if summary else text[:max_length] + "..."


def index_document_in_engram(doc_result: Dict) -> bool:
    """Indexa un documento completo en Engram"""
    metadata = doc_result['metadata']
    text = doc_result.get('text', '')
    
    # Generar resumen
    summary = generate_summary(text[:10000])  # Primeros 10k chars
    
    # Guardar en Engram
    return save_to_engram(metadata, summary)


def bulk_index_to_engram(documents: List[Dict]) -> int:
    """Indexa múltiples documentos en Engram"""
    count = 0
    
    for doc in documents:
        if index_document_in_engram(doc):
            count += 1
    
    logger.info(f"Indexados {count}/{len(documents)} documentos en Engram")
    return count


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    # Test
    test_meta = {
        "filename": "test.pdf",
        "size": 1024000,
        "hash": "abc123",
        "chunk_count": 10,
        "char_count": 5000,
        "filepath": "/tmp/test.pdf"
    }
    test_text = "Este es un documento de prueba para Digital Lab. " * 50
    
    summary = generate_summary(test_text)
    print(f"Resumen: {summary[:200]}...")
    print(f"Engram disponible: {engram_available()}")
