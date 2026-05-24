#!/Library/Developer/CommandLineTools/usr/bin/python3
"""
Main CLI: CLI + Daemon para Sistema RAG
Uso: python3 main.py [index|query|watch|status|test]
"""
import os
import sys
import logging
import argparse
import json
from pathlib import Path
import subprocess

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Añadir path base
BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))


def cmd_index(args):
    """Indexa documentos en input/"""
    from processor import process_directory, get_supported_files, map_collection
    from embeddings import generate_embeddings, get_embedding_model
    from vector_store import get_vector_store

    input_dir = BASE_DIR / "input"

    if args.path:
        input_dir = Path(args.path)

    if args.all:
        dirs_to_process = [
            item for item in input_dir.iterdir()
            if item.is_dir() and not item.name.startswith('.')
        ]
        logger.info(f"📂 Modo --all: {len(dirs_to_process)} carpetas")
    else:
        default = input_dir / "TRANSF.DIGITAL"
        dirs_to_process = [default if default.exists() else input_dir]

    try:
        get_embedding_model()
    except Exception as e:
        logger.error(f"Error con Ollama: {e}")
        return 1

    # Cache de VectorStore por colección para no reinicializar en cada doc
    vs_cache = {}
    total_indexed = 0
    total_docs = 0

    for dir_path in dirs_to_process:
        if not dir_path.exists():
            continue

        logger.info(f"\n📂 Procesando: {dir_path.name}")
        results = process_directory(str(dir_path))

        if not results:
            logger.warning(f"   Sin archivos en {dir_path.name}")
            continue

        logger.info(f"   Archivos encontrados: {len(results)}")

        for result in results:
            topic = result['metadata'].get('topic', 'unknown')
            category = result['metadata'].get('category', 'unknown')
            collection = map_collection(topic)

            if collection not in vs_cache:
                vs_cache[collection] = get_vector_store(collection)
            vs = vs_cache[collection]

            doc_hash = result['metadata']['hash']
            if vs.check_document_exists(doc_hash):
                logger.info(f"   ⏭️  Ya indexado: {result['metadata']['filename']}")
                continue

            logger.info(f"   🔄 [{collection}] [{topic}]: {result['metadata']['filename']}")
            try:
                result['embeddings'] = generate_embeddings(result['chunks'])
                chunks_added = vs.add_documents([result])
                total_indexed += chunks_added
                total_docs += 1

                try:
                    from engram_client import index_document_in_engram
                    index_document_in_engram(result)
                except Exception as e:
                    logger.warning(f"   Engram: {e}")

            except Exception as e:
                logger.error(f"   ❌ Error: {e}")

    logger.info(f"\n✅ Indexación: {total_docs} documentos, {total_indexed} chunks")
    return 0


def cmd_query(args):
    """Busca en la base de conocimiento usando el router multi-colección"""
    from vector_store import get_vector_store
    from router import route_query, get_collection_for_topic

    if not args.query:
        logger.error("Consulta requerida: -q 'tu pregunta'")
        return 1

    # Determinar colecciones a consultar
    if args.topic:
        collections = [get_collection_for_topic(args.topic)]
        logger.info(f"🏷️  Topic forzado: {args.topic} → {collections[0]}")
    else:
        collections = route_query(args.query)

    logger.info(f"🔍 Buscando en: {collections}")

    # Recopilar resultados de cada colección
    all_docs = []
    for coll_name in collections:
        vs = get_vector_store(coll_name)
        if vs.collection.count() == 0:
            continue
        try:
            res = vs.query(args.query, n_results=args.n, category=args.category if hasattr(args, 'category') else None)
            if res.get('documents') and res['documents'][0]:
                for i, doc in enumerate(res['documents'][0]):
                    all_docs.append({
                        'text': doc,
                        'distance': res['distances'][0][i] if 'distances' in res else 0,
                        'metadata': res['metadatas'][0][i] if 'metadatas' in res else {},
                        'collection': coll_name,
                    })
        except Exception as e:
            logger.warning(f"   Error en {coll_name}: {e}")

    if not all_docs:
        logger.warning("No se encontraron resultados")
        return 0

    # Ordenar por distancia (más relevante primero) y limitar
    all_docs.sort(key=lambda x: x['distance'])
    all_docs = all_docs[:args.n]

    print("\n" + "="*60)
    print(f"RESULTADOS PARA: {args.query}")
    print("="*60 + "\n")

    for i, item in enumerate(all_docs):
        meta = item['metadata']
        print(f"--- Resultado {i+1} (dist: {item['distance']:.3f}) [{meta.get('topic', '?')}] ---")
        print(f"📄 {meta.get('filename', 'unknown')}  |  colección: {item['collection']}")
        print(f"📝 {item['text'][:300]}...")
        print()

    print(f"Total: {len(all_docs)} resultados")
    return 0


def cmd_watch(args):
    """Inicia el watchdog daemon"""
    from watcher import create_watcher, process_new_pdf
    
    input_dir = BASE_DIR / "input"
    
    if args.path:
        input_dir = Path(args.path)
    
    logger.info("🚀 Iniciando watchdog daemon...")
    logger.info(f"   Directorio: {input_dir}")
    logger.info("   Presiona Ctrl+C para detener")
    
    watcher = create_watcher(str(input_dir), callback=process_new_pdf)
    
    try:
        watcher.run_forever()
    except KeyboardInterrupt:
        watcher.stop()
        logger.info("👋 daemon detenido")
    
    return 0


def cmd_topics(args):
    """Muestra topics disponibles"""
    from vector_store import get_vector_store
    
    print("\n" + "="*60)
    print("TEMAS DISPONIBLES EN LA BASE DE CONOCIMIENTO")
    print("="*60)
    
    try:
        vs = get_vector_store()
        topics = vs.get_available_topics()
        
        if not topics:
            print("\n❌ No hay documentos indexados")
            return 0
        
        print(f"\n📂 Topics ({len(topics)}):\n")
        
        for topic, stats in topics.items():
            category = stats.get('category', 'unknown')
            doc_count = stats.get('document_count', 0)
            chunk_count = stats.get('chunk_count', 0)
            
            print(f"  🏷️  {topic}")
            print(f"      Categoría: {category}")
            print(f"      Documentos: {doc_count}")
            print(f"      Chunks: {chunk_count}")
            print()
        
    except Exception as e:
        print(f"❌ Error: {e}")
    
    print("="*60)
    return 0


def cmd_status(args):
    """Muestra estado del sistema"""
    from vector_store import get_vector_store
    
    print("\n" + "="*60)
    print("ESTADO DEL SISTEMA RAG")
    print("="*60)
    
    # ChromaDB
    try:
        vs = get_vector_store()
        stats = vs.get_stats()
        print(f"\n📦 ChromaDB:")
        print(f"   Colección: {stats['collection_name']}")
        print(f"   Documentos únicos: {stats['unique_documents']}")
        print(f"   Total chunks: {stats['total_chunks']}")
        print(f"   Persistido en: {stats['persist_dir']}")
    except Exception as e:
        print(f"   ❌ Error: {e}")
    
    # Topics detallados si se pide
    if args.detailed:
        try:
            vs = get_vector_store()
            topics = vs.get_available_topics()
            print(f"\n📂 Topics por categoría:")
            for topic, stats in topics.items():
                print(f"   - {topic}: {stats.get('document_count', 0)} docs, {stats.get('chunk_count', 0)} chunks")
        except Exception as e:
            print(f"   ❌ Error: {e}")
    
    # Ollama
    try:
        result = subprocess.run(["ollama", "list"], capture_output=True, text=True)
        print(f"\n🤖 Modelos Ollama disponibles:")
        for line in result.stdout.strip().split('\n')[1:]:
            if line.strip():
                parts = line.split()
                if len(parts) >= 2:
                    print(f"   - {parts[0]} ({parts[1]})")
    except Exception as e:
        print(f"   ❌ Ollama no disponible: {e}")
    
    # PDFs en input
    input_dir = BASE_DIR / "input"
    pdf_count = len(list(input_dir.rglob("*.pdf")))
    file_count = len(list(input_dir.rglob("*.*"))) - len(list(input_dir.rglob(".*")))
    print(f"\n📄 Archivos en input/: {file_count} ({pdf_count} PDFs)")
    
    # Engram
    from engram_client import engram_available
    print(f"\n💾 Engram: {'✅ Disponible' if engram_available() else '❌ No disponible'}")
    
    print("\n" + "="*60)
    return 0


def cmd_test(args):
    """Test del sistema"""
    from embeddings import test_embeddings
    from vector_store import get_vector_store
    
    print("🧪 Ejecutando tests...")
    
    # Test embeddings
    try:
        test_embeddings()
        print("✅ Embeddings: OK")
    except Exception as e:
        print(f"❌ Embeddings: {e}")
        return 1
    
    # Test vector store
    try:
        vs = get_vector_store()
        stats = vs.get_stats()
        print(f"✅ Vector Store: OK ({stats['total_chunks']} chunks)")
    except Exception as e:
        print(f"❌ Vector Store: {e}")
        return 1
    
    print("\n🎉 Todos los tests pasaron")
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Sistema RAG - Digital Lab",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Comandos')
    
    # index
    parser_index = subparsers.add_parser('index', help='Indexar documentos')
    parser_index.add_argument('--path', help='Directorio con documentos')
    parser_index.add_argument('--all', action='store_true', help='Indexar todas las carpetas en input/')
    parser_index.set_defaults(func=cmd_index)
    
    # query
    parser_query = subparsers.add_parser('query', help='Buscar en conocimiento')
    parser_query.add_argument('-q', '--query', required=True, help='Consulta')
    parser_query.add_argument('-n', type=int, default=5, help='Número de resultados')
    parser_query.add_argument('--topic', help='Filtrar por topic específico')
    parser_query.add_argument('--category', help='Filtrar por categoría específica')
    parser_query.set_defaults(func=cmd_query)
    
    # watch
    parser_watch = subparsers.add_parser('watch', help='Iniciar watchdog daemon')
    parser_watch.add_argument('--path', help='Directorio a monitorear')
    parser_watch.set_defaults(func=cmd_watch)
    
    # status
    parser_status = subparsers.add_parser('status', help='Ver estado')
    parser_status.add_argument('--detailed', action='store_true', help='Mostrar detalles por topic')
    parser_status.set_defaults(func=cmd_status)
    
    # topics
    parser_topics = subparsers.add_parser('topics', help='Ver topics disponibles')
    parser_topics.set_defaults(func=cmd_topics)
    
    # test
    parser_test = subparsers.add_parser('test', help='Test del sistema')
    parser_test.set_defaults(func=cmd_test)
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 0
    
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
