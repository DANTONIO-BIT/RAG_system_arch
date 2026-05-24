#!/usr/bin/env python3
"""
Processor: Archivo → texto → chunks
Optimizado para PDFs pesados (30-70MB)
Soporta: PDF, MD, JSON, DOCX, XLSX, CSV
"""
import os
import sys
import hashlib
import json
import logging
import time
from pathlib import Path
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

CHUNK_SIZE = 1500
CHUNK_OVERLAP = 200
CHECKPOINT_INTERVAL = 10  # Guardar checkpoint cada 10 archivos

BASE_DIR = Path(__file__).parent.parent
CONFIG_DIR = BASE_DIR / "config"
DATA_DIR = BASE_DIR / "data"
CHECKPOINT_FILE = DATA_DIR / "index_checkpoint.json"
TOPICS_CONFIG = CONFIG_DIR / "topics.yaml"

TOPIC_MAP = {}
QUERY_KEYWORDS = {}


def _load_checkpoint() -> Dict:
    """Carga el checkpoint de indexación"""
    if CHECKPOINT_FILE.exists():
        try:
            with open(CHECKPOINT_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Error cargando checkpoint: {e}")
    return {"indexed_files": [], "last_updated": None}


def _save_checkpoint(checkpoint: Dict):
    """Guarda el checkpoint de indexación"""
    checkpoint["last_updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    try:
        with open(CHECKPOINT_FILE, 'w') as f:
            json.dump(checkpoint, f, indent=2)
    except Exception as e:
        logger.error(f"Error guardando checkpoint: {e}")

def load_topics_config():
    """Carga configuración de topics desde YAML"""
    global TOPIC_MAP, QUERY_KEYWORDS
    
    if not TOPICS_CONFIG.exists():
        logger.warning(f"Config no encontrada: {TOPICS_CONFIG}")
        return
    
    try:
        import yaml
        with open(TOPICS_CONFIG, 'r') as f:
            config = yaml.safe_load(f)
        
        TOPIC_MAP = config.get('topics', {})
        QUERY_KEYWORDS = config.get('query_keywords', {})
        logger.info(f"Cargados {len(TOPIC_MAP)} topics configurados")
    except Exception as e:
        logger.error(f"Error cargando topics.yaml: {e}")

load_topics_config()


def extract_topic_from_path(filepath: str) -> str:
    """Extrae el topic (nombre de carpeta) desde la ruta del archivo"""
    path = Path(filepath)
    input_dir = BASE_DIR / "input"
    
    try:
        relative = path.relative_to(input_dir)
        parts = relative.parts
        if len(parts) > 0:
            return parts[0]
    except ValueError:
        pass
    
    for topic_name in TOPIC_MAP.keys():
        if topic_name in str(filepath):
            return topic_name
    
    return "general"


def map_category(topic: str) -> str:
    if topic in TOPIC_MAP:
        return TOPIC_MAP[topic].get('category', 'general')
    return 'general'


def map_collection(topic: str) -> str:
    if topic in TOPIC_MAP:
        return TOPIC_MAP[topic].get('collection', 'digital_lab_knowledge')
    return 'digital_lab_knowledge'


def detect_file_type(filepath: str) -> str:
    """Detecta el tipo de archivo por extensión"""
    ext = Path(filepath).suffix.lower()
    type_map = {
        '.pdf': 'pdf',
        '.md': 'markdown',
        '.json': 'json',
        '.docx': 'docx',
        '.xlsx': 'xlsx',
        '.csv': 'csv',
        '.txt': 'text',
    }
    return type_map.get(ext, 'unknown')


def extract_text_from_docx(docx_path: str) -> str:
    """Extrae texto de archivos .docx"""
    if not DOCX_AVAILABLE:
        raise ImportError("python-docx requerido: pip install python-docx")
    
    doc = docx.Document(docx_path)
    text_parts = []
    
    for para in doc.paragraphs:
        if para.text.strip():
            text_parts.append(para.text)
    
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                if cell.text.strip():
                    text_parts.append(cell.text)
    
    return "\n\n".join(text_parts)


def extract_text_from_xlsx(xlsx_path: str) -> str:
    """Extrae texto de archivos .xlsx"""
    if not XLSX_AVAILABLE:
        raise ImportError("openpyxl requerido: pip install openpyxl")
    
    wb = openpyxl.load_workbook(xlsx_path, data_only=True)
    text_parts = []
    
    for sheet in wb.sheetnames:
        ws = wb[sheet]
        text_parts.append(f"=== Hoja: {sheet} ===")
        
        for row in ws.iter_rows():
            row_values = []
            for cell in row:
                if cell.value is not None:
                    row_values.append(str(cell.value))
            if row_values:
                text_parts.append(" | ".join(row_values))
    
    return "\n".join(text_parts)


def extract_text_from_csv(csv_path: str) -> str:
    """Extrae texto de archivos .csv"""
    text_parts = []
    
    with open(csv_path, 'r', encoding='utf-8', errors='ignore') as f:
        import csv
        reader = csv.reader(f)
        for row in reader:
            text_parts.append(" | ".join(row))
    
    return "\n".join(text_parts)


def extract_text_from_json(json_path: str) -> str:
    """Extrae texto de archivos .json"""
    with open(json_path, 'r', encoding='utf-8', errors='ignore') as f:
        data = json.load(f)
    
    def flatten(obj, prefix=""):
        parts = []
        if isinstance(obj, dict):
            for k, v in obj.items():
                parts.extend(flatten(v, f"{prefix}.{k}" if prefix else k))
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                parts.extend(flatten(v, f"{prefix}[{i}]" if prefix else str(i)))
        else:
            parts.append(f"{prefix}: {obj}")
        return parts
    
    return "\n".join(flatten(data))


def extract_text_from_file(filepath: str) -> str:
    """Extrae texto según el tipo de archivo"""
    file_type = detect_file_type(filepath)
    
    if file_type == 'pdf':
        return extract_text_from_pdf(filepath)
    elif file_type == 'docx':
        return extract_text_from_docx(filepath)
    elif file_type == 'xlsx':
        return extract_text_from_xlsx(filepath)
    elif file_type == 'csv':
        return extract_text_from_csv(filepath)
    elif file_type == 'json':
        return extract_text_from_json(filepath)
    elif file_type in ('markdown', 'text'):
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            return f.read()
    else:
        raise ValueError(f"Tipo de archivo no soportado: {file_type}")


try:
    import pymupdf
    PDF_AVAILABLE = True
except ImportError:
    try:
        import fitz
        pymupdf = fitz
        PDF_AVAILABLE = True
    except ImportError:
        PDF_AVAILABLE = False
        logger.warning("pymupdf/fitz no disponible")

DOCX_AVAILABLE = False
try:
    import docx
    DOCX_AVAILABLE = True
except ImportError:
    logger.warning("python-docx no disponible")

XLSX_AVAILABLE = False
try:
    import openpyxl
    XLSX_AVAILABLE = True
except ImportError:
    logger.warning("openpyxl no disponible")


def get_file_hash(filepath: str) -> str:
    """Genera hash SHA256 del archivo"""
    sha256 = hashlib.sha256()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            sha256.update(chunk)
    return sha256.hexdigest()


def extract_text_from_pdf(pdf_path: str) -> str:
    """Extrae texto de PDF usando pymupdf/fitz"""
    if not PDF_AVAILABLE:
        raise ImportError("pymupdf o fitz requerido: pip install pymupdf")
    
    text_parts = []
    doc = pymupdf.open(pdf_path)
    
    logger.info(f"Procesando PDF: {pdf_path} ({len(doc)} páginas)")
    
    for page_num, page in enumerate(doc):
        text = page.get_text()
        if text.strip():
            text_parts.append(text)
    
    doc.close()
    return "\n\n".join(text_parts)


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> List[str]:
    """Divide texto en chunks con overlap"""
    chunks = []
    start = 0
    text_len = len(text)
    
    while start < text_len:
        end = start + chunk_size
        chunk = text[start:end]
        chunks.append(chunk)
        start = end - overlap
    
    logger.info(f"Texto dividido en {len(chunks)} chunks")
    return chunks


def process_file(file_path: str) -> Dict:
    """Procesa cualquier archivo soportado y retorna metadata + chunks"""
    filepath = Path(file_path)
    
    if not filepath.exists():
        raise FileNotFoundError(f"Archivo no encontrado: {file_path}")
    
    file_type = detect_file_type(file_path)
    if file_type == 'unknown':
        logger.warning(f"Tipo no soportado: {file_path}")
        return None
    
    topic = extract_topic_from_path(file_path)
    category = map_category(topic)
    
    # Metadata con topic y category
    metadata = {
        "filename": filepath.name,
        "filepath": str(filepath.absolute()),
        "hash": get_file_hash(str(filepath)),
        "size": filepath.stat().st_size,
        "file_type": file_type,
        "topic": topic,
        "category": category,
    }
    
    # Extraer texto según tipo
    try:
        text = extract_text_from_file(str(filepath))
    except Exception as e:
        logger.error(f"Error extrayendo texto de {filepath}: {e}")
        return None
    
    metadata["char_count"] = len(text)
    
    # Chunks
    chunks = chunk_text(text)
    metadata["chunk_count"] = len(chunks)
    
    logger.info(f"Procesado: {metadata['filename']} [{metadata['topic']}] - {metadata['chunk_count']} chunks")
    
    return {
        "metadata": metadata,
        "text": text,
        "chunks": chunks
    }


def process_pdf(pdf_path: str) -> Dict:
    """Legacy: Procesa un PDF y retorna metadata + chunks (Backward compatibility)"""
    return process_file(pdf_path)


def process_directory(input_dir: str, recursive: bool = True) -> List[Dict]:
    """Procesa todos los archivos soportados en un directorio"""
    input_path = Path(input_dir)
    
    extensions = ['*.pdf', '*.md', '*.json', '*.docx', '*.xlsx', '*.csv', '*.txt']
    files = []
    for ext in extensions:
        if recursive:
            files.extend(input_path.rglob(ext))
        else:
            files.extend(input_path.glob(ext))
    
    checkpoint = _load_checkpoint()
    indexed_hashes = set(checkpoint.get('indexed_files', []))
    
    results = []
    processed_count = 0
    skipped_count = 0
    
    for file_path in files:
        try:
            file_str = str(file_path)
            result = process_file(file_str)
            
            if result:
                doc_hash = result.get('metadata', {}).get('hash', '')
                
                if doc_hash in indexed_hashes:
                    skipped_count += 1
                    logger.info(f"⏭️ Skip (ya indexado): {file_path.name}")
                    continue
                
                results.append(result)
                indexed_hashes.add(doc_hash)
                processed_count += 1
                
                if processed_count % CHECKPOINT_INTERVAL == 0:
                    _save_checkpoint({"indexed_files": list(indexed_hashes)})
                    logger.info(f"💾 Checkpoint guardado ({processed_count} nuevos)")
                    
        except Exception as e:
            logger.error(f"Error procesando {file_path}: {e}")
    
    if indexed_hashes:
        _save_checkpoint({"indexed_files": list(indexed_hashes)})
        logger.info(f"💾 Checkpoint final: {len(indexed_hashes)} archivos indexados")
    
    logger.info(f"Total: {processed_count} nuevos, {skipped_count} skippeados")
    return results


def get_supported_files(input_dir: str) -> List[str]:
    """Lista todos los archivos soportados en un directorio"""
    input_path = Path(input_dir)
    extensions = ['*.pdf', '*.md', '*.json', '*.docx', '*.xlsx', '*.csv', '*.txt']
    files = []
    for ext in extensions:
        files.extend(input_path.rglob(ext))
    return [str(f) for f in files]


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    
    if len(sys.argv) > 1:
        result = process_pdf(sys.argv[1])
        print(f"Chunks: {result['metadata']['chunk_count']}")
        print(f"Caracteres: {result['metadata']['char_count']}")
    else:
        print("Usage: python3 processor.py <pdf_path>")
