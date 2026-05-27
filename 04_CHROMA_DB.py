#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
04_CHROMA_DB_FINAL.py - Processamento de Discursos 2023+
Baseado no código de referência 04_CHROMA_DB_old.py
"""

import os
import re
import json
import time
import argparse
import sqlite3
import hashlib
from datetime import datetime
from typing import List, Tuple, Dict, Optional, Iterable

from tqdm import tqdm
import chromadb
from chromadb.api.types import Documents, Embeddings, Metadatas, IDs
from openai import OpenAI

# ============== CONFIG ==============
DEFAULT_DB_PATH = "discursos.db"
OUTPUT_DIR = "./vetores"
COLLECTION_NAME = "discursos_2023_plus"

EMBED_MODEL = "text-embedding-ada-002"    # 1536 dims
EMBED_DIM = 1536

DOCS_PER_BATCH = 1000                     # quantos documentos por lote
EMBED_BATCH_SIZE = 100                    # quantos CHUNKS por chamada de embedding
CHUNK_SIZE_CHARS = 8000                   # discursos curtos → 1 chunk na maioria
MAX_RETRIES = 5

# Forçar nomes para nosso banco
FORCE_TABLE_NAME = "discursos"
FORCE_TEXT_COLUMN = "Texto"
FORCE_ID_COLUMN = "ID"
FORCE_DATE_COLUMN = "Data"

# ============== ENV E CLIENTES ==============
def load_env():
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:
        pass

def get_openai_client() -> OpenAI:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("Defina OPENAI_API_KEY no ambiente ou em um arquivo .env")
    return OpenAI(api_key=api_key)

# ============== SQLITE ==============
def connect_sqlite(path: str) -> sqlite3.Connection:
    if not os.path.exists(path):
        raise FileNotFoundError(f"SQLite não encontrado: {path}")
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn

def fetch_rows_2023_plus(conn: sqlite3.Connection, table: str, id_col: str, text_col: str) -> List[sqlite3.Row]:
    """Busca dados de 2023 em diante"""
    select_base = f"SELECT {id_col} AS base_id, {text_col} AS texto, * FROM {table}"
    q = f"""{select_base} 
           WHERE LENGTH({text_col}) > 50
           AND ({FORCE_DATE_COLUMN} LIKE '%/2023' OR {FORCE_DATE_COLUMN} LIKE '%/2024' OR {FORCE_DATE_COLUMN} LIKE '%/2025' OR {FORCE_DATE_COLUMN} LIKE '%/2026' OR {FORCE_DATE_COLUMN} LIKE '%/2027' OR {FORCE_DATE_COLUMN} LIKE '%/2028' OR {FORCE_DATE_COLUMN} LIKE '%/2029' OR {FORCE_DATE_COLUMN} LIKE '%/2030')
           ORDER BY ROWID"""
    return conn.execute(q).fetchall()

# ============== MANIFESTO (anti-reprocesso) ==============
def ensure_manifest_db(output_dir: str) -> sqlite3.Connection:
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, "manifest.db")
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS processed (
            base_id TEXT PRIMARY KEY,
            content_hash TEXT NOT NULL,
            chunk_count INTEGER NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.commit()
    return conn

def manifest_get(conn: sqlite3.Connection, base_id: str) -> Optional[sqlite3.Row]:
    cur = conn.execute("SELECT base_id, content_hash, chunk_count, updated_at FROM processed WHERE base_id = ?", (base_id,))
    return cur.fetchone()

def manifest_upsert_many(conn: sqlite3.Connection, rows: List[Tuple[str, str, int]]):
    now = datetime.utcnow().isoformat()
    conn.executemany("""
        INSERT INTO processed (base_id, content_hash, chunk_count, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(base_id) DO UPDATE SET
            content_hash=excluded.content_hash,
            chunk_count=excluded.chunk_count,
            updated_at=excluded.updated_at
    """, [(bid, h, cnt, now) for (bid, h, cnt) in rows])
    conn.commit()

# ============== OPENAI EMBEDDINGS ==============
def embed_batch(client: OpenAI, texts: List[str], model: str, max_retries: int = MAX_RETRIES) -> List[List[float]]:
    for attempt in range(max_retries):
        try:
            resp = client.embeddings.create(model=model, input=texts)
            vecs = [d.embedding for d in resp.data]
            # sanity check
            if any(len(v) != EMBED_DIM for v in vecs):
                raise RuntimeError(f"Embedding com dimensão inesperada. Esperado {EMBED_DIM}.")
            return vecs
        except Exception as e:
            error_str = str(e)
            
            # Se a OpenAI rejeitar por limite (payload muito grande ou tokens individuais)
            if "maximum context length" in error_str.lower() or "too large" in error_str.lower() or "400" in error_str:
                if len(texts) > 1:
                    print(f"\n[embed] Lote rejeitado ({len(texts)} itens). Dividindo pela metade (força bruta)...")
                    mid = len(texts) // 2
                    part1 = embed_batch(client, texts[:mid], model, max_retries)
                    part2 = embed_batch(client, texts[mid:], model, max_retries)
                    return part1 + part2
                else:
                    try:
                        print("\n[embed] Truncando 1 chunk bizarro que excede sozinho o limite de tokens da OpenAI...")
                        # Corta pela metade o texto para caber no limite da OpenAI
                        texto_cortado = texts[0][:len(texts[0]) // 2]
                        # Tenta embeddar apenas a metade
                        resp = client.embeddings.create(model=model, input=[texto_cortado])
                        return [resp.data[0].embedding]
                    except Exception as fatal_e:
                        print(f"\n[embed] Nem truncando funcionou, retornando zeros. Erro: {fatal_e}")
                        return [[0.0] * EMBED_DIM]

            wait = min(2 ** attempt, 30)
            print(f"\n[embed] Erro: {error_str}. Retry em {wait}s ({attempt+1}/{max_retries})...")
            time.sleep(wait)
    raise RuntimeError("Falha ao gerar embeddings após múltiplas tentativas.")

# ============== CHROMA ==============
def get_chroma_client(path: str):
    os.makedirs(path, exist_ok=True)
    return chromadb.PersistentClient(path=path)

def ensure_collection(client, name: str):
    # Não registramos embedding_function; passamos embeddings prontos
    return client.get_or_create_collection(name=name, metadata={"hnsw:space": "cosine"})

def ensure_collection_meta(output_dir: str, collection_name: str, client, force_reset: bool = False):
    meta_path = os.path.join(output_dir, f"{collection_name}__meta.json")
    current = {"model": EMBED_MODEL, "dimension": EMBED_DIM}
    if os.path.exists(meta_path):
        with open(meta_path, "r", encoding="utf-8") as f:
            old = json.load(f)
        if (old.get("model") != EMBED_MODEL) or (old.get("dimension") != EMBED_DIM):
            if not force_reset:
                raise RuntimeError(
                    f"[guard] Coleção tem meta diferente ({old}). Use --force-reset ou apague {output_dir}."
                )
            try:
                client.delete_collection(collection_name)
            except Exception:
                pass
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(current, f, ensure_ascii=False, indent=2)
            return
        return
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(current, f, ensure_ascii=False, indent=2)

# ============== LÓGICA DE LOTE ==============
def sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def chunk_text(text: str, max_chars: int) -> List[str]:
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]
    return [text[i:i+max_chars] for i in range(0, len(text), max_chars)]

def yield_doc_batches(items: List[Dict], docs_per_batch: int) -> Iterable[List[Dict]]:
    for i in range(0, len(items), docs_per_batch):
        yield items[i:i+docs_per_batch]

def prepare_chunks_for_batch(doc_batch: List[Dict], table: str, text_col: str) -> Tuple[List[str], List[str], List[Dict], List[Tuple[str,str,int]], List[str]]:
    ids: IDs = []
    docs: Documents = []
    metas: Metadatas = []
    manifest_rows: List[Tuple[str, str, int]] = []
    base_ids_unique: List[str] = []

    for item in doc_batch:
        base_id = item["base_id"]
        texto = item["texto"]
        content_hash = item["content_hash"]
        row_dict = item["row"]
        
        # Usar o hash da linha como ID único
        unique_base_id = content_hash

        chunks = chunk_text(texto, CHUNK_SIZE_CHARS)
        cnt = len(chunks)
        manifest_rows.append((unique_base_id, content_hash, cnt))
        base_ids_unique.append(unique_base_id)

        # Criar metadados limpos
        base_meta = {k: v for k, v in row_dict.items() if k not in ("texto", text_col) and v is not None}
        base_meta["base_id"] = unique_base_id
        base_meta["original_id"] = base_id
        base_meta["table"] = table
        base_meta["text_col"] = text_col
        base_meta["hash"] = content_hash

        for idx, ch in enumerate(chunks):
            cid = f"2023_plus_{unique_base_id[:16]}#{idx:03d}"  # ID único com hash truncado
            ids.append(cid)
            docs.append(ch)
            meta = dict(base_meta)
            meta["chunk_index"] = idx
            meta["chunk_total"] = cnt
            metas.append(meta)

    # de-dup base_ids mantendo ordem
    seen = set(); uniq = []
    for b in base_ids_unique:
        if b not in seen:
            seen.add(b); uniq.append(b)

    return ids, docs, metas, manifest_rows, uniq

def upsert_in_embed_sublots(openai_client, collection, ids: IDs, docs: Documents, metas: Metadatas):
    assert len(ids) == len(docs) == len(metas)
    total = len(docs)
    for i in tqdm(range(0, total, EMBED_BATCH_SIZE), desc="Embeddings (sublotes)", unit="lote"):
        j = i + EMBED_BATCH_SIZE
        sub_ids = ids[i:j]
        sub_docs = docs[i:j]
        sub_metas = metas[i:j]
        vectors: Embeddings = embed_batch(openai_client, sub_docs, EMBED_MODEL)
        collection.upsert(ids=sub_ids, embeddings=vectors, documents=sub_docs, metadatas=sub_metas)

def delete_old_for_batch(collection, base_ids: List[str]):
    for bid in base_ids:
        try:
            collection.delete(where={"base_id": bid})
        except Exception:
            pass

# ============== PIPELINE ==============
def build_todo(rows: List[sqlite3.Row], man_conn: sqlite3.Connection) -> List[Dict]:
    todo = []
    for r in rows:
        base_id = str(r["base_id"])
        texto = (r["texto"] or "").strip()
        if not texto:
            continue
        
        # Gerar hash da linha completa para chave única
        row_dict = dict(r)
        row_str = str(sorted(row_dict.items()))
        row_hash = sha256_text(row_str)
        
        mrow = manifest_get(man_conn, row_hash)
        if (mrow is None) or (mrow["content_hash"] != row_hash):
            todo.append({"base_id": base_id, "texto": texto, "content_hash": row_hash, "row": row_dict})
    return todo

def run(db_path: str, docs_per_batch: int, embed_batch_size: int, force_reset: bool, test_limit: Optional[int] = None):
    print("== Processamento de Discursos 2023+ ==")
    print(f"SQLite: {db_path}")
    print(f"Coleção: {COLLECTION_NAME} | Persist: {OUTPUT_DIR}")
    print(f"Modelo: {EMBED_MODEL} ({EMBED_DIM} dims)")
    print(f"Lotes: docs_per_batch={docs_per_batch} embed_batch_size={embed_batch_size}")
    if test_limit:
        print(f"TESTE: Limitando a {test_limit} documentos")
    print()

    load_env()
    sql = connect_sqlite(db_path)
    man = ensure_manifest_db(OUTPUT_DIR)
    openai_client = get_openai_client()

    # schema fixo
    table, text_col, id_col = FORCE_TABLE_NAME, FORCE_TEXT_COLUMN, FORCE_ID_COLUMN
    print(f"[schema] tabela={table} | texto={text_col} | id={id_col} | data={FORCE_DATE_COLUMN}")

    # dados filtrados
    rows = fetch_rows_2023_plus(sql, table, id_col, text_col)
    print(f"[dados] Linhas 2023+: {len(rows)}")
    
    # Aplicar limite de teste se especificado
    if test_limit and len(rows) > test_limit:
        rows = rows[:test_limit]
        print(f"[teste] Limitado a {len(rows)} documentos")

    # plano
    todo = build_todo(rows, man)
    print(f"[plan] Novos/alterados a vetorizar: {len(todo)}")
    if not todo:
        print("Nada para vetorizar. ✅")
        return

    chroma_client = get_chroma_client(OUTPUT_DIR)
    ensure_collection_meta(OUTPUT_DIR, COLLECTION_NAME, chroma_client, force_reset=force_reset)
    collection = ensure_collection(chroma_client, COLLECTION_NAME)

    # processamento em lotes
    processed_docs = 0
    for doc_batch in tqdm(list(yield_doc_batches(todo, docs_per_batch)), desc="Lotes (documentos)", unit="lote"):
        if not doc_batch:
            continue
        ids, docs, metas, manifest_rows, base_ids = prepare_chunks_for_batch(doc_batch, table, text_col)
        delete_old_for_batch(collection, base_ids)
        if docs:
            upsert_in_embed_sublots(openai_client, collection, ids, docs, metas)
        manifest_upsert_many(man, manifest_rows)
        processed_docs += len(doc_batch)

    print("\nConcluído! ✅")
    print(f"- Documentos (bases) processados: {processed_docs}")
    print(f"- Coleção: {COLLECTION_NAME}")
    print(f"- Pasta persistida: {os.path.abspath(OUTPUT_DIR)}")

# ============== CLI ==============
def parse_args():
    ap = argparse.ArgumentParser(description="Processa discursos 2023-2025.")
    ap.add_argument("--db", type=str, default=DEFAULT_DB_PATH, help="Caminho do SQLite")
    ap.add_argument("--docs-per-batch", type=int, default=DOCS_PER_BATCH, help="Docs por lote")
    ap.add_argument("--embed-batch-size", type=int, default=EMBED_BATCH_SIZE, help="Chunks por chamada de embedding")
    ap.add_argument("--force-reset", action="store_true", help="Recria coleção se meta incompatível")
    ap.add_argument("--test", type=int, default=None, help="Limitar a N documentos para teste")
    return ap.parse_args()

if __name__ == "__main__":
    args = parse_args()
    # no módulo (topo), NÃO use 'global' — basta atribuir
    EMBED_BATCH_SIZE = args.embed_batch_size
    run(
        db_path=args.db,
        docs_per_batch=args.docs_per_batch,
        embed_batch_size=args.embed_batch_size,
        force_reset=args.force_reset,
        test_limit=args.test
    )
