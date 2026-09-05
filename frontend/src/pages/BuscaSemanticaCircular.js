import React, { useState, useEffect, useRef } from 'react';
import {
  Box,
  Container,
  Typography,
  TextField,
  Button,
  Paper,
  Grid,
  Card,
  CardContent,
  Chip,
  CircularProgress,
  Alert,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Accordion,
  AccordionSummary,
  AccordionDetails,
  Divider,
  IconButton,
  Tooltip
} from '@mui/material';
import * as echarts from 'echarts';
import { API_HEADERS } from '../config';
import {
  Search as SearchIcon,
  ExpandMore as ExpandMoreIcon,
  OpenInNew as OpenInNewIcon,
  ContentCopy as ContentCopyIcon,
  Timeline as TimelineIcon,
  People as PeopleIcon,
  Article as ArticleIcon,
  TrendingUp as TrendingUpIcon
} from '@mui/icons-material';

const BuscaSemantica = () => {
  // Estados principais
  const [tema, setTema] = useState('');
  const [dataInicio, setDataInicio] = useState('2023-01-01');
  const [dataFim, setDataFim] = useState(new Date().toISOString().split('T')[0]);
  const [loading, setLoading] = useState(false);
  const [erro, setErro] = useState('');
  const [resultados, setResultados] = useState(null);
  const [progresso, setProgresso] = useState('');
  
  // Estados do grafo
  const [grafoData, setGrafoData] = useState(null);
  const [filtroCategoria, setFiltroCategoria] = useState('todos');
  const [filtroSentimento, setFiltroSentimento] = useState('todos');
  const [mostrarConexoes, setMostrarConexoes] = useState(true);
  const [filtroPartido, setFiltroPartido] = useState('todos');
  const [filtroEstado, setFiltroEstado] = useState('todos');
  const [filtroComissao, setFiltroComissao] = useState('todos');
  const [tooltipFixo, setTooltipFixo] = useState(null);
  
  // Refs para o gráfico
  const grafoRef = useRef(null);
  const grafoChartRef = useRef(null);

  // Função para formatar valores monetários
  const formatarMoeda = (valor) => {
    return new Intl.NumberFormat('pt-BR', {
      style: 'currency',
      currency: 'BRL'
    }).format(valor);
  };

  // Função para criar o grafo ECharts com layout circular
  const criarGrafoECharts = () => {
    if (!grafoData || !grafoRef.current) return;

    // Limpar gráfico anterior
    if (grafoChartRef.current) {
      grafoChartRef.current.dispose();
    }

    // Criar novo gráfico
    const chart = echarts.init(grafoRef.current);
    grafoChartRef.current = chart;

    // Aplicar filtros
    let nodesFiltrados = grafoData.nodes || [];
    let linksFiltrados = grafoData.links || [];

    // Filtrar por categoria
    if (filtroCategoria !== 'todos') {
      nodesFiltrados = nodesFiltrados.filter(node => node.category === filtroCategoria);
    }

    // Filtrar por partido (apenas deputados)
    if (filtroPartido !== 'todos') {
      nodesFiltrados = nodesFiltrados.filter(node => 
        node.category !== 'Parlamentar' || node.partido === filtroPartido
      );
    }

    // Filtrar por estado (apenas deputados)
    if (filtroEstado !== 'todos') {
      nodesFiltrados = nodesFiltrados.filter(node => 
        node.category !== 'Parlamentar' || node.estado === filtroEstado
      );
    }

    // Filtrar por comissão (apenas deputados)
    if (filtroComissao !== 'todos') {
      nodesFiltrados = nodesFiltrados.filter(node => 
        node.category !== 'Parlamentar' || node.comissao === filtroComissao
      );
    }

    // Manter apenas links que conectam nós filtrados
    const idsFiltrados = new Set(nodesFiltrados.map(n => n.id));
    linksFiltrados = linksFiltrados.filter(link => 
      idsFiltrados.has(link.source) && idsFiltrados.has(link.target)
    );

    // Filtrar por sentimento (apenas para links entre deputados)
    if (filtroSentimento !== 'todos') {
      linksFiltrados = linksFiltrados.filter(link => {
        // Se é conexão entre deputados, verificar sentimento
        if (link.sentimentos && link.sentimentos.length > 0) {
          return link.sentimentos.includes(filtroSentimento);
        }
        // Se é conexão de afiliação, sempre mostrar
        return true;
      });
    }

    // Mostrar/ocultar conexões
    if (!mostrarConexoes) {
      linksFiltrados = [];
    }

    // Preparar dados para o layout circular
    const graph = {
      nodes: nodesFiltrados.map(node => ({
        ...node,
        label: {
          show: node.symbolSize > 30
        }
      })),
      links: linksFiltrados,
      categories: grafoData.categories || []
    };

    // Configuração do ECharts com layout circular
    const option = {
      title: {
        text: '📊 Grafo de Relacionamentos Parlamentares',
        subtext: `Layout circular com ${graph.nodes.length} parlamentares e ${graph.links.length} conexões`,
        top: 'bottom',
        left: 'right',
        textStyle: {
          fontSize: 18,
          fontWeight: 'bold'
        },
        subtextStyle: {
          fontSize: 12,
          color: '#666'
        }
      },
      tooltip: {
        formatter: function(params) {
          if (params.dataType === 'node') {
            return params.data.tooltip_texto || `${params.data.name}`;
          } else if (params.dataType === 'edge') {
            return `<strong>${params.data.source} → ${params.data.target}</strong><br/>
                    <strong>Sentimento:</strong> ${params.data.sentimento}<br/>
                    <strong>Tom:</strong> ${params.data.tom}<br/>
                    <strong>Frases:</strong><br/>${params.data.frases ? params.data.frases.slice(0, 2).map(frase => `• ${frase}`).join('<br/>') : 'N/A'}`;
          }
          return '';
        }
      },
      legend: [
        {
          data: graph.categories.map(function (a) {
            return a.name;
          })
        }
      ],
      animationDurationUpdate: 1500,
      animationEasingUpdate: 'quinticInOut',
      series: [
        {
          name: 'Relacionamentos Parlamentares',
          type: 'graph',
          layout: 'circular',
          circular: {
            rotateLabel: true
          },
          data: graph.nodes,
          links: graph.links,
          categories: graph.categories,
          roam: true,
          label: {
            position: 'right',
            formatter: '{b}'
          },
          lineStyle: {
            color: 'source',
            curveness: 0.3
          },
          symbol: 'circle',
          symbolSize: function(value, params) {
            if (params.data.category === 'Parlamentar') return 30;
            if (params.data.category === 'Partido') return 25;
            if (params.data.category === 'Estado') return 20;
            return 15;
          },
          itemStyle: {
            borderRadius: '50%'
          },
          emphasis: {
            focus: 'adjacency',
            lineStyle: {
              width: 4
            }
          }
        }
      ]
    };

    // Configurar evento de clique nas arestas
    chart.on('click', function(params) {
      if (params.dataType === 'edge') {
        setTooltipFixo({
          source: params.data.source,
          target: params.data.target,
          sentimento: params.data.sentimento,
          tom: params.data.tom,
          frases: params.data.frases || []
        });
      }
    });

    // Aplicar configuração
    chart.setOption(option);

    // Cleanup function
    return () => {
      if (chart) {
        chart.dispose();
      }
    };
  };

  // Effect para criar o grafo quando os dados mudarem
  useEffect(() => {
    if (grafoData && grafoData.nodes && grafoData.nodes.length > 0) {
      const cleanup = criarGrafoECharts();
      return cleanup;
    }
  }, [grafoData, filtroCategoria, filtroSentimento, filtroPartido, filtroEstado, filtroComissao, mostrarConexoes]);

  // Função para executar busca semântica
  const executarBusca = async () => {
    if (!tema.trim()) {
      setErro('Por favor, digite um tema para análise.');
      return;
    }

    setLoading(true);
    setErro('');
    setResultados(null);
    setProgresso('🔍 Iniciando busca semântica...');

    try {
      const response = await fetch(`/api/busca-semantica/buscar`, {
        method: 'POST',
        headers: { ...API_HEADERS, 'Content-Type': 'application/json' },
        body: JSON.stringify({
          tema: tema.trim(),
          data_inicio: dataInicio,
          data_fim: dataFim
        })
      });
      const data = await response.json();

      if (data.error) {
        setErro(data.error);
        setProgresso('❌ Erro na análise');
        return;
      }

      setResultados(data);
      setGrafoData(data.grafo_data);
      setProgresso(data.progresso || '✅ Análise concluída');

    } catch (error) {
      console.error('Erro na busca:', error);
      setErro('Erro ao conectar com o servidor. Verifique se o backend está rodando.');
      setProgresso('❌ Erro na análise');
    } finally {
      setLoading(false);
    }
  };

  // Função para limpar filtros
  const limparFiltros = () => {
    setFiltroCategoria('todos');
    setFiltroSentimento('todos');
    setFiltroPartido('todos');
    setFiltroEstado('todos');
    setFiltroComissao('todos');
    setMostrarConexoes(true);
  };

  return (
    <Container maxWidth="xl" sx={{ py: 4 }}>
      {/* Header */}
      <Box sx={{ mb: 4 }}>
        <Typography variant="h4" component="h1" gutterBottom sx={{ fontWeight: 'bold', color: '#1976d2' }}>
          🔍 Busca Semântica Parlamentar
        </Typography>
        <Typography variant="subtitle1" color="text.secondary">
          Análise inteligente de discursos parlamentares com IA
        </Typography>
      </Box>

      {/* Formulário de Busca */}
      <Paper sx={{ p: 3, mb: 4 }}>
        <Grid container spacing={3} alignItems="center">
          <Grid item xs={12} md={4}>
            <TextField
              fullWidth
              label="Tema de Análise"
              placeholder="Ex: meio ambiente, saúde, educação"
              value={tema}
              onChange={(e) => setTema(e.target.value)}
              variant="outlined"
            />
          </Grid>
          <Grid item xs={12} md={2}>
            <TextField
              fullWidth
              label="Data Início"
              type="date"
              value={dataInicio}
              onChange={(e) => setDataInicio(e.target.value)}
              InputLabelProps={{ shrink: true }}
            />
          </Grid>
          <Grid item xs={12} md={2}>
            <TextField
              fullWidth
              label="Data Fim"
              type="date"
              value={dataFim}
              onChange={(e) => setDataFim(e.target.value)}
              InputLabelProps={{ shrink: true }}
            />
          </Grid>
          <Grid item xs={12} md={4}>
            <Button
              fullWidth
              variant="contained"
              size="large"
              startIcon={<SearchIcon />}
              onClick={executarBusca}
              disabled={loading}
              sx={{ height: '56px' }}
            >
              {loading ? 'Analisando...' : 'Executar Análise'}
            </Button>
          </Grid>
        </Grid>
      </Paper>

      {/* Indicador de Progresso */}
      {loading && (
        <Box sx={{ mb: 3, display: 'flex', alignItems: 'center', gap: 2 }}>
          <CircularProgress size={24} />
          <Alert severity="info" sx={{ flex: 1 }}>
            {progresso}
          </Alert>
        </Box>
      )}

      {/* Erro */}
      {erro && (
        <Alert severity="error" sx={{ mb: 3 }}>
          {erro}
        </Alert>
      )}

      {/* Resultados */}
      {resultados && (
        <Grid container spacing={3}>
          {/* Estatísticas */}
          <Grid item xs={12}>
            <Card>
              <CardContent>
                <Typography variant="h6" gutterBottom>
                  📊 Estatísticas da Análise
                </Typography>
                <Grid container spacing={2}>
                  <Grid item xs={6} sm={3}>
                    <Box textAlign="center">
                      <Typography variant="h4" color="primary">
                        {resultados.estatisticas?.total_discursos || 0}
                      </Typography>
                      <Typography variant="body2" color="text.secondary">
                        Discursos Encontrados
                      </Typography>
                    </Box>
                  </Grid>
                  <Grid item xs={6} sm={3}>
                    <Box textAlign="center">
                      <Typography variant="h4" color="success.main">
                        {resultados.estatisticas?.discursos_validados || 0}
                      </Typography>
                      <Typography variant="body2" color="text.secondary">
                        Validados pelo LLM
                      </Typography>
                    </Box>
                  </Grid>
                  <Grid item xs={6} sm={3}>
                    <Box textAlign="center">
                      <Typography variant="h4" color="warning.main">
                        {resultados.estatisticas?.parlamentares_envolvidos || 0}
                      </Typography>
                      <Typography variant="body2" color="text.secondary">
                        Parlamentares
                      </Typography>
                    </Box>
                  </Grid>
                  <Grid item xs={6} sm={3}>
                    <Box textAlign="center">
                      <Typography variant="h4" color="info.main">
                        {resultados.estatisticas?.total_citacoes || 0}
                      </Typography>
                      <Typography variant="body2" color="text.secondary">
                        Citações
                      </Typography>
                    </Box>
                  </Grid>
                </Grid>
              </CardContent>
            </Card>
          </Grid>

          {/* Palavras-chave */}
          {resultados.palavras_chave && resultados.palavras_chave.length > 0 && (
            <Grid item xs={12}>
              <Card>
                <CardContent>
                  <Typography variant="h6" gutterBottom>
                    🔑 Palavras-chave Geradas pelo LLM
                  </Typography>
                  <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1 }}>
                    {resultados.palavras_chave.slice(0, 10).map((palavra, index) => (
                      <Chip
                        key={index}
                        label={palavra}
                        color="primary"
                        variant="outlined"
                        size="small"
                      />
                    ))}
                    {resultados.palavras_chave.length > 10 && (
                      <Chip
                        label={`+${resultados.palavras_chave.length - 10} mais`}
                        color="default"
                        variant="outlined"
                        size="small"
                      />
                    )}
                  </Box>
                </CardContent>
              </Card>
            </Grid>
          )}

          {/* Filtros do Grafo */}
          <Grid item xs={12}>
            <Card>
              <CardContent>
                <Typography variant="h6" gutterBottom>
                  🎛️ Filtros do Grafo
                </Typography>
                <Grid container spacing={2} alignItems="center">
                  <Grid item xs={12} sm={6} md={2}>
                    <FormControl fullWidth size="small">
                      <InputLabel>Categoria</InputLabel>
                      <Select
                        value={filtroCategoria}
                        onChange={(e) => setFiltroCategoria(e.target.value)}
                        label="Categoria"
                      >
                        <MenuItem value="todos">Todas</MenuItem>
                        <MenuItem value="Parlamentar">Parlamentares</MenuItem>
                        <MenuItem value="Partido">Partidos</MenuItem>
                        <MenuItem value="Estado">Estados</MenuItem>
                      </Select>
                    </FormControl>
                  </Grid>
                  <Grid item xs={12} sm={6} md={2}>
                    <FormControl fullWidth size="small">
                      <InputLabel>Partido</InputLabel>
                      <Select
                        value={filtroPartido}
                        onChange={(e) => setFiltroPartido(e.target.value)}
                        label="Partido"
                      >
                        <MenuItem value="todos">Todos</MenuItem>
                        {/* Adicionar partidos dinamicamente */}
                      </Select>
                    </FormControl>
                  </Grid>
                  <Grid item xs={12} sm={6} md={2}>
                    <FormControl fullWidth size="small">
                      <InputLabel>Estado</InputLabel>
                      <Select
                        value={filtroEstado}
                        onChange={(e) => setFiltroEstado(e.target.value)}
                        label="Estado"
                      >
                        <MenuItem value="todos">Todos</MenuItem>
                        {/* Adicionar estados dinamicamente */}
                      </Select>
                    </FormControl>
                  </Grid>
                  <Grid item xs={12} sm={6} md={2}>
                    <FormControl fullWidth size="small">
                      <InputLabel>Comissão</InputLabel>
                      <Select
                        value={filtroComissao}
                        onChange={(e) => setFiltroComissao(e.target.value)}
                        label="Comissão"
                      >
                        <MenuItem value="todos">Todas</MenuItem>
                        {/* Adicionar comissões dinamicamente */}
                      </Select>
                    </FormControl>
                  </Grid>
                  <Grid item xs={12} sm={6} md={2}>
                    <FormControl fullWidth size="small">
                      <InputLabel>Sentimento</InputLabel>
                      <Select
                        value={filtroSentimento}
                        onChange={(e) => setFiltroSentimento(e.target.value)}
                        label="Sentimento"
                      >
                        <MenuItem value="todos">Todos</MenuItem>
                        <MenuItem value="Positivo">Positivo</MenuItem>
                        <MenuItem value="Negativo">Negativo</MenuItem>
                        <MenuItem value="Neutro">Neutro</MenuItem>
                      </Select>
                    </FormControl>
                  </Grid>
                  <Grid item xs={12} sm={6} md={2}>
                    <Box sx={{ display: 'flex', gap: 1 }}>
                      <Button
                        variant={mostrarConexoes ? "contained" : "outlined"}
                        onClick={() => setMostrarConexoes(!mostrarConexoes)}
                        size="small"
                      >
                        {mostrarConexoes ? 'Ocultar' : 'Mostrar'} Conexões
                      </Button>
                      <Button
                        variant="outlined"
                        onClick={limparFiltros}
                        size="small"
                      >
                        Limpar
                      </Button>
                    </Box>
                  </Grid>
                </Grid>
              </CardContent>
            </Card>
          </Grid>

          {/* Grafo de Relacionamentos */}
          <Grid item xs={12}>
            <Card>
              <CardContent>
                <Typography variant="h6" gutterBottom>
                  📊 Grafo de Relacionamentos Parlamentares
                </Typography>
                <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                  Grafo interativo mostrando relacionamentos entre parlamentares baseados em citações nos discursos.
                </Typography>
                
                {/* Legenda */}
                <Box sx={{ display: 'flex', gap: 2, mb: 2, flexWrap: 'wrap' }}>
                  <Chip label="Deputados" color="primary" size="small" />
                  <Chip label="Partidos" color="secondary" size="small" />
                  <Chip label="Estados" color="success" size="small" />
                </Box>

                {/* Container do Grafo */}
                <Box
                  ref={grafoRef}
                  sx={{
                    width: '100%',
                    height: '600px',
                    border: '1px solid #e0e0e0',
                    borderRadius: 1,
                    backgroundColor: '#fafafa'
                  }}
                />
              </CardContent>
            </Card>
          </Grid>

          {/* Relatório Completo */}
          {resultados.relatorio && (
            <Grid item xs={12}>
              <Card>
                <CardContent>
                  <Typography variant="h6" gutterBottom>
                    📋 Relatório Completo
                  </Typography>
                  <Box
                    sx={{
                      whiteSpace: 'pre-wrap',
                      lineHeight: 1.6,
                      fontSize: '0.95rem',
                      maxHeight: '400px',
                      overflowY: 'auto',
                      p: 2,
                      backgroundColor: '#f8f9fa',
                      borderRadius: 1,
                      border: '1px solid #e9ecef'
                    }}
                  >
                    {resultados.relatorio}
                  </Box>
                </CardContent>
              </Card>
            </Grid>
          )}
        </Grid>
      )}

      {/* Tooltip Fixo para Arestas */}
      {tooltipFixo && (
        <Box
          sx={{
            position: 'fixed',
            top: '50%',
            left: '50%',
            transform: 'translate(-50%, -50%)',
            zIndex: 9999,
            backgroundColor: 'white',
            border: '2px solid #1976d2',
            borderRadius: 2,
            p: 3,
            maxWidth: '500px',
            maxHeight: '400px',
            overflowY: 'auto',
            boxShadow: '0 8px 32px rgba(0,0,0,0.3)'
          }}
        >
          <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
            <Typography variant="h6">
              {tooltipFixo.source} → {tooltipFixo.target}
            </Typography>
            <IconButton onClick={() => setTooltipFixo(null)} size="small">
              ✕
            </IconButton>
          </Box>
          <Typography variant="body2" color="text.secondary" gutterBottom>
            <strong>Sentimento:</strong> {tooltipFixo.sentimento} | <strong>Tom:</strong> {tooltipFixo.tom}
          </Typography>
          <Typography variant="body2" sx={{ mt: 1 }}>
            <strong>Frases:</strong>
          </Typography>
          {tooltipFixo.frases.map((frase, index) => (
            <Typography key={index} variant="body2" sx={{ mt: 1, fontStyle: 'italic' }}>
              • {frase}
            </Typography>
          ))}
        </Box>
      )}
    </Container>
  );
};

export default BuscaSemantica;

