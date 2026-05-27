"""
Script de Sincronização Inteligente de Bancos de Dados para o Servidor
Usa fabric (SSH + SFTP) para enviar arquivos com autenticação automática
"""
import os
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
from fabric import Connection
from invoke import Responder

class SyncBancosServidor:
    def __init__(self):
        # Carregar configurações do .env
        load_dotenv()
        
        self.host = os.getenv("REMOTE_DB_HOST", "31.97.21.120")
        self.user = os.getenv("REMOTE_DB_USER", "aislangreca")
        self.password = os.getenv("REMOTE_DB_PASSWORD", "Biriquitote2000")
        self.pasta_remota = "/home/aislangreca/bancos_dados"
        self.base_local = "/Users/aislangreca/Library/Mobile Documents/com~apple~CloudDocs/Projetos_dados/acompanhamento_camara/dash2"
        
        # Criar conexão SSH
        self.conn = None
        
        # Bancos de dados - Atualização por frequência
        self.bancos_criticos = [
            # Atualizados frequentemente (diário)
            "discursos_links.db",
            "noticias_parlamentares.db",
            "data/badges.json",
            "data/home_stats.json",
        ]
        
        self.bancos_regulares = [
            # Atualizados regularmente (semanal)
            "discursos.db",
            "cache_normalizacao_citacoes_integrados.db",
        ]
        
        self.bancos_estáveis = [
            # Atualizam raramente (mensal ou quando necessário)
            # IMPORTANTE: tabelao.db agora contém a tabela cache_llm_relatorios (cache centralizado)
            "tabelao.db",  # Contém cache_llm_relatorios para todos os relatórios LLM
            "llm_cache.db",  # Mantido para compatibilidade se necessário
        ]
        
        # Bancos especiais (arquivos DuckDB ou outros formatos)
        self.bancos_especiais = [
            # Bancos em formatos especiais ou localizações específicas
            "mapa/votacao.duckdb",  # Usado para mapa eleitoral
        ]
    
    def verificar_arquivo_mudou(self, arquivo):
        """Verifica quando o arquivo foi modificado pela última vez"""
        caminho = os.path.join(self.base_local, arquivo)
        if not os.path.exists(caminho):
            return False, None
        
        timestamp = os.path.getmtime(caminho)
        data_modificacao = datetime.fromtimestamp(timestamp)
        return True, data_modificacao
    
    def conectar(self):
        """Estabelece conexão SSH"""
        if self.conn is None:
            try:
                print(f"🔗 Conectando a {self.host}...")
                self.conn = Connection(
                    host=self.host,
                    user=self.user,
                    connect_kwargs={"password": self.password}
                )
                # Testar conexão
                self.conn.run('echo "Conexão OK"', hide=True)
                print(f"✅ Conectado a {self.host}")
                return True
            except Exception as e:
                print(f"❌ Erro ao conectar: {e}")
                return False
        return True
    
    def criar_tabela_cache_llm_no_servidor(self):
        """Cria a tabela cache_llm_relatorios no tabelao.db do servidor se não existir
        Usa Python no servidor para criar a tabela (não requer sqlite3 CLI)
        """
        if not self.conectar():
            return False
        
        try:
            caminho_remoto = f"{self.pasta_remota}/tabelao.db"
            
            # Verificar se o arquivo existe no servidor
            result = self.conn.run(f'test -f {caminho_remoto} && echo "existe" || echo "nao_existe"', hide=True)
            if "nao_existe" in result.stdout:
                print(f"⚠️  tabelao.db não existe no servidor. Será criado na próxima sincronização.")
                return True
            
            # Verificar se a tabela existe usando Python no servidor
            print(f"🔍 Verificando se tabela cache_llm_relatorios existe no servidor...")
            
            # Script Python para verificar e criar a tabela
            # Usar string SQL em uma linha para evitar conflito com f-string multi-linha
            create_table_sql = "CREATE TABLE IF NOT EXISTS cache_llm_relatorios (hash_key TEXT PRIMARY KEY, tipo_relatorio TEXT NOT NULL, parametros TEXT NOT NULL, resultado TEXT NOT NULL, data_criacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP, data_atualizacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
            
            python_script = f'''
import sqlite3
import sys

db_path = "{caminho_remoto}"
try:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Verificar se a tabela existe
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='cache_llm_relatorios';")
    tabela_existe = cursor.fetchone() is not None
    
    if not tabela_existe:
        # Criar a tabela
        cursor.execute("{create_table_sql}")
        conn.commit()
        print("TABELA_CRIADA")
    else:
        print("TABELA_EXISTE")
    
    conn.close()
    sys.exit(0)
except Exception as e:
    print(f"ERRO: {{e}}")
    sys.exit(1)
'''
            
            # Executar script Python no servidor
            result = self.conn.run(f'python3 -c {repr(python_script)}', hide=True, warn=True)
            
            if "TABELA_CRIADA" in result.stdout:
                print(f"✅ Tabela cache_llm_relatorios criada com sucesso no servidor!")
            elif "TABELA_EXISTE" in result.stdout:
                print(f"✅ Tabela cache_llm_relatorios já existe no servidor.")
            elif "ERRO" in result.stdout:
                print(f"⚠️  Erro ao criar tabela: {result.stdout}")
                return False
            else:
                # Tentar com python ao invés de python3
                result = self.conn.run(f'python -c {repr(python_script)}', hide=True, warn=True)
                if "TABELA_CRIADA" in result.stdout:
                    print(f"✅ Tabela cache_llm_relatorios criada com sucesso no servidor!")
                elif "TABELA_EXISTE" in result.stdout:
                    print(f"✅ Tabela cache_llm_relatorios já existe no servidor.")
                else:
                    print(f"⚠️  Não foi possível verificar/criar tabela. Output: {result.stdout}")
                    return False
            
            return True
            
        except Exception as e:
            print(f"⚠️  Erro ao verificar/criar tabela no servidor: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def sincronizar_arquivo(self, arquivo, caminho_completo=None, mostrar_progresso=True):
        """Sincroniza um arquivo usando SFTP (envia arquivo completo via SSH)
        
        Args:
            arquivo: Nome do arquivo ou caminho relativo
            caminho_completo: Caminho completo local (opcional, para arquivos em subdiretórios)
            mostrar_progresso: Se deve mostrar progresso
        """
        # Determinar caminho local
        if caminho_completo:
            caminho_local = caminho_completo
        else:
            caminho_local = os.path.join(self.base_local, arquivo)
        
        # Verificar se arquivo existe
        if not os.path.exists(caminho_local):
            print(f"⚠️  {arquivo} não encontrado em {caminho_local}. Pulando...")
            return False
        
        # Verificar data de modificação
        existe, data_mod = self.verificar_arquivo_mudou(arquivo if not caminho_completo else os.path.basename(caminho_local))
        if not existe or data_mod is None:
            # Tentar obter data de modificação diretamente do caminho
            try:
                timestamp = os.path.getmtime(caminho_local)
                data_mod = datetime.fromtimestamp(timestamp)
            except:
                print(f"⚠️  {arquivo} não pôde ser verificado. Pulando...")
                return False
        
        # Determinar caminho remoto (preservar estrutura de diretórios se necessário)
        if '/' in arquivo:
            # Arquivo está em subdiretório
            caminho_remoto = f"{self.pasta_remota}/{arquivo}"
            # Garantir que o diretório existe no servidor
            diretorio_remoto = os.path.dirname(caminho_remoto)
        else:
            # Arquivo está na raiz
            caminho_remoto = f"{self.pasta_remota}/{arquivo}"
            diretorio_remoto = self.pasta_remota
        
        tamanho = os.path.getsize(caminho_local) / (1024 * 1024)  # MB
        print(f"\n📤 Enviando {arquivo}")
        print(f"   Tamanho: {tamanho:.2f} MB")
        print(f"   Última modificação: {data_mod.strftime('%d/%m/%Y %H:%M:%S')}")
        
        # Conectar se necessário
        if not self.conectar():
            return False
        
        try:
            # Garantir que o diretório existe no servidor
            if '/' in arquivo:
                self.conn.run(f'mkdir -p {diretorio_remoto}', hide=True)
            
            # Usar fabric put para transferir arquivo
            print(f"   Transferindo...")
            self.conn.put(caminho_local, caminho_remoto)
            print(f"✅ {arquivo} sincronizado com sucesso!")
            
            # Se for tabelao.db, garantir que a tabela cache_llm_relatorios existe
            if arquivo == "tabelao.db" or arquivo.endswith("/tabelao.db"):
                self.criar_tabela_cache_llm_no_servidor()
            
            return True
                
        except Exception as e:
            print(f"❌ Erro ao sincronizar {arquivo}: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def sincronizar_grupo(self, titulo, arquivos, mostrar_progresso=True):
        """Sincroniza um grupo de arquivos"""
        print("\n" + "="*70)
        print(f"📊 {titulo}")
        print("="*70)
        
        sucessos = 0
        falhas = 0
        
        for arquivo in arquivos:
            if self.sincronizar_arquivo(arquivo, mostrar_progresso=mostrar_progresso):
                sucessos += 1
            else:
                falhas += 1
        
        print(f"\n{titulo}: {sucessos} sincronizados, {falhas} falharam")
        return sucessos, falhas
    
    def fechar_conexao(self):
        """Fecha a conexão SSH"""
        if self.conn:
            try:
                self.conn.close()
                print("🔌 Conexão fechada")
            except:
                pass
    
    def sincronizar_tudo(self, incluir_estaveis=False):
        """Sincroniza todos os bancos (ou apenas os que mudam frequentemente)"""
        print("\n" + "="*70)
        print("🚀 SINCRONIZAÇÃO INTELIGENTE DE BANCOS DE DADOS")
        print(f"🖥️  Servidor: {self.user}@{self.host}")
        print(f"📁 Pasta remota: {self.pasta_remota}")
        print(f"⏰ Início: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
        print("="*70)
        
        total_ok = 0
        total_fail = 0
        
        # Sincronizar bancos críticos (sempre)
        ok, fail = self.sincronizar_grupo(
            "BANCOS CRÍTICOS (Atualizados Diariamente)",
            self.bancos_criticos
        )
        total_ok += ok
        total_fail += fail
        
        # Sincronizar bancos regulares (sempre)
        ok, fail = self.sincronizar_grupo(
            "BANCOS REGULARES (Atualizados Semanalmente)",
            self.bancos_regulares
        )
        total_ok += ok
        total_fail += fail
        
        # Sincronizar bancos estáveis (opcional)
        if incluir_estaveis:
            ok, fail = self.sincronizar_grupo(
                "BANCOS ESTÁVEIS (Atualizados Raramente)",
                self.bancos_estáveis
            )
            total_ok += ok
            total_fail += fail
            
            # Sincronizar bancos especiais (se houver)
            if self.bancos_especiais:
                for arquivo_especial in self.bancos_especiais:
                    # Arquivos especiais podem estar em subdiretórios
                    if '/' in arquivo_especial:
                        caminho_completo = os.path.join(self.base_local, arquivo_especial)
                        if os.path.exists(caminho_completo):
                            if self.sincronizar_arquivo(arquivo_especial, caminho_completo=caminho_completo):
                                total_ok += 1
                            else:
                                total_fail += 1
                        else:
                            print(f"⚠️  {arquivo_especial} não encontrado localmente. Pulando...")
                            total_fail += 1
        else:
            print("\n" + "="*70)
            print("⏭️  PULANDO BANCOS ESTÁVEIS (use --completo para incluir)")
            print("="*70)
        
        # Garantir que tabelas necessárias existem no servidor
        print("\n" + "="*70)
        print("🔧 VERIFICANDO E CRIANDO TABELAS NO SERVIDOR")
        print("="*70)
        # A tabela será criada automaticamente quando tabelao.db for sincronizado
        # Mas vamos garantir que existe se tabelao.db já estiver no servidor
        if incluir_estaveis and "tabelao.db" in self.bancos_estáveis:
            # Tentar criar a tabela mesmo se não sincronizamos agora
            self.criar_tabela_cache_llm_no_servidor()
        
        # Verificar espaço no servidor
        self.verificar_espaco_servidor()
        
        # Resumo
        print("\n" + "="*70)
        print("🏁 SINCRONIZAÇÃO CONCLUÍDA!")
        print(f"⏰ Fim: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
        print("="*70)
        print(f"✅ Arquivos sincronizados: {total_ok}")
        print(f"❌ Arquivos com falha: {total_fail}")
        
        if total_fail == 0:
            print("\n🎉 Todos os arquivos foram sincronizados com sucesso!")
        else:
            print("\n⚠️  Alguns arquivos não foram sincronizados. Verifique os erros acima.")
        
        # Fechar conexão
        self.fechar_conexao()
    
    def verificar_espaco_servidor(self):
        """Verifica o espaço em disco no servidor"""
        print("\n" + "="*70)
        print("💾 VERIFICANDO ESPAÇO NO SERVIDOR")
        print("="*70)
        
        if not self.conectar():
            return
        
        try:
            result = self.conn.run(f'df -h {self.pasta_remota}', hide=True)
            print(result.stdout)
        except Exception as e:
            print(f"⚠️  Não foi possível verificar espaço: {e}")
    
    def baixar_arquivo(self, arquivo, mostrar_progresso=True):
        """Baixa um arquivo do servidor para a máquina local"""
        caminho_remoto = f"{self.pasta_remota}/{arquivo}"
        caminho_local = os.path.join(self.base_local, arquivo)
        
        # Garantir diretório local
        os.makedirs(os.path.dirname(caminho_local), exist_ok=True)
        
        print(f"\n📥 Baixando {arquivo} do servidor...")
        
        if not self.conectar():
            return False
            
        try:
            # Verificar se arquivo existe no servidor
            result = self.conn.run(f'test -f {caminho_remoto} && echo "existe" || echo "nao_existe"', hide=True)
            if "nao_existe" in result.stdout:
                print(f"⚠️  Arquivo {arquivo} não encontrado no servidor.")
                return False
            
            self.conn.get(caminho_remoto, caminho_local)
            print(f"✅ {arquivo} baixado com sucesso!")
            return True
        except Exception as e:
            print(f"❌ Erro ao baixar {arquivo}: {e}")
            return False

    def baixar_tudo(self):
        """Baixa todos os bancos do servidor para o local"""
        print("\n" + "="*70)
        print("📥 DOWNLOAD DE DADOS DO SERVIDOR")
        print("="*70)
        
        todos_bancos = self.bancos_criticos + self.bancos_regulares + self.bancos_estáveis
        # Adicionar badges e home_stats se não estiverem
        extras = ["data/badges.json", "data/home_stats.json"]
        for extra in extras:
            if extra not in todos_bancos:
                todos_bancos.append(extra)
        
        sucessos = 0
        for banco in todos_bancos:
            if self.baixar_arquivo(banco):
                sucessos += 1
                
        print(f"\n✅ Download concluído: {sucessos} arquivos atualizados.")
        self.fechar_conexao()

if __name__ == "__main__":
    import sys
    
    print("="*70)
    print("🔄 SINCRONIZAÇÃO INTELIGENTE DE BANCOS DE DADOS")
    print("="*70)
    print("Este script usa rsync para enviar apenas as mudanças,")
    print("economizando tempo e largura de banda.")
    print("="*70)
    
    sync = SyncBancosServidor()
    
    # Verificar argumentos
    if len(sys.argv) > 1:
        if sys.argv[1] == "--completo":
            print("\n🔄 Modo: SINCRONIZAÇÃO COMPLETA (incluindo bancos estáveis)")
            sync.sincronizar_tudo(incluir_estaveis=True)
        elif sys.argv[1] == "--baixar":
            print("\n📥 Modo: BAIXAR DO SERVIDOR (Download)")
            sync.baixar_tudo()
        elif sys.argv[1] == "--help":
            print("\nUso:")
            print("  python sync_bancos_servidor.py              # Envia bancos locais para o servidor")
            print("  python sync_bancos_servidor.py --baixar     # Baixa bancos do servidor para local")
            print("  python sync_bancos_servidor.py --completo   # Envia TODOS os bancos")
            print("  python sync_bancos_servidor.py <arquivo>    # Sincroniza apenas um arquivo")
        else:
            # Sincronizar arquivo específico
            arquivo = sys.argv[1]
            sync.sincronizar_arquivo(arquivo)
    else:
        print("\n🔄 Modo: SINCRONIZAÇÃO RÁPIDA (apenas bancos que mudam frequentemente)")
        print("💡 Use --completo para incluir todos os bancos")
        print("💡 Use --baixar para trazer dados do servidor")
        sync.sincronizar_tudo(incluir_estaveis=False)

