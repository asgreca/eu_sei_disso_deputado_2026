import sqlite3
import time
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List

import pandas as pd
import requests
from dateutil.relativedelta import relativedelta
from tqdm import tqdm

# =============================================================================
# CONFIGURAÇÕES GERAIS
# =============================================================================

DATA_INICIO_GERAL = "2023-01-01"
DATA_FIM_GERAL = "2026-12-31"

BASE_DIR = Path(__file__).resolve().parent
TABELAO_DB_PATH = BASE_DIR / "tabelao.db"

# Se True, remove dados prévios antes do processamento,
# garantindo recomputação completa.
RESETAR_DADOS = False

# ID do tipo de evento para Sessão Deliberativa do Plenário
ID_EVENTO_PLENARIO = "10000"

# Delay entre requisições para evitar throttling
DELAY_ENTRE_REQUISICOES = 0.1

# User-Agent para evitar bloqueios
HTTP_HEADERS = {
    "User-Agent": "PresencaCamaraBot/1.0 (+https://github.com/aislangreca)"
}


# =============================================================================
# FUNÇÕES AUXILIARES
# =============================================================================

def fetch_json(url: str, params: Dict[str, str] | None = None) -> Dict:
    """Faz GET na API da Câmara com backoff simples."""
    tentativas = 0
    while tentativas < 3:
        try:
            response = requests.get(
                url, params=params, timeout=30, headers=HTTP_HEADERS
            )
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            tentativas += 1
            espera = 10 * tentativas
            print(f"⚠️  Erro em {url} ({exc}). Tentativa {tentativas}/3. Aguardando {espera}s…")
            time.sleep(espera)
    raise RuntimeError(f"Falha ao acessar {url} após 3 tentativas.")


def normalizar_texto(texto: str) -> str:
    if not texto:
        return ""
    texto = unicodedata.normalize("NFD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return texto.lower()


def get_todos_deputados() -> Dict[int, str]:
    """
    Retorna dicionário {id_deputado: nome} abrangendo titulares e suplentes.
    Fonte: CSV oficial de deputados filtrado para legislatura atual (57) e sem falecimento.
    """
    print("🔄 Carregando cadastro completo de deputados (titulares + suplentes)…")
    url_csv = "https://dadosabertos.camara.leg.br/arquivos/deputados/csv/deputados.csv"

    try:
        df = pd.read_csv(url_csv, sep=";", dtype=str)
    except Exception as exc:
        raise RuntimeError(f"Falha ao baixar CSV de deputados: {exc}") from exc

    df = df.rename(columns=str.strip)
    col_uri = next((c for c in df.columns if c.lower() == "uri"), None)
    col_nome = next((c for c in df.columns if c.lower() == "nome"), None)
    col_leg_ini = next((c for c in df.columns if "legislaturainicial" in c.lower()), None)
    col_leg_fim = next((c for c in df.columns if "legislaturafinal" in c.lower()), None)
    col_falecimento = next((c for c in df.columns if "falecimento" in c.lower()), None)

    if not all([col_uri, col_nome, col_leg_ini, col_leg_fim]):
        raise RuntimeError("Estrutura do CSV de deputados é diferente do esperado.")

    df['id_deputado'] = df[col_uri].astype(str).str.extract(r"/(\d+)$", expand=False)
    df['id_deputado'] = pd.to_numeric(df['id_deputado'], errors="coerce")

    df[col_leg_ini] = pd.to_numeric(df[col_leg_ini], errors="coerce")
    df[col_leg_fim] = pd.to_numeric(df[col_leg_fim], errors="coerce")
    df[col_leg_fim] = df[col_leg_fim].fillna(df[col_leg_ini])

    df_ativas = df[
        (df[col_leg_ini] <= 57)
        & (df[col_leg_fim] >= 57)
    ].copy()

    if col_falecimento:
        df_ativas = df_ativas[df_ativas[col_falecimento].isna()]

    df_ativas = df_ativas.dropna(subset=['id_deputado'])
    df_ativas['id_deputado'] = df_ativas['id_deputado'].astype(int)
    df_ativas[col_nome] = df_ativas[col_nome].astype(str).str.strip()

    deputados: Dict[int, str] = dict(zip(df_ativas['id_deputado'], df_ativas[col_nome]))
    print(f"✅ Deputados carregados: {len(deputados)} (CSV oficial)")
    return deputados


def get_comissoes_permanentes() -> Dict[int, str]:
    """Retorna dicionário {id_orgao: nome} para comissões permanentes."""
    print("🔄 Buscando comissões permanentes…")
    comissoes: Dict[int, str] = {}
    url = "https://dadosabertos.camara.leg.br/api/v2/orgaos"
    params = {"itens": 100}

    while url:
        dados = fetch_json(url, params=params)
        for orgao in dados.get("dados", []):
            if orgao.get("tipoOrgao") == "Comissão Permanente":
                comissoes[int(orgao["id"])] = orgao["nome"]

        link_next = next(
            (link["href"] for link in dados.get("links", []) if link.get("rel") == "next"),
            None,
        )
        url = link_next
        params = {}

    print(f"✅ Comissões permanentes carregadas: {len(comissoes)}")
    return comissoes


def get_comissoes_nao_permanentes() -> Dict[int, str]:
    """Retorna dicionário {id_orgao: nome} para comissões não permanentes."""
    print("🔄 Buscando comissões não permanentes…")
    comissoes: Dict[int, str] = {}
    url = "https://dadosabertos.camara.leg.br/api/v2/orgaos"
    params = {"itens": 100}

    while url:
        dados = fetch_json(url, params=params)
        for orgao in dados.get("dados", []):
            tipo_orgao = orgao.get("tipoOrgao", "")
            # Incluir comissões temporárias, especiais, etc.
            if "Comissão" in tipo_orgao and "Permanente" not in tipo_orgao:
                comissoes[int(orgao["id"])] = orgao["nome"]

        link_next = next(
            (link["href"] for link in dados.get("links", []) if link.get("rel") == "next"),
            None,
        )
        url = link_next
        params = {}

    print(f"✅ Comissões não permanentes carregadas: {len(comissoes)}")
    return comissoes


def get_todas_comissoes() -> Dict[int, tuple]:
    """Retorna dicionário {id_orgao: (nome, tipo_orgao)} para todas as comissões (permanentes e não permanentes)."""
    print("🔄 Buscando todas as comissões (permanentes e não permanentes)…")
    comissoes: Dict[int, tuple] = {}
    url = "https://dadosabertos.camara.leg.br/api/v2/orgaos"
    params = {"itens": 100}

    while url:
        dados = fetch_json(url, params=params)
        for orgao in dados.get("dados", []):
            tipo_orgao = orgao.get("tipoOrgao", "")
            # Incluir todas as comissões (permanentes e não permanentes)
            if "Comissão" in tipo_orgao:
                comissoes[int(orgao["id"])] = (orgao["nome"], tipo_orgao)

        link_next = next(
            (link["href"] for link in dados.get("links", []) if link.get("rel") == "next"),
            None,
        )
        url = link_next
        params = {}

    permanentes = sum(1 for _, (_, tipo) in comissoes.items() if "Permanente" in tipo)
    nao_permanentes = len(comissoes) - permanentes
    print(f"✅ Total de comissões carregadas: {len(comissoes)} ({permanentes} permanentes + {nao_permanentes} não permanentes)")
    return comissoes


def get_membros_comissao(id_orgao: int) -> List[int]:
    """Retorna lista de IDs de deputados que são membros da comissão."""
    membros: List[int] = []
    url = f"https://dadosabertos.camara.leg.br/api/v2/orgaos/{id_orgao}/membros"
    params = {"itens": 100}

    try:
        while url:
            dados = fetch_json(url, params=params)
            for membro in dados.get("dados", []):
                # A API retorna o ID do deputado no campo 'id'
                dep_id = membro.get("id")
                if dep_id:
                    try:
                        membros.append(int(dep_id))
                    except (TypeError, ValueError):
                        continue

            link_next = next(
                (link["href"] for link in dados.get("links", []) if link.get("rel") == "next"),
                None,
            )
            url = link_next
            params = {}
            time.sleep(DELAY_ENTRE_REQUISICOES)
    except RuntimeError:
        # Se falhar, retorna lista vazia (comissão sem membros ou erro)
        pass

    return membros


def carregar_membros_comissoes(comissoes: Dict[int, tuple]) -> Dict[int, List[int]]:
    """Carrega e retorna dicionário {id_orgao: [ids_deputados_membros]}."""
    print("🔄 Carregando membros das comissões…")
    membros_por_comissao: Dict[int, List[int]] = {}

    for id_orgao, (nome_orgao, _) in tqdm(comissoes.items(), desc="Comissões", ncols=90):
        membros = get_membros_comissao(id_orgao)
        membros_por_comissao[id_orgao] = membros
        print(f"  📋 {nome_orgao}: {len(membros)} membros")

    print(f"✅ Membros das comissões carregados")
    return membros_por_comissao


def get_ids_eventos_por_filtro(
    data_inicio: str,
    data_fim: str,
    id_orgao: int | None = None,
    id_tipo_evento: str | None = None,
) -> List[int]:
    """Busca IDs de eventos para um órgão ou tipo de evento em um período."""
    ids_eventos: List[int] = []

    url = "https://dadosabertos.camara.leg.br/api/v2/eventos"
    params = {
        "dataInicio": data_inicio,
        "dataFim": data_fim,
        "ordem": "ASC",
        "itens": 100,
    }

    if id_orgao is not None:
        params["idOrgao"] = id_orgao
    if id_tipo_evento is not None:
        params["tipoEvento"] = id_tipo_evento

    while url:
        try:
            dados = fetch_json(url, params=params)
        except RuntimeError:
            # Erro persistente: retornar o que já temos
            break

        for evento in dados.get("dados", []):
            ids_eventos.append(int(evento["id"]))

        link_next = next(
            (link["href"] for link in dados.get("links", []) if link.get("rel") == "next"),
            None,
        )
        url = link_next
        params = {}

    return ids_eventos


def get_eventos_plenario(data_inicio: str, data_fim: str) -> List[int]:
    """Busca eventos de plenário por período filtrando pela descrição."""
    ids_eventos: List[int] = []
    url = "https://dadosabertos.camara.leg.br/api/v2/eventos"
    params = {
        "dataInicio": data_inicio,
        "dataFim": data_fim,
        "ordem": "ASC",
        "itens": 100,
    }

    while url:
        try:
            dados = fetch_json(url, params=params)
        except RuntimeError as exc:
            print(f"⚠️  Falha ao buscar eventos do plenário ({exc}).")
            break

        for evento in dados.get("dados", []):
            descricao_tipo = normalizar_texto(evento.get("descricaoTipo"))
            local_exibe = normalizar_texto(evento.get("localExibicao") or "")
            tipo_evento = evento.get("tipoEvento", {})
            tipo_evento_id = str(tipo_evento.get("id", "")) if isinstance(tipo_evento, dict) else ""

            # Verificar se é evento de plenário
            is_plenario = (
                "plenario" in descricao_tipo
                or "plenaria" in descricao_tipo
                or "plenario" in local_exibe
                or tipo_evento_id == ID_EVENTO_PLENARIO
                or (descricao_tipo == "sessao deliberativa" and not local_exibe)  # Sessão Deliberativa sem local geralmente é plenário
            )

            if is_plenario:
                try:
                    ids_eventos.append(int(evento["id"]))
                except (TypeError, ValueError):
                    continue

        link_next = next(
            (link["href"] for link in dados.get("links", []) if link.get("rel") == "next"),
            None,
        )
        url = link_next
        params = {}
        time.sleep(0.1)

    return ids_eventos


def analisar_presenca_em_eventos(
    lista_deputados: Dict[int, str], ids_eventos: Iterable[int]
) -> Dict[int, int]:
    """Retorna {id_deputado: número de presenças} nos eventos informados."""
    presencas = {dep_id: 0 for dep_id in lista_deputados.keys()}

    for id_evento in ids_eventos:
        url_presenca = f"https://dadosabertos.camara.leg.br/api/v2/eventos/{id_evento}/deputados"
        try:
            dados = fetch_json(url_presenca)
        except RuntimeError:
            continue

        for dep_presente in dados.get("dados", []):
            dep_id = dep_presente.get("id")
            if dep_id in presencas:
                presencas[dep_id] += 1

        time.sleep(DELAY_ENTRE_REQUISICOES)

    return presencas


def init_db():
    """Cria as tabelas necessárias no tabelao.db (se o arquivo existir)."""
    if not TABELAO_DB_PATH.exists():
        print(f"⚠️  Banco '{TABELAO_DB_PATH}' não encontrado. A tabela será criada quando o DB existir.")
        return

    conn = sqlite3.connect(TABELAO_DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS presencas_eventos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            id_deputado INTEGER NOT NULL,
            nome_deputado TEXT NOT NULL,
            id_orgao TEXT NOT NULL,
            nome_orgao TEXT NOT NULL,
            tipo_orgao TEXT NOT NULL,
            mes_referencia TEXT NOT NULL,
            n_presencas INTEGER NOT NULL,
            n_total_reunioes INTEGER NOT NULL,
            data_processamento TEXT NOT NULL,
            UNIQUE(id_deputado, id_orgao, mes_referencia)
        )
        """
    )
    conn.commit()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS presencas_eventos_status (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            data_inicio TEXT NOT NULL,
            data_fim TEXT NOT NULL,
            ultima_execucao TEXT,
            ultimo_mes_processado TEXT
        )
        """
    )
    conn.commit()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS membros_comissoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            id_orgao INTEGER NOT NULL,
            nome_orgao TEXT NOT NULL,
            id_deputado INTEGER NOT NULL,
            nome_deputado TEXT NOT NULL,
            data_atualizacao TEXT NOT NULL,
            UNIQUE(id_orgao, id_deputado)
        )
        """
    )
    conn.commit()

    cur.execute(
        """
        INSERT OR IGNORE INTO presencas_eventos_status
            (id, data_inicio, data_fim, ultima_execucao, ultimo_mes_processado)
        VALUES (1, ?, ?, NULL, NULL)
        """,
        (DATA_INICIO_GERAL, DATA_FIM_GERAL),
    )
    conn.commit()
    conn.close()


def salvar_mes_no_db(df_mes: pd.DataFrame, mes_referencia: str):
    """Salva/atualiza informações do mês no banco tabelao.db."""
    if df_mes.empty or not TABELAO_DB_PATH.exists():
        return

    conn = sqlite3.connect(TABELAO_DB_PATH)
    cur = conn.cursor()
    registros = [
        (
            int(row["ID Deputado"]),
            row["Nome Deputado"],
            str(row["ID Orgao"]),
            row["Nome Orgao"],
            row["Tipo Orgao"],
            mes_referencia,
            int(row["N Presencas"]),
            int(row["N Total Reunioes"]),
            datetime.utcnow().isoformat(timespec="seconds"),
        )
        for _, row in df_mes.iterrows()
    ]

    cur.executemany(
        """
        INSERT INTO presencas_eventos (
            id_deputado, nome_deputado, id_orgao, nome_orgao, tipo_orgao,
            mes_referencia, n_presencas, n_total_reunioes, data_processamento
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id_deputado, id_orgao, mes_referencia) DO UPDATE SET
            nome_deputado = excluded.nome_deputado,
            nome_orgao = excluded.nome_orgao,
            tipo_orgao = excluded.tipo_orgao,
            n_presencas = excluded.n_presencas,
            n_total_reunioes = excluded.n_total_reunioes,
            data_processamento = excluded.data_processamento
        """,
        registros,
    )
    conn.commit()
    conn.close()


def obter_status_execucao() -> Dict[str, str | None]:
    if not TABELAO_DB_PATH.exists():
        return {
            "data_inicio": DATA_INICIO_GERAL,
            "data_fim": DATA_FIM_GERAL,
            "ultima_execucao": None,
            "ultimo_mes_processado": None,
        }

    conn = sqlite3.connect(TABELAO_DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT data_inicio, data_fim, ultima_execucao, ultimo_mes_processado
        FROM presencas_eventos_status
        WHERE id = 1
        """
    )
    row = cur.fetchone()
    conn.close()
    if not row:
        return {
            "data_inicio": DATA_INICIO_GERAL,
            "data_fim": DATA_FIM_GERAL,
            "ultima_execucao": None,
            "ultimo_mes_processado": None,
        }
    return {
        "data_inicio": row[0],
        "data_fim": row[1],
        "ultima_execucao": row[2],
        "ultimo_mes_processado": row[3],
    }


def atualizar_status_execucao(ultimo_mes: str):
    if not TABELAO_DB_PATH.exists():
        return
    conn = sqlite3.connect(TABELAO_DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE presencas_eventos_status
        SET ultima_execucao = ?, ultimo_mes_processado = ?
        WHERE id = 1
        """,
        (datetime.utcnow().isoformat(timespec="seconds"), ultimo_mes),
    )
    conn.commit()
    conn.close()


def salvar_membros_comissoes(membros_por_comissao: Dict[int, List[int]], comissoes: Dict[int, tuple], deputados: Dict[int, str]):
    """Salva/atualiza informações de membros das comissões no banco."""
    if not TABELAO_DB_PATH.exists():
        return

    conn = sqlite3.connect(TABELAO_DB_PATH)
    cur = conn.cursor()
    registros = []

    for id_orgao, membros_ids in membros_por_comissao.items():
        nome_orgao = comissoes.get(id_orgao, ("Desconhecida", ""))[0]
        for dep_id in membros_ids:
            nome_dep = deputados.get(dep_id, "Desconhecido")
            registros.append((
                int(id_orgao),
                nome_orgao,
                int(dep_id),
                nome_dep,
                datetime.utcnow().isoformat(timespec="seconds"),
            ))

    if registros:
        cur.executemany(
            """
            INSERT INTO membros_comissoes (
                id_orgao, nome_orgao, id_deputado, nome_deputado, data_atualizacao
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(id_orgao, id_deputado) DO UPDATE SET
                nome_orgao = excluded.nome_orgao,
                nome_deputado = excluded.nome_deputado,
                data_atualizacao = excluded.data_atualizacao
            """,
            registros,
        )
        conn.commit()
        print(f"✅ {len(registros)} registros de membros salvos/atualizados no banco.")

    conn.close()


def carregar_membros_comissoes_db() -> Dict[int, List[int]]:
    """Carrega membros das comissões do banco de dados."""
    if not TABELAO_DB_PATH.exists():
        return {}

    conn = sqlite3.connect(TABELAO_DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT id_orgao, id_deputado FROM membros_comissoes")
    rows = cur.fetchall()
    conn.close()

    membros_por_comissao: Dict[int, List[int]] = {}
    for id_orgao, id_deputado in rows:
        if id_orgao not in membros_por_comissao:
            membros_por_comissao[id_orgao] = []
        membros_por_comissao[id_orgao].append(id_deputado)

    return membros_por_comissao


def resetar_presencas():
    """Remove dados prévios para reprocessar do zero."""
    if not TABELAO_DB_PATH.exists():
        return

    conn = sqlite3.connect(TABELAO_DB_PATH)
    cur = conn.cursor()
    print("🧹 Limpando dados anteriores de presenças…")
    cur.execute("DELETE FROM presencas_eventos")
    cur.execute(
        """
        UPDATE presencas_eventos_status
        SET ultima_execucao = NULL,
            ultimo_mes_processado = NULL
        WHERE id = 1
        """
    )
    conn.commit()
    conn.close()


# =============================================================================
# LÓGICA PRINCIPAL
# =============================================================================

def processar_presencas():
    init_db()

    if RESETAR_DADOS:
        resetar_presencas()

    deputados = get_todos_deputados()
    comissoes = get_todas_comissoes()  # Agora inclui permanentes e não permanentes

    # Carregar membros das comissões (da API ou do banco)
    print("\n🔄 Verificando membros das comissões…")
    membros_por_comissao = carregar_membros_comissoes_db()
    
    # Se não há dados no banco ou RESETAR_DADOS, buscar da API
    if not membros_por_comissao or RESETAR_DADOS:
        print("📡 Buscando membros das comissões da API…")
        membros_por_comissao = carregar_membros_comissoes(comissoes)
        salvar_membros_comissoes(membros_por_comissao, comissoes, deputados)
    else:
        print(f"✅ Membros das comissões carregados do banco ({len(membros_por_comissao)} comissões)")
        # Verificar se há novas comissões que não estão no banco
        comissoes_no_banco = set(membros_por_comissao.keys())
        comissoes_novas = {k: v for k, v in comissoes.items() if k not in comissoes_no_banco}
        if comissoes_novas:
            print(f"📡 Encontradas {len(comissoes_novas)} novas comissões. Buscando membros…")
            membros_novas = carregar_membros_comissoes(comissoes_novas)
            membros_por_comissao.update(membros_novas)
            salvar_membros_comissoes(membros_novas, comissoes_novas, deputados)

    # Converter para formato {id_orgao: nome} para compatibilidade
    orgaos_analise: Dict[str, str] = {str(k): v[0] for k, v in comissoes.items()}
    orgaos_analise["0"] = "Plenário"
    
    # Criar dicionário de tipos de órgão para uso posterior
    tipos_orgao: Dict[int, str] = {k: v[1] for k, v in comissoes.items()}

    status_execucao = obter_status_execucao()

    try:
        data_inicial = datetime.strptime(DATA_INICIO_GERAL, "%Y-%m-%d")
    except ValueError:
        data_inicial = datetime(2023, 1, 1)

    ultimo_mes_status = status_execucao.get("ultimo_mes_processado")
    if ultimo_mes_status:
        try:
            data_inicial = datetime.strptime(ultimo_mes_status + "-01", "%Y-%m-%d")
        except ValueError:
            pass
        else:
            data_inicial += relativedelta(months=1)

    data_atual = data_inicial
    data_fim = datetime.strptime(DATA_FIM_GERAL, "%Y-%m-%d")
    hoje = datetime.now()

    ultimo_mes_processado = ultimo_mes_status

    while data_atual <= data_fim:
        ano_mes_str = data_atual.strftime("%Y-%m")
        print(f"\n📅 Processando mês {ano_mes_str}…")

        if (data_atual.year, data_atual.month) > (hoje.year, hoje.month):
            print("⏹️  Mês no futuro detectado. Encerrando processamento.")
            break

        inicio_mes = data_atual.strftime("%Y-%m-%d")
        fim_mes = (data_atual + relativedelta(months=1) - relativedelta(days=1)).strftime(
            "%Y-%m-%d"
        )

        resultados_mes: List[Dict] = []

        for id_orgao, nome_orgao in tqdm(
            orgaos_analise.items(), desc=f"Órgãos {ano_mes_str}", ncols=90
        ):
            if id_orgao == "0":
                ids_eventos = get_eventos_plenario(inicio_mes, fim_mes)
                tipo_orgao = "Plenário"
                if ids_eventos:
                    print(f"  🏛️  Plenário: {len(ids_eventos)} eventos encontrados para {ano_mes_str}")
                else:
                    print(f"  ⚠️  Plenário: Nenhum evento encontrado para {ano_mes_str}")
            else:
                ids_eventos = get_ids_eventos_por_filtro(
                    inicio_mes, fim_mes, id_orgao=int(id_orgao)
                )
                # Determinar tipo baseado no tipoOrgao da API
                id_orgao_int = int(id_orgao)
                tipo_orgao_api = tipos_orgao.get(id_orgao_int, "")
                if "Permanente" in tipo_orgao_api:
                    tipo_orgao = "Comissão Permanente"
                else:
                    tipo_orgao = "Comissão Não Permanente"

            total_reunioes = len(ids_eventos)
            if total_reunioes == 0:
                continue

            # Para Plenário, todos os deputados podem participar
            # Para Comissões, apenas os membros
            if id_orgao == "0":
                deputados_analise = deputados
            else:
                id_orgao_int = int(id_orgao)
                membros_ids = membros_por_comissao.get(id_orgao_int, [])
                deputados_analise = {dep_id: nome for dep_id, nome in deputados.items() if dep_id in membros_ids}
                
                if not deputados_analise:
                    print(f"  ⚠️  Nenhum membro encontrado para {nome_orgao}. Pulando…")
                    continue

            presencas = analisar_presenca_em_eventos(deputados_analise, ids_eventos)

            for dep_id, nome_dep in deputados_analise.items():
                resultados_mes.append(
                    {
                        "ID Deputado": dep_id,
                        "Nome Deputado": nome_dep,
                        "ID Orgao": id_orgao,
                        "Nome Orgao": nome_orgao,
                        "Tipo Orgao": tipo_orgao,
                        "Mes Referencia": ano_mes_str,
                        "N Presencas": presencas.get(dep_id, 0),
                        "N Total Reunioes": total_reunioes,
                    }
                )

        if resultados_mes:
            df_mes = pd.DataFrame(resultados_mes)
            salvar_mes_no_db(df_mes, ano_mes_str)
            print(f"✅ Registros de {ano_mes_str} gravados/atualizados no banco.")
            ultimo_mes_processado = ano_mes_str
        else:
            print(f"ℹ️  Nenhuma atividade registrada em {ano_mes_str}.")

        data_atual += relativedelta(months=1)

    atualizar_status_execucao(ultimo_mes_processado or DATA_INICIO_GERAL[:7])
    print("\n🎯 Processamento concluído. Status de execução atualizado.")

    if not TABELAO_DB_PATH.exists():
        return

    conn = sqlite3.connect(TABELAO_DB_PATH)
    df_plenario = pd.read_sql_query(
        """
        SELECT id_deputado, nome_deputado, mes_referencia, n_presencas, n_total_reunioes
        FROM presencas_eventos
        WHERE tipo_orgao = 'Plenário'
        """,
        conn,
    )
    conn.close()

    if df_plenario.empty:
        print("ℹ️  Nenhum registro de Plenário disponível para estatísticas.")
    else:
        freq_plenario = (
            df_plenario.groupby(["id_deputado", "nome_deputado"])[
                ["n_presencas", "n_total_reunioes"]
            ]
            .sum()
            .assign(
                frequencia=lambda df: (
                    df["n_presencas"] / df["n_total_reunioes"]
                )
                .replace([float("inf"), -float("inf")], 0)
                .fillna(0)
                * 100
            )
            .sort_values("frequencia", ascending=False)
        )

        print("\n🏛️  Top 10 presença no Plenário (frequência %):")
        print(freq_plenario.head(10).round(2))


if __name__ == "__main__":
    processar_presencas()