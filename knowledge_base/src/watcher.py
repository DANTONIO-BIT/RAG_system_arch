#!/Library/Developer/CommandLineTools/usr/bin/python3
"""
Watcher: Monitor de cambios en tiempo real (watchdog)
Detecta nuevos PDFs y dispara indexación automática
"""
import logging
import time
import signal
import sys
import threading
import queue
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler, FileCreatedEvent, FileModifiedEvent
    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False
    logger.warning("watchdog no disponible: pip install watchdog")


SUPPORTED_EXTENSIONS = {'.pdf', '.md', '.json', '.docx', '.xlsx', '.csv', '.txt'}

# === COLA ASÍNCRONA PARA PROCESAMIENTO ===
_processing_queue = queue.Queue()
_worker_thread = None
_shutdown_event = threading.Event()


class PDFHandler(FileSystemEventHandler):
    """Manejador de eventos de archivos"""
    
    def __init__(self, callback: Callable[[str], None] = None):
        super().__init__()
        self.callback = callback
        self.processed_hashes = set()
    
    def _is_supported(self, filepath: str) -> bool:
        """Verifica si el archivo es de tipo soportado"""
        ext = Path(filepath).suffix.lower()
        return ext in SUPPORTED_EXTENSIONS
    
    def on_created(self, archivo_creado):
        """Archivo creado"""
        if archivo_creado.is_directory:
            return
        
        if self._is_supported(archivo_creado.src_path):
            logger.info(f"📄 Archivo detectado: {archivo_creado.src_path}")
            self._process_file(archivo_creado.src_path)
    
    def on_modified(self, event):
        """Archivo modificado"""
        if event.is_directory:
            return
        
        if self._is_supported(event.src_path):
            logger.info(f"📝 Archivo modificado: {event.src_path}")
            self._process_file(event.src_path)
    
    def _process_file(self, file_path: str):
        """Encola el archivo para procesamiento asíncrono"""
        time.sleep(1)
        
        if self.callback:
            try:
                _processing_queue.put((file_path, self.callback))
                logger.info(f"📥 Enqueued: {file_path}")
            except Exception as e:
                logger.error(f"Error encolando {file_path}: {e}")


class Watcher:
    """Watchdog para monitorear directorio"""
    
    def __init__(self, watch_dir: str, callback: Callable[[str], None] = None):
        self.watch_dir = Path(watch_dir)
        self.callback = callback
        self.observer = None
        self.handler = PDFHandler(callback=callback)
        
        if not WATCHDOG_AVAILABLE:
            raise ImportError("watchdog requerido: pip install watchdog")
        
        if not self.watch_dir.exists():
            raise FileNotFoundError(f"Directorio no encontrado: {watch_dir}")
    
    def start(self):
        """Inicia el watchdog y worker thread"""
        start_worker_thread(self.callback)
        
        self.observer = Observer()
        self.observer.schedule(self.handler, str(self.watch_dir), recursive=True)
        self.observer.start()
        
        logger.info(f"👀 Watchdog iniciado: {self.watch_dir}")
        logger.info("   Esperando cambios... (Ctrl+C para detener)")
    
    def stop(self):
        """Detiene el watchdog y worker thread"""
        if self.observer:
            self.observer.stop()
            self.observer.join()
        
        stop_worker_thread()
        logger.info("🛑 Watchdog detenido")
    
    def run_forever(self):
        """Ejecuta el watchdog indefinidamente"""
        self.start()
        
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop()


def create_watcher(watch_dir: str, callback: Callable[[str], None] = None) -> Watcher:
    """Factory function para crear Watcher"""
    return Watcher(watch_dir, callback)


def process_new_file(file_path: str):
    """Callback por defecto para procesar nuevos archivos"""
    logger.info(f"🔄 Procesando: {file_path}")
    
    # Importar aquí para evitar circular
    sys.path.insert(0, str(Path(__file__).parent))
    from processor import process_file
    from embeddings import generate_embeddings
    from vector_store import get_vector_store
    
    try:
        # 1. Procesar archivo
        result = process_file(file_path)
        if not result:
            logger.error(f"   ❌ No se pudo procesar: {file_path}")
            return
        
        topic = result['metadata'].get('topic', 'unknown')
        logger.info(f"   [{topic}] Extraídos {result['metadata']['chunk_count']} chunks")
        
        # 2. Generar embeddings
        embeddings = generate_embeddings(result['chunks'])
        result['embeddings'] = embeddings
        
        # 3. Guardar en vector store
        vs = get_vector_store()
        vs.add_documents([result])
        
        logger.info(f"✅ Indexado [{topic}]: {result['metadata']['filename']}")
        
        # 4. Guardar en Engram
        try:
            from engram_client import index_document_in_engram
            index_document_in_engram(result)
        except Exception as e:
            logger.warning(f"   Engram: {e}")
        
    except Exception as e:
        logger.error(f"❌ Error: {e}")


def process_new_pdf(pdf_path: str):
    """Legacy: Callback por defecto para procesar nuevos PDFs (Backward compatibility)"""
    process_new_file(pdf_path)


def _worker_loop(callback: Callable[[str], None]):
    """Worker thread que procesa la cola asíncronamente"""
    logger.info("🧵 Worker thread iniciado")
    
    while not _shutdown_event.is_set():
        try:
            file_path, cb = _processing_queue.get(timeout=1)
            logger.info(f"⚙️ Procesando: {file_path}")
            try:
                cb(file_path)
            except Exception as e:
                logger.error(f"❌ Error procesando {file_path}: {e}")
            finally:
                _processing_queue.task_done()
        except queue.Empty:
            continue
        except Exception as e:
            logger.error(f"❌ Error en worker loop: {e}")
    
    logger.info("🧵 Worker thread detenido")


def start_worker_thread(callback: Callable[[str], None]):
    """Inicia el worker thread para procesamiento asíncrono"""
    global _worker_thread
    
    if _worker_thread and _worker_thread.is_alive():
        logger.warning("Worker thread ya está corriendo")
        return
    
    _shutdown_event.clear()
    _worker_thread = threading.Thread(target=_worker_loop, args=(callback,), daemon=True)
    _worker_thread.start()
    logger.info("✅ Worker thread iniciado")


def stop_worker_thread():
    """Detiene el worker thread"""
    global _worker_thread
    
    _shutdown_event.set()
    if _worker_thread:
        _worker_thread.join(timeout=5)
        _worker_thread = None
    logger.info("🛑 Worker thread detenido")


if __name__ == "__main__":
    import sys
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    if len(sys.argv) > 1:
        watch_dir = sys.argv[1]
    else:
        # Default: input directory
        base_dir = Path(__file__).parent.parent
        watch_dir = base_dir / "input"
    
    print(f"Iniciando watchdog en: {watch_dir}")
    
    watcher = create_watcher(str(watch_dir), callback=process_new_pdf)
    watcher.run_forever()
