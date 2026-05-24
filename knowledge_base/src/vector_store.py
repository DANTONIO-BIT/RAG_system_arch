#!/usr/bin/env python3
"""
Vector Store: ChromaDB con persistencia
"""
import logging
import os
from pathlib import Path
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

try:
    import chromadb
    from chromadb.config import Settings
    CHROMA_AVAILABLE = True
except ImportError:
    CHROMA_AVAILABLE = False
    logger.warning("chromadb no disponible: pip install chromadb")

DEFAULT_COLLECTION = "digital_lab_knowledge"
EMBEDDING_DIM = 1024


class VectorStore:
    def __init__(self, persist_dir: str = None, collection_name: str = None):
        if not CHROMA_AVAILABLE:
            raise ImportError("chromadb requerido: pip install chromadb")

        if persist_dir is None:
            base_dir = Path(__file__).parent.parent
            persist_dir = base_dir / "data" / "chroma_db"

        self.persist_dir = Path(persist_dir)
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self.collection_name = collection_name or DEFAULT_COLLECTION

        self.client = chromadb.PersistentClient(
            path=str(self.persist_dir),
            settings=Settings(anonymized_telemetry=False)
        )

        self.collection = self.client.get_or_create_collection(
            name=self.collection_name,
            metadata={"description": f"Knowledge Base - {self.collection_name}"}
        )

        logger.info(f"ChromaDB [{self.collection_name}]: {self.collection.count()} docs")
    
    def add_documents(self, documents: List[Dict]) -> int:
        """Añade documentos al vector store"""
        ids = []
        embeddings = []
        documents_text = []
        metadatas = []
        
        for doc in documents:
            # Generar ID base del documento
            doc_id_base = doc['metadata']['hash'][:16]
            filename = doc['metadata']['filename']
            
            # Embeddings de los chunks
            if 'embeddings' not in doc:
                logger.warning(f"Documento sin embeddings: {filename}")
                continue
            
            # Añadir cada chunk con su propio ID
            for i, (chunk, embedding) in enumerate(zip(doc['chunks'], doc['embeddings'])):
                chunk_id = f"{doc_id_base}_chunk{i}_{filename[:20]}"
                ids.append(chunk_id)
                embeddings.append(embedding)
                documents_text.append(chunk)
                
                metadata = {
                    **doc['metadata'],
                    'chunk_index': i,
                    'doc_id': doc_id_base
                }
                metadatas.append(metadata)
        
        if not ids:
            logger.warning("No hay documentos para añadir")
            return 0
        
        # Añadir al collection
        self.collection.add(
            ids=ids,
            embeddings=embeddings,
            documents=documents_text,
            metadatas=metadatas
        )
        
        total_chunks = len(documents_text)
        logger.info(f"Añadidos {total_chunks} chunks al vector store")
        
        return total_chunks
    
    def query(self, query_text: str, n_results: int = 5, topic: str = None, category: str = None) -> Dict:
        """Busca documentos similares con filtro opcional por topic/category"""
        from embeddings import generate_embedding
        
        # Generar embedding de la query
        query_embedding = generate_embedding(query_text)
        
        # Construir filtro where
        where_clause = {}
        if topic:
            where_clause["topic"] = topic
        if category:
            where_clause["category"] = category
        
        where = where_clause if where_clause else None
        
        # Buscar en ChromaDB con filtro
        try:
            results = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=n_results,
                where=where
            )
        except Exception:
            results = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=n_results
            )
        
        return results
    
    def get_all_documents(self) -> List[Dict]:
        """Obtiene todos los documentos"""
        results = self.collection.get()
        
        documents = []
        for i, doc_id in enumerate(results['ids']):
            documents.append({
                'id': doc_id,
                'text': results['documents'][i],
                'metadata': results['metadatas'][i]
            })
        
        return documents
    
    def get_stats(self) -> Dict:
        count = self.collection.count()

        unique_docs = set()
        results = self.collection.get()
        for meta in results.get('metadatas', []):
            if 'filename' in meta:
                unique_docs.add(meta['filename'])

        return {
            'total_chunks': count,
            'unique_documents': len(unique_docs),
            'collection_name': self.collection_name,
            'persist_dir': str(self.persist_dir)
        }
    
    def get_available_topics(self) -> Dict:
        """Obtiene lista de topics disponibles con sus estadísticas"""
        results = self.collection.get()
        
        topics_stats = {}
        for meta in results.get('metadatas', []):
            topic = meta.get('topic', 'unknown')
            category = meta.get('category', 'unknown')
            
            if topic not in topics_stats:
                topics_stats[topic] = {
                    'category': category,
                    'documents': set(),
                    'chunks': 0
                }
            
            if 'filename' in meta:
                topics_stats[topic]['documents'].add(meta['filename'])
            topics_stats[topic]['chunks'] += 1
        
        # Convert sets to counts
        for topic in topics_stats:
            topics_stats[topic]['document_count'] = len(topics_stats[topic]['documents'])
            topics_stats[topic]['chunk_count'] = topics_stats[topic]['chunks']
            del topics_stats[topic]['documents']
            del topics_stats[topic]['chunks']
        
        return topics_stats
    
    def get_documents_by_topic(self, topic: str) -> List[Dict]:
        """Obtiene todos los documentos de un topic específico"""
        results = self.collection.get(where={"topic": topic})
        
        documents = []
        for i, doc_id in enumerate(results['ids']):
            documents.append({
                'id': doc_id,
                'text': results['documents'][i],
                'metadata': results['metadatas'][i]
            })
        
        return documents
    
    def check_document_exists(self, doc_hash: str) -> bool:
        """Verifica si un documento ya está indexado usando filtro eficiente"""
        try:
            results = self.collection.get(where={"hash": doc_hash})
            return len(results.get('ids', [])) > 0
        except Exception as e:
            logger.warning(f"Error en check_document_exists con filtro: {e}")
            return False
    
    def delete_document(self, doc_id: str):
        """Elimina un documento por ID"""
        self.collection.delete(ids=[doc_id])
        logger.info(f"Documento eliminado: {doc_id}")
    
    def reset(self):
        self.client.delete_collection(self.collection_name)
        self.collection = self.client.get_or_create_collection(
            name=self.collection_name,
            metadata={"description": f"Knowledge Base - {self.collection_name}"}
        )
        logger.warning(f"Vector store reseteado: {self.collection_name}")


def get_vector_store(collection_name: str = None, persist_dir: str = None) -> VectorStore:
    return VectorStore(persist_dir=persist_dir, collection_name=collection_name)


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    
    vs = get_vector_store()
    stats = vs.get_stats()
    print(f"Estadísticas: {stats}")
