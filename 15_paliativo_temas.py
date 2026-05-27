# -*- coding: utf-8 -*-
"""
Paliativo: classifica tema_macro usando EXCLUSIVAMENTE a API oficial da Câmara.
Sobrescreve qualquer tema anterior gerado por LLM.

Checkpoint em .temas_checkpoint.json para retomar se interrompido.
"""

import sqlite3
import json
import time
import requests
from pathlib import Path
from tqdm import tqdm

DB_PATH = "/Users/aislangreca/TCC/tabelao.db"
CHECKPOINT_PATH = "/Users/aislangreca/TCC/.temas_checkpoint.json"
API_TEMAS = "https://dadosabertos.camara.leg.br/api/v2/proposicoes/{id}/temas"
DELAY_ENTRE_CALLS = 0.15
COMMIT_INTERVALO = 500  # commit a cada N proposições processadas


def buscar_temas(id_proposicao: int, session: requests.Session) -> str | None:
    """Retorna string com temas oficiais separados por vírgula, ou None."""
    try:
        resp = session.get(API_TEMAS.format(id=id_proposicao), timeout=15)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        temas = resp.json().get("dados", [])
        if not temas:
            return None
        temas_sorted = sorted(temas, key=lambda t: t.get("relevancia", 0), reverse=True)
        nomes = [t.get("tema", "").strip() for t in temas_sorted if t.get("tema")]
        return ", ".join(nomes[:3]) if nomes else None
    except Exception:
        return None


def carregar_checkpoint() -> set[int]:
    """Retorna conjunto de id_proposicao já consultados na API."""
    p = Path(CHECKPOINT_PATH)
    if p.exists():
        try:
            return set(json.loads(p.read_text()))
        except Exception:
            pass
    return set()


def salvar_checkpoint(processados: set[int]):
    Path(CHECKPOINT_PATH).write_text(json.dumps(list(processados)))


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    cur = conn.cursor()

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

    # ── Carrega pares votação ↔ proposição ─────────────────────────────────────
    print("Carregando pares votação ↔ proposição do raw_vault...")
    cur.execute("""
        SELECT
            id_votacao,
            CAST(json_extract(raw_json, '$.dados.objetosPossiveis[0].id') AS INTEGER) AS id_prop
        FROM votacoes_raw_vault
        WHERE tipo_dado = 'detalhe'
          AND json_extract(raw_json, '$.dados.objetosPossiveis[0].id') IS NOT NULL
    """)
    pares = cur.fetchall()
    print(f"  {len(pares)} pares encontrados.")

    prop_para_votacoes: dict[int, list[str]] = {}
    for id_votacao, id_prop in pares:
        if id_prop:
            prop_para_votacoes.setdefault(id_prop, []).append(id_votacao)

    todas_proposicoes = list(prop_para_votacoes.keys())
    print(f"  {len(todas_proposicoes)} proposições únicas encontradas.")

    # ── Trava por checkpoint (API já consultada) ───────────────────────────────
    ja_consultados = carregar_checkpoint()
    pendentes = [p for p in todas_proposicoes if p not in ja_consultados]
    print(f"  {len(ja_consultados)} já consultadas na API (checkpoint) → pulando.")
    print(f"  {len(pendentes)} proposições pendentes para processar.\n")

    # ── Processa ───────────────────────────────────────────────────────────────
    session = requests.Session()
    session.headers.update({"Accept": "application/json"})

    atualizados = 0
    sem_tema_api = 0
    processados_desde_commit = 0

    with tqdm(total=len(pendentes), desc="Temas (API Câmara)", unit="prop",
              bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}]") as pbar:

        for id_prop in pendentes:
            tema = buscar_temas(id_prop, session)
            time.sleep(DELAY_ENTRE_CALLS)

            votacoes = prop_para_votacoes[id_prop]

            if tema:
                cur.executemany("""
                    INSERT INTO votacoes_analise_enrichment (id_votacao, tema_macro, atualizado_em)
                    VALUES (?, ?, datetime('now'))
                    ON CONFLICT(id_votacao) DO UPDATE SET
                        tema_macro = excluded.tema_macro,
                        atualizado_em = datetime('now')
                """, [(v, tema) for v in votacoes])
                atualizados += len(votacoes)
            else:
                sem_tema_api += len(votacoes)

            ja_consultados.add(id_prop)
            processados_desde_commit += 1

            if processados_desde_commit >= COMMIT_INTERVALO:
                conn.commit()
                salvar_checkpoint(ja_consultados)
                processados_desde_commit = 0

            pbar.update(1)
            pbar.set_postfix(atualizados=atualizados, sem_tema=sem_tema_api)

    conn.commit()
    salvar_checkpoint(ja_consultados)

    # ── Resumo ─────────────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print("RESUMO FINAL")
    print(f"{'='*60}")
    print(f"  Votações com tema oficial atualizado : {atualizados}")
    print(f"  Votações sem tema na API da Câmara   : {sem_tema_api}")

    cur.execute("""
        SELECT tema_macro, COUNT(*) as n
        FROM votacoes_analise_enrichment
        WHERE tema_macro IS NOT NULL AND tema_macro != ''
        GROUP BY tema_macro
        ORDER BY n DESC
        LIMIT 20
    """)
    print("\nTop 20 temas (API oficial Câmara):")
    for tema, n in cur.fetchall():
        print(f"  {n:5d}  {tema}")

    conn.close()
    print("\n✅ Paliativo de temas concluído.")


if __name__ == "__main__":
    main()
