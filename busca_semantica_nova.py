#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Busca Semântica Nova - Implementação Simplificada
Fluxo: 1) Usuário busca 2) LLM gera 10 palavras 3) Filtrar discursos 4) Gerar relatório 5) Frases impactantes
"""

import sqlite3
import json
from typing import List, Dict, Any
from openai import OpenAI
import os
from dotenv import load_dotenv

# Carregar variáveis de ambiente
load_dotenv()

# Configuração do OpenAI
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def gerar_palavras_chave(tema: str) -> List[str]:
    """Gera exatamente 10 palavras-chave relacionadas ao tema"""
    try:
        print(f"🔑 Gerando palavras-chave para tema: {tema}")
        prompt = f"""
        Gere exatamente 10 palavras-chave relacionadas ao tema "{tema}" para busca em discursos parlamentares.
        
        Regras:
        - Exatamente 10 palavras-chave
        - Uma por linha
        - Sem numeração
        - Termos específicos do tema
        - Sem repetições
        
        Tema: {tema}
        """
        
        print(f"⏳ Chamando LLM para gerar palavras-chave...")
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            timeout=60  # Timeout de 60 segundos
        )
        print(f"✅ Palavras-chave recebidas do LLM")
        
        palavras = response.choices[0].message.content.strip().split('\n')
        palavras_limpas = []
        
        for palavra in palavras:
            palavra = palavra.strip().lower()
            if palavra and len(palavra) > 2 and palavra not in palavras_limpas:
                palavras_limpas.append(palavra)
        
        # Garantir exatamente 10 palavras
        return palavras_limpas[:10]
        
    except Exception as e:
        print(f"Erro ao gerar palavras-chave: {e}")
        return [tema.lower()]

def buscar_discursos_com_palavras(palavras_chave: List[str], data_inicio: str, data_fim: str, db_path: str = None) -> List[Dict]:
    """Busca discursos que contenham as palavras-chave"""
    try:
        print(f"📚 Buscando discursos com {len(palavras_chave)} palavras-chave...")
        
        # Usar db_path fornecido ou caminho padrão
        if db_path is None:
            db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'discursos.db')
        
        print(f"📂 Conectando ao banco: {db_path}")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Converter datas para formato ISO
        data_inicio_iso = f"{data_inicio[0:4]}-{data_inicio[5:7]}-{data_inicio[8:10]}"
        data_fim_iso = f"{data_fim[0:4]}-{data_fim[5:7]}-{data_fim[8:10]}"
        
        print(f"📅 Período: {data_inicio_iso} a {data_fim_iso}")
        
        # Construir cláusula WHERE para busca por palavras-chave
        # Usar LIMIT na query para evitar buscar todos os discursos de uma vez
        where_conditions = []
        for palavra in palavras_chave:
            where_conditions.append(f"LOWER(Texto) LIKE LOWER('%{palavra}%')")
        
        where_clause = " OR ".join(where_conditions)
        
        # Query com filtro de data e LIMIT para melhor performance
        query = f"""
        SELECT DISTINCT ID, Texto, Data, Parlamentar, Partido, Estado, Comissao, Sessao
        FROM discursos 
        WHERE ({where_clause})
        AND date(substr(Data, 7, 4) || '-' || substr(Data, 4, 2) || '-' || substr(Data, 1, 2)) >= date(?)
        AND date(substr(Data, 7, 4) || '-' || substr(Data, 4, 2) || '-' || substr(Data, 1, 2)) <= date(?)
        ORDER BY Data DESC
        LIMIT 500
        """
        
        print(f"⏳ Executando query no banco de dados...")
        cursor.execute(query, (data_inicio_iso, data_fim_iso))
        
        print(f"📥 Carregando resultados...")
        rows = cursor.fetchall()
        discursos = []
        
        for row in rows:
            discursos.append({
                'ID': row[0],
                'Texto': row[1],
                'Data': row[2],
                'Parlamentar': row[3],
                'Partido': row[4],
                'Estado': row[5],
                'Comissao': row[6],
                'Sessao': row[7]
            })
        
        conn.close()
        
        # Verificar se há dados no período selecionado
        total_discursos_periodo = len(discursos)
        if total_discursos_periodo == 0:
            print(f"⚠️ Nenhum discurso encontrado no período {data_inicio_iso} a {data_fim_iso}")
            print("💡 O banco de dados contém discursos de 01/01/2023 a 31/10/2024")
            return []
        
        print(f"✅ Encontrados {total_discursos_periodo} discursos (limitado a 500)")
        return discursos
        
    except Exception as e:
        print(f"❌ Erro ao buscar discursos: {e}")
        import traceback
        traceback.print_exc()
        return []

def validar_discursos_llm(discursos: List[Dict], tema: str) -> List[Dict]:
    """Valida discursos com LLM para garantir relevância"""
    try:
        if not discursos:
            return []
        
        print(f"🤖 Validando {len(discursos)} discursos com LLM...")
        
        # Processar em lotes de 20
        discursos_validados = []
        batch_size = 20
        
        for i in range(0, len(discursos), batch_size):
            batch = discursos[i:i + batch_size]
            
            # Preparar dados do lote
            dados_lote = []
            for discurso in batch:
                dados_lote.append({
                    'texto': discurso['Texto'][:500],  # Limitar tamanho
                    'parlamentar': discurso['Parlamentar'],
                    'data': discurso['Data'],
                    'comissao': discurso['Comissao']
                })
            
            # Prompt para validação
            prompt = f"""
            Analise os discursos abaixo e determine quais são realmente relevantes para o tema "{tema}".
            
            Tema de busca: {tema}
            
            Discursos para análise:
            {json.dumps(dados_lote, ensure_ascii=False, indent=2)}
            
            Responda APENAS com um JSON no formato:
            {{
                "validacoes": [
                    {{"relevante": "SIM"}},
                    {{"relevante": "NÃO"}},
                    ...
                ]
            }}
            
            Critérios:
            - SIM: Discurso trata diretamente do tema ou assuntos relacionados
            - NÃO: Discurso não tem relação clara com o tema
            """
            
            print(f"⏳ Validando lote {i//batch_size + 1}/{len(discursos)//batch_size + 1} com LLM...")
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                timeout=120  # Timeout de 120 segundos para validação
            )
            print(f"✅ Lote {i//batch_size + 1} validado")
            
            try:
                # Limpar a resposta do LLM removendo markdown se houver
                resposta_limpa = response.choices[0].message.content.strip()
                if resposta_limpa.startswith('```json'):
                    resposta_limpa = resposta_limpa.replace('```json', '').replace('```', '').strip()
                
                resultado = json.loads(resposta_limpa)
                validacoes = resultado.get('validacoes', [])
                
                # Adicionar discursos validados
                for j, validacao in enumerate(validacoes):
                    if j < len(batch) and validacao.get('relevante') == 'SIM':
                        discursos_validados.append(batch[j])
                
                print(f"📊 Lote {i//batch_size + 1}: {len([v for v in validacoes if v.get('relevante') == 'SIM'])}/{len(batch)} discursos validados")
                
            except json.JSONDecodeError as e:
                print(f"⚠️ Erro ao processar resposta do LLM no lote {i//batch_size + 1}: {e}")
                print(f"Resposta recebida: {response.choices[0].message.content[:200]}...")
                continue
        
        print(f"✅ Validação concluída: {len(discursos_validados)} discursos realmente relevantes ao tema")
        return discursos_validados
        
    except Exception as e:
        print(f"Erro na validação LLM: {e}")
        return discursos  # Retornar todos se houver erro

def gerar_relatorio_llm(discursos: List[Dict], tema: str) -> str:
    """Gera relatório detalhado usando LLM"""
    try:
        if not discursos:
            return "Nenhum discurso relevante encontrado para análise."
        
        # Preparar dados para o relatório
        info_discursos = []
        parlamentares = []
        partidos = []
        estados = []
        
        for discurso in discursos:
            # Verificar se os campos existem e não são None
            parlamentar = discurso.get('Parlamentar', 'N/A') or 'N/A'
            partido = discurso.get('Partido', 'N/A') or 'N/A'
            estado = discurso.get('Estado', 'N/A') or 'N/A'
            data = discurso.get('Data', 'N/A') or 'N/A'
            comissao = discurso.get('Comissao', 'N/A') or 'N/A'
            texto = discurso.get('Texto', '') or ''
            
            info_discursos.append(f"• {parlamentar} ({partido}-{estado}) - {data} - {comissao}: {texto[:200]}...")
            parlamentares.append(parlamentar)
            partidos.append(partido)
            estados.append(estado)
        
        # Remover duplicatas
        parlamentares = list(set(parlamentares))
        partidos = list(set(partidos))
        estados = list(set(estados))
        
        prompt = f"""
        <relatorio>
        Preciso que você gere um documento EXTREMAMENTE DETALHADO com pelo menos 8-10 páginas, seguindo a estrutura abaixo, com uma perspectiva conservadora e estratégica:

        1. **Introdução** (mínimo 3 parágrafos):
           - Faça um resumo geral dos assuntos abordados nos discursos em três parágrafos, analisando criticamente as propostas e posicionamentos.
           - Informe quais assuntos no segmento que foi pesquisado pelo usuário foram tratados em três parágrafos, destacando as implicações práticas e custos.
           - Para cada assunto tratado, diga qual data e comissão foram falados em três parágrafos, analisando a viabilidade e eficácia das propostas.

        2. **Análise Estratégica** (mínimo 4 parágrafos):
           - Faça uma análise estratégica dos discursos, focando nas implicações econômicas, sociais e políticas das propostas.
           - Identifique padrões de gastos públicos, interferência estatal e impactos na livre iniciativa.
           - Analise criticamente as propostas que podem gerar dependência do Estado ou restrições à liberdade individual.
           - Examine as consequências de longo prazo das políticas propostas.

        3. **Impacto Real para o Cidadão** (mínimo 4 parágrafos):
           - Crie uma seção detalhando como as discussões impactam efetivamente o dia a dia e a vida cotidiana do cidadão.
           - Foque nos custos reais, burocracias criadas e restrições à liberdade individual.
           - Destaque o dia e em qual reunião isto aconteceu e quais os pontos foram mais relevantes para a vida prática do cidadão.
           - Analise o impacto econômico direto nas famílias e pequenos negócios.

        4. **Atores e Posicionamentos** (mínimo 3 parágrafos):
           - Liste todos os atores (pessoas, instituições, empresas) citados nas reuniões referenciando a data e o número da reunião que isto ocorreu.
           - Inclua quais deputados (citando estado e partido) possuem posições antagônicas e porque, analisando as diferenças ideológicas.
           - Identifique padrões de alinhamento com movimentos progressistas ou conservadores.

        5. **Análise de Custos e Orçamento** (mínimo 2 parágrafos):
           - Analise os custos estimados das propostas apresentadas.
           - Examine o impacto orçamentário e a sustentabilidade fiscal das medidas.

        6. **Recomendações Estratégicas** (mínimo 2 parágrafos):
           - Forneça recomendações baseadas na análise crítica dos discursos.
           - Sugira alternativas que preservem a liberdade individual e a eficiência econômica.

        IMPORTANTE: 
        - Use uma linguagem neutra e analítica, sem enaltecimento de movimentos progressistas ou "woke".
        - Foque na análise crítica das propostas e seus impactos reais.
        - Destaque custos, burocracias e restrições à liberdade individual.
        - Analise a viabilidade econômica e eficácia das propostas.
        - Formate os títulos em negrito e os subtítulos em itálico.
        - Escreva no final do documento que o texto foi desenvolvido por inteligência artificial com base nos discursos.
        - SEJA EXTREMAMENTE DETALHADO E COMPLETO - cada seção deve ter pelo menos 2-3 parágrafos longos.

        TEMA PESQUISADO: {tema}
        
        DADOS DOS DISCURSOS:
        {chr(10).join(info_discursos)}
        
        PARLAMENTARES ENVOLVIDOS: {', '.join(parlamentares[:15])}
        PARTIDOS: {', '.join(partidos[:10])}
        ESTADOS: {', '.join(estados[:10])}
        
        TOTAL DE DISCURSOS ANALISADOS: {len(discursos)}
        </relatorio>
        """
        
        print(f"⏳ Gerando relatório com LLM...")
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            timeout=300  # Timeout de 5 minutos para relatório longo
        )
        print(f"✅ Relatório gerado")
        return response.choices[0].message.content
        
    except Exception as e:
        print(f"Erro ao gerar relatório: {e}")
        return f"Erro ao gerar relatório: {str(e)}"

def gerar_frases_impactantes(discursos: List[Dict], tema: str) -> List[Dict]:
    """Gera frases impactantes dos parlamentares usando LLM para seleção, validando relevância ao tema"""
    try:
        if not discursos:
            return []
        
        print(f"🔍 Processando {len(discursos)} discursos para frases impactantes relevantes ao tema '{tema}'...")
        
        # Conectar ao tabelao para buscar fotos e informações
        tabelao_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tabelao.db')
        conn_tabelao = sqlite3.connect(tabelao_path)
        cursor_tabelao = conn_tabelao.cursor()
        
        # Preparar dados para o LLM selecionar as melhores frases
        # Manter mapeamento entre índice e discurso original
        discursos_para_analise = []
        for idx, discurso in enumerate(discursos):
            discursos_para_analise.append({
                'indice': idx,  # Usar índice real do discurso na lista original
                'parlamentar': discurso.get('Parlamentar', 'N/A'),
                'texto': discurso.get('Texto', '')[:800],  # Limitar para não sobrecarregar o LLM
                'comissao': discurso.get('Comissao', 'N/A'),
                'data': discurso.get('Data', 'N/A')
            })
        
        # Usar LLM para selecionar as 10 frases mais impactantes E RELEVANTES AO TEMA
        print(f"🤖 LLM selecionando frases impactantes e relevantes ao tema '{tema}'...")
        prompt = f"""
        Você é um especialista em análise de discursos parlamentares.
        
        TEMA DE BUSCA: "{tema}"
        
        Analise os discursos abaixo e selecione APENAS as frases que são:
        1. RELEVANTES ao tema "{tema}" - a frase DEVE tratar diretamente do tema ou assuntos relacionados
        2. IMPACTANTES - declarações que tenham impacto político ou social
        3. CLARAS - que demonstrem posicionamento claro do parlamentar sobre o tema
        
        IMPORTANTE: 
        - NÃO selecione frases que não tenham relação clara com o tema "{tema}"
        - Se um discurso não trata do tema, NÃO o inclua
        - Priorize qualidade e relevância sobre quantidade
        - Selecione no máximo 10 frases, mas pode ser menos se não houver frases relevantes
        
        Discursos para análise:
        {json.dumps(discursos_para_analise, ensure_ascii=False, indent=2)}
        
        Responda APENAS com um JSON no formato:
        {{
            "frases_selecionadas": [
                {{
                    "indice": 0,
                    "frase": "texto da frase impactante (máximo 300 caracteres)",
                    "relevancia": "explicação de por que esta frase é relevante ao tema '{tema}'",
                    "motivo": "por que esta frase é impactante"
                }},
                ...
            ]
        }}
        
        Selecione APENAS frases que sejam realmente relevantes ao tema "{tema}".
        """
        
        print(f"⏳ Selecionando frases impactantes com LLM...")
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            timeout=120  # Timeout de 120 segundos
        )
        print(f"✅ Frases impactantes selecionadas")
        
        try:
            # Limpar resposta do LLM removendo markdown se houver
            resposta_limpa = response.choices[0].message.content.strip()
            if resposta_limpa.startswith('```json'):
                resposta_limpa = resposta_limpa.replace('```json', '').replace('```', '').strip()
            elif resposta_limpa.startswith('```'):
                resposta_limpa = resposta_limpa.replace('```', '').strip()
            
            resultado = json.loads(resposta_limpa)
            frases_selecionadas = resultado.get('frases_selecionadas', [])
            print(f"✅ LLM selecionou {len(frases_selecionadas)} frases impactantes e relevantes ao tema")
        except json.JSONDecodeError as e:
            print(f"⚠️ Erro ao processar resposta do LLM: {e}")
            print(f"Resposta recebida: {response.choices[0].message.content[:500]}...")
            # Fallback: não retornar frases se não conseguir validar
            frases_selecionadas = []
        
        frases_impactantes = []
        
        # Processar as frases selecionadas pelo LLM
        for item in frases_selecionadas:
            indice = item.get('indice', -1)
            if indice >= 0 and indice < len(discursos):
                discurso = discursos[indice]
                
                # Extrair frase do item ou usar trecho do discurso
                frase_texto = item.get('frase', '')
                if not frase_texto or len(frase_texto) < 20:
                    # Se a frase não foi fornecida ou é muito curta, usar trecho do discurso
                    texto_completo = discurso.get('Texto', '')
                    frase_texto = texto_completo[:300] + "..." if len(texto_completo) > 300 else texto_completo
                
                # Buscar informações do parlamentar
                nome_parlamentar = discurso['Parlamentar'].upper().strip()
                
                # Tentar busca exata primeiro
                cursor_tabelao.execute("""
                    SELECT ultimoStatus_urlFoto, sgPartido, sgUF, " URL_Partido", URL_Estado
                    FROM tabelao 
                    WHERE UPPER(TRIM(nome)) = ?
                    LIMIT 1
                """, (nome_parlamentar,))
                
                info = cursor_tabelao.fetchone()
                
                # Se não encontrou, tentar busca parcial
                if not info:
                    cursor_tabelao.execute("""
                        SELECT ultimoStatus_urlFoto, sgPartido, sgUF, " URL_Partido", URL_Estado
                        FROM tabelao 
                        WHERE UPPER(TRIM(nome)) LIKE ?
                        LIMIT 1
                    """, (f'%{nome_parlamentar}%',))
                    info = cursor_tabelao.fetchone()
                
                if info:
                    url_foto, partido, estado, url_partido, url_estado = info
                    
                    # Validar se a frase realmente tem relação com o tema
                    # O LLM já foi instruído a selecionar apenas frases relevantes
                    # Mas vamos fazer uma validação adicional básica
                    relevancia = item.get('relevancia', '').lower()
                    frase_lower = frase_texto.lower()
                    tema_lower = tema.lower()
                    
                    # Verificar se a explicação de relevância indica que NÃO é relevante
                    palavras_negativas = ['não é relevante', 'não tem relação', 'não trata', 'não relacionado', 'não aborda']
                    if any(palavra in relevancia for palavra in palavras_negativas):
                        print(f"⚠️ Pulando frase do índice {indice} - LLM indicou que não é relevante")
                        continue
                    
                    # Se não há explicação de relevância, mas a frase contém palavras do tema, aceitar
                    # (o LLM pode ter esquecido de incluir a explicação)
                    if not relevancia and any(palavra in frase_lower for palavra in tema_lower.split()):
                        print(f"✅ Aceitando frase do índice {indice} - contém palavras do tema")
                    
                    frases_impactantes.append({
                        'parlamentar': discurso.get('Parlamentar', 'N/A'),
                        'partido': partido or 'N/A',
                        'estado': estado or 'N/A',
                        'foto': url_foto or '',
                        'logo_partido': url_partido or '',
                        'bandeira_estado': url_estado or '',
                        'frase': f'"{frase_texto}"',
                        'comissao': discurso.get('Comissao', 'N/A'),
                        'data': discurso.get('Data', 'N/A'),
                        'motivo': item.get('motivo', 'Selecionada pelo LLM'),
                        'relevancia': item.get('relevancia', 'Relevante ao tema')
                    })
                else:
                    print(f"⚠️ Informações do parlamentar não encontradas para: {discursos[indice].get('Parlamentar', 'N/A')}")
        
        conn_tabelao.close()
        
        print(f"✅ {len(frases_impactantes)} frases impactantes processadas")
        return frases_impactantes
        
    except Exception as e:
        print(f"Erro ao gerar frases impactantes: {e}")
        return []

def buscar_semantica_nova(tema: str, data_inicio: str, data_fim: str, discursos_db_path: str = None) -> Dict[str, Any]:
    """Função principal da busca semântica"""
    try:
        print(f"🔍 Iniciando busca semântica para: {tema}")
        
        # PASSO 1: Gerar palavras-chave
        print(f"📝 PASSO 1: Tema de busca: {tema}")
        palavras_chave = gerar_palavras_chave(tema)
        print(f"✅ Palavras-chave geradas: {palavras_chave}")
        
        # PASSO 2: Buscar discursos
        print(f"📚 PASSO 3: Buscando discursos...")
        discursos = buscar_discursos_com_palavras(palavras_chave, data_inicio, data_fim, discursos_db_path)
        print(f"✅ Encontrados {len(discursos)} discursos")
        
        if not discursos:
            return {
                'palavras_chave': palavras_chave,
                'estatisticas': {
                    'total_discursos': 0,
                    'discursos_relevantes': 0,
                    'parlamentares_envolvidos': 0,
                    'total_citacoes': 0
                },
                'relatorio': 'Nenhum discurso encontrado para o período selecionado.',
                'frases_impactantes': []
            }
        
        # PASSO 3: Validar discursos com LLM
        print(f"🤖 PASSO 4: Validando {len(discursos)} discursos com LLM...")
        discursos_validados = validar_discursos_llm(discursos, tema)
        print(f"✅ {len(discursos_validados)} discursos validados pelo LLM")
        
        # PASSO 4: Gerar relatório
        print(f"📋 PASSO 6: Gerando relatório...")
        print(f"📝 Escrevendo introdução...")
        relatorio = gerar_relatorio_llm(discursos_validados, tema)
        print(f"✅ Relatório concluído!")
        
        # PASSO 5: Gerar frases impactantes (validando relevância ao tema)
        print(f"💬 Coletando frases impactantes relevantes ao tema...")
        frases_impactantes = gerar_frases_impactantes(discursos_validados, tema)
        print(f"✅ {len(frases_impactantes)} frases impactantes coletadas")
        
        # Calcular estatísticas finais
        parlamentares_unicos = set([d['Parlamentar'] for d in discursos_validados if d.get('Parlamentar')])
        estatisticas = {
            'total_discursos': len(discursos),
            'discursos_relevantes': len(discursos_validados),
            'parlamentares_envolvidos': len(parlamentares_unicos),
            'total_citacoes': 0  # Removido sistema de citações
        }
        
        print(f"📊 Estatísticas calculadas: {estatisticas}")
        
        return {
            'palavras_chave': palavras_chave,
            'estatisticas': estatisticas,
            'relatorio': relatorio,
            'frases_impactantes': frases_impactantes
        }
        
    except Exception as e:
        print(f"Erro na busca semântica: {e}")
        return {
            'error': str(e),
            'palavras_chave': [],
            'estatisticas': {},
            'relatorio': '',
            'frases_impactantes': []
        }

if __name__ == "__main__":
    # Teste
    resultado = buscar_semantica_nova("meio ambiente", "2025-08-01", "2025-10-23")
    print(f"Palavras-chave: {resultado['palavras_chave']}")
    print(f"Estatísticas: {resultado['estatisticas']}")
    print(f"Frases impactantes: {len(resultado['frases_impactantes'])}")









