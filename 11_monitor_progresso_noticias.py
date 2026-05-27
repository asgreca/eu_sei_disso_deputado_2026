#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Monitor de Progresso do Coletor de Notícias
Permite visualizar o progresso, gerar relatórios e gerenciar o processamento.
"""

import sqlite3
import json
from datetime import datetime, date
from tabulate import tabulate

class MonitorProgressoNoticias:
    def __init__(self):
        self.DB_TABELAO = "/Users/aislangreca/TCC/tabelao.db"
        self.DB_NOTICIAS = "/Users/aislangreca/TCC/noticias_parlamentares.db"
        self.conn_tabelao = None
        self.conn_noticias = None
    
    def conectar_bancos(self):
        """Conecta aos bancos de dados."""
        self.conn_tabelao = sqlite3.connect(self.DB_TABELAO)
        self.conn_noticias = sqlite3.connect(self.DB_NOTICIAS)
        print("✅ Conexões estabelecidas")
    
    def obter_estatisticas_gerais(self):
        """Obtém estatísticas gerais do processamento."""
        cursor = self.conn_noticias.cursor()
        
        # Total de notícias
        cursor.execute("SELECT COUNT(*) FROM noticias")
        total_noticias = cursor.fetchone()[0]
        
        # Total de parlamentares com notícias
        cursor.execute("SELECT COUNT(DISTINCT parlamentar_id) FROM noticias")
        parlamentares_com_noticias = cursor.fetchone()[0]
        
        # Total de parlamentares no tabelao (Legislatura 57)
        cursor_tabelao = self.conn_tabelao.cursor()
        cursor_tabelao.execute("SELECT COUNT(DISTINCT id) FROM tabelao WHERE ultimoStatus_idLegislatura = 57")
        total_parlamentares = cursor_tabelao.fetchone()[0]
        
        # Meses processados
        cursor.execute("SELECT COUNT(*) FROM progresso_mensal WHERE status = 'concluido'")
        meses_concluidos = cursor.fetchone()[0]
        
        # Meses em andamento
        cursor.execute("SELECT COUNT(*) FROM progresso_mensal WHERE status = 'em_andamento'")
        meses_em_andamento = cursor.fetchone()[0]
        
        # Data da última coleta
        cursor.execute("SELECT MAX(data_coleta) FROM noticias")
        ultima_coleta = cursor.fetchone()[0]
        
        return {
            'total_noticias': total_noticias,
            'parlamentares_com_noticias': parlamentares_com_noticias,
            'total_parlamentares': total_parlamentares,
            'meses_concluidos': meses_concluidos,
            'meses_em_andamento': meses_em_andamento,
            'ultima_coleta': ultima_coleta
        }
    
    def obter_progresso_por_parlamentar(self, limite=20):
        """Obtém progresso detalhado por parlamentar."""
        cursor = self.conn_noticias.cursor()
        
        cursor.execute("""
            SELECT 
                p.parlamentar_nome,
                COUNT(DISTINCT p.mes_ano) as meses_processados,
                COUNT(n.id) as total_noticias,
                MAX(p.data_fim) as ultima_atualizacao
            FROM progresso_mensal p
            LEFT JOIN noticias n ON p.parlamentar_id = n.parlamentar_id
            GROUP BY p.parlamentar_id, p.parlamentar_nome
            ORDER BY total_noticias DESC
            LIMIT ?
        """, (limite,))
        
        return cursor.fetchall()
    
    def obter_progresso_por_mes(self):
        """Obtém progresso por mês/ano."""
        cursor = self.conn_noticias.cursor()
        
        cursor.execute("""
            SELECT 
                p.mes_ano,
                COUNT(DISTINCT p.parlamentar_id) as parlamentares_processados,
                COUNT(n.id) as total_noticias,
                SUM(CASE WHEN p.status = 'concluido' THEN 1 ELSE 0 END) as concluidos,
                SUM(CASE WHEN p.status = 'em_andamento' THEN 1 ELSE 0 END) as em_andamento
            FROM progresso_mensal p
            LEFT JOIN noticias n ON p.parlamentar_id = n.parlamentar_id AND p.mes_ano = n.mes_ano
            GROUP BY p.mes_ano
            ORDER BY p.mes_ano
        """)
        
        return cursor.fetchall()
    
    def obter_top_categorias(self, limite=10):
        """Obtém as categorias mais frequentes."""
        cursor = self.conn_noticias.cursor()
        
        cursor.execute("""
            SELECT categoria, COUNT(*) as total
            FROM noticias
            GROUP BY categoria
            ORDER BY total DESC
            LIMIT ?
        """, (limite,))
        
        return cursor.fetchall()
    
    def obter_top_veiculos(self, limite=10):
        """Obtém os veículos com mais notícias."""
        cursor = self.conn_noticias.cursor()
        
        cursor.execute("""
            SELECT veiculo, COUNT(*) as total
            FROM noticias
            WHERE veiculo IS NOT NULL AND veiculo != ''
            GROUP BY veiculo
            ORDER BY total DESC
            LIMIT ?
        """, (limite,))
        
        return cursor.fetchall()
    
    def obter_parlamentares_sem_noticias(self):
        """Obtém parlamentares que ainda não têm notícias."""
        cursor = self.conn_noticias.cursor()
        
        # Como as tabelas estão em bancos diferentes, precisamos do ATTACH
        cursor.execute(f"ATTACH DATABASE '{self.DB_TABELAO}' AS db_tabelao")
        
        cursor.execute("""
            SELECT DISTINCT t.nome
            FROM db_tabelao.tabelao t
            LEFT JOIN noticias n ON t.id = n.parlamentar_id
            WHERE n.parlamentar_id IS NULL AND t.ultimoStatus_idLegislatura = 57
            ORDER BY t.nome
        """)
        
        parlamentares = [row[0] for row in cursor.fetchall()]
        
        cursor.execute("DETACH DATABASE db_tabelao")
        return parlamentares
    
    def exibir_dashboard(self):
        """Exibe dashboard completo do progresso."""
        print("📊 DASHBOARD DE PROGRESSO - COLETOR DE NOTÍCIAS")
        print("=" * 60)
        
        # Estatísticas gerais
        stats = self.obter_estatisticas_gerais()
        
        print(f"\n📈 ESTATÍSTICAS GERAIS:")
        print(f"   📰 Total de notícias: {stats['total_noticias']:,}")
        print(f"   👥 Parlamentares com notícias: {stats['parlamentares_com_noticias']}/{stats['total_parlamentares']}")
        print(f"   📅 Meses concluídos: {stats['meses_concluidos']}")
        print(f"   🔄 Meses em andamento: {stats['meses_em_andamento']}")
        print(f"   🕐 Última coleta: {stats['ultima_coleta'] or 'Nunca'}")
        
        # Progresso por parlamentar
        print(f"\n🏆 TOP 20 PARLAMENTARES COM MAIS NOTÍCIAS:")
        progresso_parlamentares = self.obter_progresso_por_parlamentar(20)
        
        if progresso_parlamentares:
            headers = ["Parlamentar", "Meses Processados", "Total Notícias", "Última Atualização"]
            table_data = []
            for nome, meses, noticias, ultima in progresso_parlamentares:
                table_data.append([
                    nome[:30] + "..." if len(nome) > 30 else nome,
                    meses,
                    f"{noticias:,}",
                    ultima[:10] if ultima else "N/A"
                ])
            
            print(tabulate(table_data, headers=headers, tablefmt="grid"))
        
        # Progresso por mês
        print(f"\n📅 PROGRESSO POR MÊS/ANO:")
        progresso_meses = self.obter_progresso_por_mes()
        
        if progresso_meses:
            headers = ["Mês/Ano", "Parlamentares", "Notícias", "Concluídos", "Em Andamento"]
            table_data = []
            for mes_ano, parlamentares, noticias, concluidos, em_andamento in progresso_meses:
                table_data.append([
                    mes_ano,
                    parlamentares,
                    f"{noticias:,}",
                    concluidos,
                    em_andamento
                ])
            
            print(tabulate(table_data, headers=headers, tablefmt="grid"))
        
        # Top categorias
        print(f"\n🏷️  TOP 10 CATEGORIAS:")
        top_categorias = self.obter_top_categorias(10)
        
        if top_categorias:
            headers = ["Categoria", "Total Notícias"]
            table_data = [[cat, f"{total:,}"] for cat, total in top_categorias]
            print(tabulate(table_data, headers=headers, tablefmt="grid"))
        
        # Top veículos
        print(f"\n📺 TOP 10 VEÍCULOS:")
        top_veiculos = self.obter_top_veiculos(10)
        
        if top_veiculos:
            headers = ["Veículo", "Total Notícias"]
            table_data = [[veiculo[:40] + "..." if len(veiculo) > 40 else veiculo, f"{total:,}"] 
                         for veiculo, total in top_veiculos]
            print(tabulate(table_data, headers=headers, tablefmt="grid"))
        
        # Parlamentares sem notícias
        sem_noticias = self.obter_parlamentares_sem_noticias()
        if sem_noticias:
            print(f"\n⚠️  PARLAMENTARES SEM NOTÍCIAS ({len(sem_noticias)}):")
            for i, nome in enumerate(sem_noticias[:20], 1):
                print(f"   {i:2d}. {nome}")
            if len(sem_noticias) > 20:
                print(f"   ... e mais {len(sem_noticias) - 20} parlamentares")
    
    def resetar_progresso_parlamentar(self, parlamentar_nome):
        """Reseta o progresso de um parlamentar específico."""
        cursor = self.conn_noticias.cursor()
        
        # Buscar ID do parlamentar
        cursor_tabelao = self.conn_tabelao.cursor()
        cursor_tabelao.execute("SELECT id FROM tabelao WHERE nome = ?", (parlamentar_nome,))
        resultado = cursor_tabelao.fetchone()
        
        if not resultado:
            print(f"❌ Parlamentar '{parlamentar_nome}' não encontrado")
            return
        
        parlamentar_id = resultado[0]
        
        # Deletar notícias e progresso
        cursor.execute("DELETE FROM noticias WHERE parlamentar_id = ?", (parlamentar_id,))
        cursor.execute("DELETE FROM progresso_mensal WHERE parlamentar_id = ?", (parlamentar_id,))
        
        self.conn_noticias.commit()
        print(f"✅ Progresso resetado para {parlamentar_nome}")
    
    def fechar_conexoes(self):
        """Fecha as conexões com os bancos."""
        if self.conn_tabelao:
            self.conn_tabelao.close()
        if self.conn_noticias:
            self.conn_noticias.close()

def main():
    """Função principal."""
    
    import sys
    
    monitor = MonitorProgressoNoticias()
    
    try:
        monitor.conectar_bancos()
        
        if len(sys.argv) > 1:
            comando = sys.argv[1]
            
            if comando == "dashboard":
                monitor.exibir_dashboard()
            elif comando == "reset" and len(sys.argv) > 2:
                parlamentar = sys.argv[2]
                monitor.resetar_progresso_parlamentar(parlamentar)
            else:
                print("Comandos disponíveis:")
                print("  python 11_monitor_progresso_noticias.py dashboard")
                print("  python 11_monitor_progresso_noticias.py reset 'Nome do Parlamentar'")
        else:
            monitor.exibir_dashboard()
    
    except Exception as e:
        print(f"❌ Erro: {e}")
    finally:
        monitor.fechar_conexoes()

if __name__ == "__main__":
    main()
