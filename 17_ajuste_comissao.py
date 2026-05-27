#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
17_ajuste_comissao.py
Script para ajustar os nomes das comissões na tabela presencas_eventos
para corresponder aos nomes corretos usados em discursos.db
"""

import sqlite3
import pandas as pd
from pathlib import Path
from difflib import SequenceMatcher
import re
from tqdm import tqdm

BASE_DIR = Path(__file__).resolve().parent
DB_TABELAO = BASE_DIR / "tabelao.db"
DB_DISCURSOS = BASE_DIR / "discursos.db"


def normalizar_nome(nome):
    """Normaliza nome de comissão para comparação."""
    if not nome or pd.isna(nome):
        return ""
    
    nome = str(nome).strip()
    # Converter para minúsculas
    nome = nome.lower()
    # Remover acentos básicos (simplificado)
    nome = nome.replace("á", "a").replace("à", "a").replace("â", "a").replace("ã", "a")
    nome = nome.replace("é", "e").replace("ê", "e")
    nome = nome.replace("í", "i").replace("î", "i")
    nome = nome.replace("ó", "o").replace("ô", "o").replace("õ", "o")
    nome = nome.replace("ú", "u").replace("û", "u")
    nome = nome.replace("ç", "c")
    # Remover pontuação e espaços extras
    nome = re.sub(r'[^\w\s]', '', nome)
    nome = re.sub(r'\s+', ' ', nome).strip()
    
    return nome


def similaridade(nome1, nome2):
    """Calcula similaridade entre dois nomes (0-1)."""
    if not nome1 or not nome2:
        return 0.0
    return SequenceMatcher(None, nome1, nome2).ratio()


def criar_mapeamento_comissoes():
    """Cria mapeamento entre nomes de comissões das duas tabelas."""
    print("📊 Carregando comissões de ambas as tabelas...")
    
    # Carregar comissões de presencas_eventos
    conn_tabelao = sqlite3.connect(DB_TABELAO)
    query_presencas = """
        SELECT DISTINCT id_orgao, nome_orgao, tipo_orgao
        FROM presencas_eventos
        WHERE nome_orgao IS NOT NULL 
          AND nome_orgao != ''
          AND id_orgao != '0'
        ORDER BY nome_orgao
    """
    df_presencas = pd.read_sql_query(query_presencas, conn_tabelao)
    conn_tabelao.close()
    
    # Carregar comissões de discursos
    conn_discursos = sqlite3.connect(DB_DISCURSOS)
    query_discursos = """
        SELECT DISTINCT Comissao
        FROM discursos
        WHERE Comissao IS NOT NULL 
          AND Comissao != ''
          AND Comissao != 'Não aplicável'
          AND Comissao != 'Plenário'
        ORDER BY Comissao
    """
    df_discursos = pd.read_sql_query(query_discursos, conn_discursos)
    conn_discursos.close()
    
    print(f"✅ Encontradas {len(df_presencas)} comissões em presencas_eventos")
    print(f"✅ Encontradas {len(df_discursos)} comissões em discursos")
    
    # Criar dicionário de mapeamento
    mapeamento = {}
    nomes_discursos = df_discursos['Comissao'].tolist()
    nomes_discursos_normalizados = {normalizar_nome(nome): nome for nome in nomes_discursos}
    
    print("\n🔍 Criando mapeamento...")
    for _, row in tqdm(df_presencas.iterrows(), total=len(df_presencas), desc="Processando"):
        id_orgao = row['id_orgao']
        nome_presencas = row['nome_orgao']
        nome_presencas_norm = normalizar_nome(nome_presencas)
        
        # Tentar match exato primeiro
        if nome_presencas_norm in nomes_discursos_normalizados:
            nome_correto = nomes_discursos_normalizados[nome_presencas_norm]
            mapeamento[id_orgao] = {
                'nome_antigo': nome_presencas,
                'nome_novo': nome_correto,
                'tipo': 'exato',
                'similaridade': 1.0
            }
            continue
        
        # Tentar match por similaridade
        melhor_match = None
        melhor_similaridade = 0.0
        melhor_nome = None
        
        for nome_disc_norm, nome_disc_original in nomes_discursos_normalizados.items():
            sim = similaridade(nome_presencas_norm, nome_disc_norm)
            if sim > melhor_similaridade:
                melhor_similaridade = sim
                melhor_match = nome_disc_norm
                melhor_nome = nome_disc_original
        
        # Se similaridade > 0.85, considerar match
        if melhor_similaridade > 0.85:
            mapeamento[id_orgao] = {
                'nome_antigo': nome_presencas,
                'nome_novo': melhor_nome,
                'tipo': 'similar',
                'similaridade': melhor_similaridade
            }
        else:
            # Sem match - manter nome original mas marcar
            mapeamento[id_orgao] = {
                'nome_antigo': nome_presencas,
                'nome_novo': nome_presencas,  # Manter original
                'tipo': 'sem_match',
                'similaridade': melhor_similaridade
            }
    
    return mapeamento, df_presencas


def aplicar_ajustes(mapeamento, dry_run=True):
    """Aplica os ajustes na tabela presencas_eventos."""
    conn = sqlite3.connect(DB_TABELAO)
    
    ajustes_aplicar = []
    ajustes_manter = []
    ajustes_sem_match = []
    
    for id_orgao, info in mapeamento.items():
        if info['nome_antigo'] != info['nome_novo']:
            ajustes_aplicar.append((id_orgao, info))
        elif info['tipo'] == 'sem_match':
            ajustes_sem_match.append((id_orgao, info))
        else:
            ajustes_manter.append((id_orgao, info))
    
    print(f"\n📋 Resumo do mapeamento:")
    print(f"   ✅ Match exato: {len([a for a in ajustes_manter if mapeamento[a[0]]['tipo'] == 'exato'])}")
    print(f"   🔄 Ajustes necessários (similar): {len([a for a in ajustes_aplicar if mapeamento[a[0]]['tipo'] == 'similar'])}")
    print(f"   ⚠️  Sem match encontrado: {len(ajustes_sem_match)}")
    
    if ajustes_aplicar:
        print(f"\n🔄 Ajustes a aplicar: {len(ajustes_aplicar)}")
        for id_orgao, info in ajustes_aplicar[:10]:  # Mostrar primeiros 10
            print(f"   {id_orgao}: '{info['nome_antigo'][:60]}...' -> '{info['nome_novo'][:60]}...' (sim: {info['similaridade']:.2f})")
        if len(ajustes_aplicar) > 10:
            print(f"   ... e mais {len(ajustes_aplicar) - 10} ajustes")
    
    if ajustes_sem_match:
        print(f"\n⚠️  Comissões sem match ({len(ajustes_sem_match)}):")
        for id_orgao, info in ajustes_sem_match[:5]:  # Mostrar primeiros 5
            print(f"   {id_orgao}: '{info['nome_antigo'][:80]}...'")
        if len(ajustes_sem_match) > 5:
            print(f"   ... e mais {len(ajustes_sem_match) - 5} comissões")
    
    if dry_run:
        print("\n🔍 MODO DRY-RUN: Nenhuma alteração foi aplicada.")
        print("   Execute com --apply para aplicar as alterações.")
        conn.close()
        return
    
    # Aplicar ajustes
    print(f"\n💾 Aplicando {len(ajustes_aplicar)} ajustes...")
    cursor = conn.cursor()
    
    for id_orgao, info in tqdm(ajustes_aplicar, desc="Aplicando ajustes"):
        cursor.execute(
            """
            UPDATE presencas_eventos
            SET nome_orgao = ?
            WHERE id_orgao = ?
            """,
            (info['nome_novo'], id_orgao)
        )
    
    conn.commit()
    print(f"✅ {len(ajustes_aplicar)} ajustes aplicados com sucesso!")
    
    # Verificar resultados
    cursor.execute("SELECT COUNT(DISTINCT nome_orgao) FROM presencas_eventos WHERE id_orgao != '0'")
    total_unicos = cursor.fetchone()[0]
    print(f"📊 Total de nomes únicos de comissões após ajuste: {total_unicos}")
    
    conn.close()


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Ajusta nomes de comissões na tabela presencas_eventos')
    parser.add_argument('--apply', action='store_true', help='Aplica as alterações (sem isso, apenas mostra o que seria feito)')
    parser.add_argument('--min-similarity', type=float, default=0.85, help='Similaridade mínima para considerar match (padrão: 0.85)')
    
    args = parser.parse_args()
    
    print("=" * 80)
    print("🔧 AJUSTE DE NOMES DE COMISSÕES")
    print("=" * 80)
    
    if not DB_TABELAO.exists():
        print(f"❌ Erro: {DB_TABELAO} não encontrado!")
        return
    
    if not DB_DISCURSOS.exists():
        print(f"❌ Erro: {DB_DISCURSOS} não encontrado!")
        return
    
    # Criar mapeamento
    mapeamento, df_presencas = criar_mapeamento_comissoes()
    
    # Aplicar ajustes
    aplicar_ajustes(mapeamento, dry_run=not args.apply)
    
    print("\n" + "=" * 80)
    print("✅ Processo concluído!")
    print("=" * 80)


if __name__ == "__main__":
    main()

