# -*- coding: utf-8 -*-
"""
Paliativo para corrigir pauta_governo e aprovacao nas votacoes já no banco.

Estratégia (sem LLM):
1. Extrai orientacao oficial do Governo do raw_vault (siglaPartidoBloco='Governo')
   → pauta_governo = Sim / Não / Indiferente
2. Extrai aprovacao (0/1) do raw_vault (dados.aprovacao)
   → normaliza descricao com prefixo "Aprovado" ou "Rejeitado"
3. Atualiza votacoes_analise_enrichment.pauta_governo
4. Atualiza votacoes_unificadas.descricao para o backend poder calcular vitórias
"""

import sqlite3
import json

DB_PATH = "/Users/aislangreca/TCC/tabelao.db"

def extrair_pauta_governo(orientacoes_raw: str) -> str:
    """Retorna 'Sim', 'Não' ou 'Indiferente' com base na orientacao do Governo."""
    try:
        data = json.loads(orientacoes_raw)
        items = data.get('dados', []) if isinstance(data, dict) else []
        for item in items:
            sigla = item.get('siglaPartidoBloco', '') or ''
            if 'Governo' in sigla:
                voto = (item.get('orientacaoVoto') or '').strip()
                if voto == 'Sim':
                    return 'Sim'
                elif voto in ('Não', 'Obstrução', 'Nao'):
                    return 'Não'
                elif voto == 'Liberado':
                    return 'Indiferente'
    except Exception:
        pass
    return None  # sem orientacao do Governo disponível


def normalizar_descricao(descricao: str, aprovacao: int) -> str:
    """Garante que descricao começa com Aprovado/Rejeitado para o backend calcular vitórias."""
    if not descricao:
        descricao = ''
    desc_lower = descricao.lower()
    # Já tem prefixo correto
    if desc_lower.startswith('aprovad') or desc_lower.startswith('rejeitad'):
        return descricao
    # Adiciona prefixo baseado no campo aprovacao da API
    if aprovacao == 1:
        return f"Aprovado. {descricao}".strip()
    elif aprovacao == 0:
        return f"Rejeitado. {descricao}".strip()
    return descricao


def corrigir():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    cur = conn.cursor()

    # Garante que votacoes_analise_enrichment existe
    cur.execute("""
        CREATE TABLE IF NOT EXISTS votacoes_analise_enrichment (
            id_votacao TEXT PRIMARY KEY NOT NULL,
            tema_macro TEXT,
            resumo_leigo TEXT,
            pauta_governo TEXT,
            local_votacao TEXT,
            analise_ia_json TEXT,
            atualizado_em TEXT
        )
    """)
    conn.commit()

    # ─── PASSO 1: atualizar pauta_governo a partir das orientacoes ───────────
    print("=" * 60)
    print("PASSO 1: Extraindo orientação do Governo do raw_vault...")
    print("=" * 60)

    cur.execute("""
        SELECT o.id_votacao, o.raw_json
        FROM votacoes_raw_vault o
        WHERE o.tipo_dado = 'orientacoes'
          AND o.raw_json LIKE '%Governo%'
    """)
    orientacoes_rows = cur.fetchall()
    print(f"Votacoes com orientacao 'Governo': {len(orientacoes_rows)}")

    atualizado_sim = 0
    atualizado_nao = 0
    sem_orientacao = 0

    for id_votacao, raw_json in orientacoes_rows:
        pauta = extrair_pauta_governo(raw_json)
        if pauta is None:
            sem_orientacao += 1
            continue

        # Upsert em votacoes_analise_enrichment
        cur.execute("""
            INSERT INTO votacoes_analise_enrichment (id_votacao, pauta_governo, atualizado_em)
            VALUES (?, ?, datetime('now'))
            ON CONFLICT(id_votacao) DO UPDATE SET
                pauta_governo = excluded.pauta_governo,
                atualizado_em = datetime('now')
        """, (id_votacao, pauta))

        if pauta == 'Sim':
            atualizado_sim += 1
        elif pauta == 'Não':
            atualizado_nao += 1

    conn.commit()
    print(f"  → Pauta Sim: {atualizado_sim}")
    print(f"  → Pauta Não: {atualizado_nao}")
    print(f"  → Sem orientação clara: {sem_orientacao}")

    # ─── PASSO 2: normalizar descricao com Aprovado/Rejeitado ────────────────
    print()
    print("=" * 60)
    print("PASSO 2: Normalizando descricao (Aprovado/Rejeitado)...")
    print("=" * 60)

    cur.execute("""
        SELECT d.id_votacao,
               json_extract(d.raw_json, '$.dados.aprovacao') AS aprovacao,
               u.descricao
        FROM votacoes_raw_vault d
        JOIN votacoes_unificadas u ON d.id_votacao = u.id_votacao
        WHERE d.tipo_dado = 'detalhe'
          AND json_extract(d.raw_json, '$.dados.aprovacao') IS NOT NULL
    """)
    detalhe_rows = cur.fetchall()
    print(f"Registros com campo aprovacao: {len(detalhe_rows)}")

    normalizados = 0
    for id_votacao, aprovacao, descricao in detalhe_rows:
        try:
            aprovacao_int = int(aprovacao) if aprovacao is not None else None
        except (ValueError, TypeError):
            continue

        if aprovacao_int is None:
            continue

        nova_descricao = normalizar_descricao(descricao or '', aprovacao_int)
        if nova_descricao != (descricao or ''):
            cur.execute(
                "UPDATE votacoes_unificadas SET descricao=? WHERE id_votacao=?",
                (nova_descricao, id_votacao)
            )
            normalizados += 1

    conn.commit()
    print(f"  → Descricoes normalizadas: {normalizados}")

    # ─── RESUMO FINAL ─────────────────────────────────────────────────────────
    print()
    print("=" * 60)
    print("RESUMO FINAL")
    print("=" * 60)
    cur.execute("""
        SELECT pauta_governo, COUNT(*)
        FROM votacoes_analise_enrichment
        GROUP BY pauta_governo ORDER BY 2 DESC
    """)
    print("pauta_governo atual:")
    for r in cur.fetchall():
        print(f"  {r[0]}: {r[1]}")

    cur.execute("""
        SELECT
            SUM(CASE WHEN descricao LIKE 'Aprovad%' THEN 1 ELSE 0 END) as aprovadas,
            SUM(CASE WHEN descricao LIKE 'Rejeitad%' THEN 1 ELSE 0 END) as rejeitadas,
            COUNT(*) as total
        FROM votacoes_unificadas
    """)
    r = cur.fetchone()
    print(f"\nvotacoes_unificadas: {r[2]} total, {r[0]} Aprovadas, {r[1]} Rejeitadas")

    conn.close()
    print("\n✅ Paliativo concluído.")


if __name__ == "__main__":
    corrigir()
