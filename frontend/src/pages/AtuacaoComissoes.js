import React, { useState, useEffect, useRef } from 'react';
import {
  Container,
  Typography,
  Box,
  Paper,
  Grid,
  CircularProgress,
  Alert,
  Button,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Card,
  CardContent,
  Chip,
  Avatar,
  LinearProgress,
  Tooltip,
  IconButton,
  GlobalStyles,
  TextField
} from '@mui/material';
import SearchIcon from '@mui/icons-material/Search';
import AccountBalanceIcon from '@mui/icons-material/AccountBalance';
import HelpOutlineIcon from '@mui/icons-material/HelpOutline';
import PrintIcon from '@mui/icons-material/Print';
import TrendingUpIcon from '@mui/icons-material/TrendingUp';
import FolderOpenIcon from '@mui/icons-material/FolderOpen';
import ReactECharts from 'echarts-for-react';
import ReactMarkdown from 'react-markdown';
import api from '../config/axios';
import { API_BASE_URL, API_KEY } from '../config';
import FilterSelector from '../components/FilterSelector';
import { PARTIDO_LOGOS_FALLBACK } from '../utils/logos';
import DataSourceFooter from '../components/DataSourceFooter';

// O axios já está configurado no arquivo ../config/api.js

const normalizeWikiUrl = (url) => {
  if (!url) return url;
  if (url.includes('wikipedia.org') || url.includes('wikimedia.org')) {
    const filename = url.split('/').pop();
    return `https://commons.wikimedia.org/wiki/Special:FilePath/${filename}`;
  }
  return url;
};

function AtuacaoComissoes() {
  const getPartidoLogo = (partido, urlOriginal) => {
    const fallback = partido ? PARTIDO_LOGOS_FALLBACK[partido.trim().toUpperCase()] : null;
    return normalizeWikiUrl(fallback || urlOriginal);
  };

  const getEstadoBandeira = (uf, urlOriginal) => {
    return normalizeWikiUrl(urlOriginal) || (uf ? `https://flagcdn.com/w160/br-${uf.toLowerCase()}.png` : "");
  };
  // Estados para filtros
  // Estados selecionados
  const [filtros, setFiltros] = useState({
    estado: 'Todos',
    partido: 'Todos',
    parlamentar: 'Todos',
  });

  const parlamentarSelecionado = filtros.parlamentar || 'Todos';
  const partidoSelecionado = filtros.partido || 'Todos';
  const estadoSelecionado = filtros.estado || 'Todos';
  const [comissoes, setComissoes] = useState([]);
  const [comissaoSelecionada, setComissaoSelecionada] = useState('Todos');
  const [carregandoPeriodo, setCarregandoPeriodo] = useState(false);
  const [loadingComissoes, setLoadingComissoes] = useState(false);
  const [avisoSemDados, setAvisoSemDados] = useState(false);

  // Estados de data
  const [dataInicio, setDataInicio] = useState('2023-01-01');
  const [dataFim, setDataFim] = useState(new Date().toISOString().split('T')[0]);

  // Estados de dados e carregamento
  const [discursos, setDiscursos] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [relatorio, setRelatorio] = useState(null);
  const [loadingRelatorio, setLoadingRelatorio] = useState(false);
  const [progresso, setProgresso] = useState({ processados: 0, total: 0, mensagem: '', status: '' });
  const [tempoDecorrido, setTempoDecorrido] = useState(0);
  const [dadosParlamentar, setDadosParlamentar] = useState(null);
  const [fromCache, setFromCache] = useState(false);

  const relatorioRef = useRef(null);

  // Atualizar comissões quando parlamentar ou datas mudam
  useEffect(() => {
    if (filtros.parlamentar && filtros.parlamentar !== 'Todos') {
      carregarComissoes(filtros.parlamentar);
    } else {
      setComissoes([]);
      setComissaoSelecionada('Todos');
    }
  }, [filtros.parlamentar]);

  // Timer para tempo decorrido
  useEffect(() => {
    let interval;
    if (loadingRelatorio) {
      interval = setInterval(() => {
        setTempoDecorrido(prev => prev + 1);
      }, 1000);
    } else {
      setTempoDecorrido(0);
    }
    return () => clearInterval(interval);
  }, [loadingRelatorio]);

  // Funções de carregamento de dados

  const carregarComissoes = async (parlamentar) => {
    setLoadingComissoes(true);
    try {
      const params = {
        parlamentar,
        data_inicio: dataInicio,
        data_fim: dataFim
      };
      if (filtros.estado && filtros.estado !== 'Todos') {
        params.estado = filtros.estado;
      }
      if (filtros.partido && filtros.partido !== 'Todos') {
        params.partido = filtros.partido;
      }

      console.log('🔄 Buscando comissões para:', parlamentar, 'Datas:', dataInicio, dataFim);
      const response = await api.get('/api/filters/comissoes', { params });
      console.log('🏛️ Comissões recebidas:', response.data);

      // API retorna {comissoes: [...]}
      const data = response.data?.comissoes || response.data;
      let lista = Array.isArray(data) ? data : [];

      // Normalizar para {comissao: "Nome"} independente do formato da API
      const listaFormatada = lista.map(item => {
        if (typeof item === 'string') return { comissao: item };
        // API retorna {id, nome} — normalizar para {comissao}
        if (item.nome && !item.comissao) return { comissao: item.nome, id: item.id };
        return item;
      });

      setComissoes(listaFormatada);

      // Se a comissão selecionada não estiver na nova lista, limpar seleção
      if (comissaoSelecionada && !listaFormatada.some(c => c.comissao === comissaoSelecionada)) {
        setComissaoSelecionada('');
      }
    } catch (err) {
      console.error('Erro ao carregar comissões:', err);
      setComissoes([]);
    } finally {
      setLoadingComissoes(false);
    }
  };

  const handleComissaoChange = async (novaComissao) => {
    setComissaoSelecionada(novaComissao);
    setAvisoSemDados(false);
    if (novaComissao === 'Todos' || !novaComissao || !filtros.parlamentar || filtros.parlamentar === 'Todos') return;
    try {
      setCarregandoPeriodo(true);
      const comObj = comissoes.find(c => (c.comissao || c.Comissao) === novaComissao);
      const sigla = comObj?.id || novaComissao;
      const resp = await api.get('/api/filters/comissoes/periodo', {
        params: { parlamentar: filtros.parlamentar, comissao: sigla, nome_comissao: novaComissao }
      });
      const temDadosReais = resp.data?.tem_dados === true;
      if (resp.data?.data_inicio) setDataInicio(resp.data.data_inicio);
      if (resp.data?.data_fim) setDataFim(resp.data.data_fim);
      setAvisoSemDados(!temDadosReais);
    } catch (err) {
      console.warn('Não foi possível buscar período da comissão:', err);
      setAvisoSemDados(true);
    } finally {
      setCarregandoPeriodo(false);
    }
  };

  const executarAnalise = async () => {
    if (parlamentarSelecionado === 'Todos' || comissaoSelecionada === 'Todos') {
      setError('Selecione um parlamentar e uma comissão para executar a análise.');
      return;
    }

    setLoadingRelatorio(true);
    setError(null);
    setRelatorio(null);
    setDadosParlamentar(null);
    setProgresso({ processados: 0, total: 0, mensagem: 'Iniciando análise...', status: 'iniciando' });

    try {
      // 1. Buscar dados do parlamentar (foto, etc)
      try {
        console.log('🔍 Buscando detalhes do parlamentar:', parlamentarSelecionado);
        const respParlamentar = await api.get('/api/parlamentares/detalhes', {
          params: { nome: parlamentarSelecionado }
        });
        console.log('📸 Detalhes recebidos:', respParlamentar.data);

        if (respParlamentar.data) {
          setDadosParlamentar(respParlamentar.data);
        }
      } catch (e) {
        console.error('❌ Erro ao carregar detalhes do parlamentar:', e);
        // Usar dados básicos se falhar
        setDadosParlamentar({
          nome: parlamentarSelecionado,
          partido: partidoSelecionado,
          uf: estadoSelecionado,
          erro: e.message // Debug
        });
      }

      // 2. Iniciar análise via SSE (Server-Sent Events) ou Polling
      // Usando POST para iniciar a análise
      const response = await api.post('/api/comissoes/analisar', {
        parlamentar: filtros.parlamentar,
        comissao: comissaoSelecionada,
        estado: filtros.estado !== 'Todos' ? filtros.estado : null,
        partido: filtros.partido !== 'Todos' ? filtros.partido : null,
        data_inicio: dataInicio,
        data_fim: dataFim
      });

      console.log('✅ Resposta da análise:', response.data);

      if (response.data.status === 'erro') {
        // Tratamento específico para falta de dados
        if (response.data.mensagem && response.data.mensagem.includes('Nenhum discurso')) {
          setError('⚠️ Não foram encontrados discursos para este parlamentar no período selecionado.');
          setLoadingRelatorio(false);
          return;
        }
        throw new Error(response.data.mensagem || 'Erro ao processar análise');
      }

      // Se retornou relatório completo (cache ou processamento rápido)
      if (response.data.relatorio) {
        setRelatorio(response.data.relatorio);
        setFromCache(response.data.from_cache === true);
        setProgresso({
          processados: response.data.total_discursos || 100,
          total: response.data.total_discursos || 100,
          mensagem: 'Análise concluída com sucesso!',
          status: 'completo'
        });
      } else if (response.data.session_id) {
        // Se retornou session_id, iniciar polling para acompanhar progresso
        monitorarProgresso(response.data.session_id);
      } else {
        throw new Error('Resposta do servidor inválida');
      }

    } catch (err) {
      console.error('Erro na análise:', err);
      setError(`Erro ao executar análise: ${err.message || 'Falha na comunicação com o servidor'}`);
      setLoadingRelatorio(false);
    }
  };

  // Função para monitorar progresso via polling
  const monitorarProgresso = async (sessionId) => {
    const intervalId = setInterval(async () => {
      try {
        const response = await api.get(`/api/comissoes/progresso/${sessionId}`);
        const status = response.data;
        console.log(`🔄 Polling ${sessionId}:`, status);

        setProgresso({
          processados: status.processados || 0,
          total: status.total || 0,
          mensagem: status.mensagem || 'Processando...',
          status: status.status,
          lote_atual: status.lote_atual || 0,
          total_lotes: status.total_lotes || 0
        });

        if (status.status === 'completo') {
          clearInterval(intervalId);
          setRelatorio(status.resultado);
          setLoadingRelatorio(false);
        } else if (status.status === 'erro') {
          clearInterval(intervalId);
          setError(status.mensagem || 'Erro durante o processamento da análise');
          setLoadingRelatorio(false);
        }
      } catch (err) {
        console.error('Erro ao monitorar progresso:', err);
        // Não parar imediatamente em caso de erro de rede temporário
      }
    }, 2000); // Poll a cada 2 segundos
  };

  // Configurações dos gráficos
  const getGraficoEvolucaoOptions = () => {
    // Fallback para garantir que o gráfico sempre renderize algo
    const defaultData = {
      datas: ['Seg', 'Ter', 'Qua', 'Qui', 'Sex'],
      objetividade: [0, 0, 0, 0, 0],
      tensao: [0, 0, 0, 0, 0]
    };

    let datas = defaultData.datas;
    let objetividade = defaultData.objetividade;
    let tensao = defaultData.tensao;

    if (relatorio && relatorio.evolucao_temporal && Object.keys(relatorio.evolucao_temporal).length > 0) {
      const sortedKeys = Object.keys(relatorio.evolucao_temporal).sort();
      datas = sortedKeys.map(d => {
        try {
          const [ano, mes, dia] = d.split('-');
          return `${dia}/${mes}`;
        } catch (e) {
          return d;
        }
      });
      objetividade = sortedKeys.map(d => relatorio.evolucao_temporal[d].objetividade_media?.toFixed(1) || 0);
      tensao = sortedKeys.map(d => relatorio.evolucao_temporal[d].tensao_media?.toFixed(1) || 0);
    }

    // Modelo solicitado pelo usuário
    return {
      title: {
        text: 'Evolução Diária'
      },
      tooltip: {
        trigger: 'axis'
      },
      legend: {
        data: ['Objetividade', 'Tensão']
      },
      grid: {
        left: '3%',
        right: '4%',
        bottom: '3%',
        containLabel: true
      },
      toolbox: {
        feature: {
          saveAsImage: {}
        }
      },
      xAxis: {
        type: 'category',
        boundaryGap: false,
        data: datas
      },
      yAxis: {
        type: 'value',
        max: 10,
        min: 0
      },
      series: [
        {
          name: 'Objetividade',
          type: 'line',
          // stack: 'Total', // Removido para não somar valores (0-10)
          data: objetividade,
          smooth: true,
          itemStyle: { color: '#009739' },
          areaStyle: { opacity: 0.1 }
        },
        {
          name: 'Tensão',
          type: 'line',
          // stack: 'Total', // Removido para não somar valores (0-10)
          data: tensao,
          smooth: true,
          itemStyle: { color: '#ED8B00' },
          areaStyle: { opacity: 0.1 }
        }
      ]
    };
  };

  const getGraficoCategoriasOptions = () => {
    if (!relatorio || !relatorio.temas_principais || Object.keys(relatorio.temas_principais).length === 0) return null;

    const data = Object.entries(relatorio.temas_principais).map(([tema, dados]) => ({
      name: tema.replace(/_/g, ' '),
      value: dados.frequencia
    })).sort((a, b) => b.value - a.value).slice(0, 10); // Top 10 temas

    return {
      tooltip: {
        trigger: 'item',
        formatter: '{b}: {c} menções'
      },
      color: ['#003366', '#009739', '#ED8B00', '#4F81BD', '#66BB6A', '#FFB74D'],
      series: [
        {
          name: 'Temas',
          type: 'treemap',
          width: '100%',
          height: '100%',
          roam: false,
          nodeClick: false,
          breadcrumb: { show: false },
          itemStyle: {
            borderColor: '#fff',
            borderWidth: 2,
            gapWidth: 1
          },
          label: {
            show: true,
            formatter: '{b}\n({c})',
            color: '#FFFFFF',
            fontSize: 13,
            fontWeight: 'bold',
            overflow: 'truncate'
          },
          data: data
        }
      ]
    };
  };


  const SpinnerIcon = () => (
    <CircularProgress size={18} thickness={4} sx={{ mr: 1, color: 'inherit', opacity: 0.6 }} />
  );

  return (
    <>
      {/* Global print styles */}
      <GlobalStyles
        styles={{
          '@media print': {
            'body *': {
              visibility: 'hidden',
            },
            '#root': {
              visibility: 'hidden',
            },
            '.print-content, .print-content *': {
              visibility: 'visible !important',
            },
            '.print-content': {
              position: 'absolute',
              left: 0,
              top: 0,
              width: '100%',
              margin: 0,
              padding: '20px',
            },
            '.no-print': {
              display: 'none !important',
            },
            // Ensure background colors are printed
            '*': {
              WebkitPrintColorAdjust: 'exact !important',
              printColorAdjust: 'exact !important',
            }
          },
        }}
      />

      <Container maxWidth="lg" sx={{ mt: 4, mb: 4 }}>
        {/* Header */}
        <Box sx={{ mb: 4, backgroundColor: 'white', p: 3, borderRadius: '16px', display: 'flex', alignItems: 'center', gap: 4 }} className="no-print">
          <Box sx={{ flex: 1 }}>
            <Typography variant="h4" component="h1" gutterBottom sx={{ color: '#003366', fontWeight: 'bold' }}>
              Análise de Atuação em Comissões
            </Typography>
            <Typography variant="subtitle1" color="text.secondary" gutterBottom>
              Selecione um parlamentar e uma comissão para gerar um relatório detalhado de atuação baseada em discursos e notas taquigráficas.
            </Typography>
          </Box>
          <Box
            component="img"
            src="/Analise_de_Atuacao_em_Comissoes.png"
            alt="Ilustração Atuação em Comissões"
            sx={{
              maxHeight: '220px',
              width: 'auto',
              borderRadius: '8px',
              display: { xs: 'none', md: 'block' }
            }}
          />
        </Box>

        {/* Filtros */}
        <Paper elevation={3} sx={{ p: 3, mb: 4, backgroundColor: '#f8f9fa' }} className="no-print">
          <Typography variant="h6" sx={{ color: '#003366', mb: 3 }}>
            🔧 Filtros Intercambiáveis
          </Typography>

          <FilterSelector
        requireSelection={true}
        requireAll={true} 
            onFiltersChange={setFiltros}
            fields={['estado', 'partido', 'parlamentar']}
            useCurrentParty={true}
          />

          <Grid container spacing={3} sx={{ mt: 1 }}>
            <Grid item xs={12} md={6}>
              <FormControl fullWidth disabled={filtros.parlamentar === 'Todos' || loadingComissoes}>
                <InputLabel>🏛️ Comissão</InputLabel>
                <Select
                  value={comissaoSelecionada}
                  onChange={(e) => handleComissaoChange(e.target.value)}
                  label="🏛️ Comissão"
                  disabled={loadingComissoes}
                  IconComponent={loadingComissoes ? SpinnerIcon : undefined}
                >
                  <MenuItem value="Todos">Todos</MenuItem>
                  {comissoes.map(com => (
                    <MenuItem key={com.comissao || com.Comissao} value={com.comissao || com.Comissao}>
                      {com.comissao || com.Comissao}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
            </Grid>

            {/* Botoes de Data compactados */}
            <Grid item xs={12} md={3}>
              <TextField
                fullWidth
                size="small"
                label={carregandoPeriodo ? "⏳ Buscando período..." : "📅 Data Início"}
                type="date"
                value={dataInicio}
                onChange={(e) => setDataInicio(e.target.value)}
                InputLabelProps={{ shrink: true }}
                disabled={carregandoPeriodo}
              />
            </Grid>
            <Grid item xs={12} md={3}>
              <TextField
                fullWidth
                size="small"
                label={carregandoPeriodo ? "⏳ Buscando período..." : "📅 Data Fim"}
                type="date"
                value={dataFim}
                onChange={(e) => setDataFim(e.target.value)}
                InputLabelProps={{ shrink: true }}
                disabled={carregandoPeriodo}
              />
            </Grid>
          </Grid>

          {avisoSemDados && comissaoSelecionada !== 'Todos' && (
            <Box sx={{ mt: 2, p: 1.5, backgroundColor: '#fff8e1', borderRadius: 2, border: '1px solid #ffe082', display: 'flex', alignItems: 'center', gap: 1 }}>
              <Typography variant="body2" sx={{ color: '#795548' }}>
                ⚠️ Não encontramos discursos indexados de <strong>{filtros.parlamentar}</strong> nesta comissão. O período exibido é o padrão — você pode ajustá-lo manualmente antes de analisar.
              </Typography>
            </Box>
          )}

          <Box sx={{ mt: 3, textAlign: 'center' }}>
            <Button
              variant="contained"
              size="large"
              onClick={executarAnalise}
              disabled={loading || filtros.estado === 'Todos' || filtros.partido === 'Todos' || parlamentarSelecionado === 'Todos' || comissaoSelecionada === 'Todos'}
              startIcon={loading ? <CircularProgress size={20} /> : <SearchIcon />}
              sx={{
                backgroundColor: '#009739',
                '&:hover': { backgroundColor: '#003366' },
                px: 4,
                py: 1.5,
              }}
            >
              {loading ? 'Executando Análise...' : (
                <Box sx={{ display: 'flex', alignItems: 'center' }}>
                  Analisar Participação
                </Box>
              )}
            </Button>
          </Box>
        </Paper>

        {/* Error Alert */}
        {error && (
          <Alert severity="error" sx={{ mb: 4 }}>
            {error}
          </Alert>
        )}

        {/* Loading Progress */}
        {loadingRelatorio && (
          <Paper elevation={3} sx={{ p: 4, mb: 4, backgroundColor: '#f8f9fa' }}>
            <Box sx={{ textAlign: 'center' }}>
              <Box sx={{ display: 'flex', justifyContent: 'center', mb: 3 }}>
                <Avatar
                  src="/antunes_mascot.png"
                  sx={{ width: 120, height: 120, border: '4px solid #009739' }}
                  alt="Antunes"
                />
              </Box>
              <Typography variant="h5" sx={{ mb: 2, color: '#003366', fontWeight: 'bold' }}>
                Antunes está analisando os discursos
              </Typography>

              {/* Barra de Progresso */}
              <Box sx={{ mb: 3 }}>
                <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 1 }}>
                  <Typography variant="body2" color="text.secondary">
                    {progresso.mensagem || 'Iniciando processamento...'}
                  </Typography>
                  <Typography variant="body2" sx={{ color: '#003366', fontWeight: 'bold' }}>
                    {progresso.processados}/{progresso.total}
                  </Typography>
                </Box>
                <LinearProgress
                  variant={progresso.total > 0 ? "determinate" : "indeterminate"}
                  value={progresso.total > 0 ? (progresso.processados / progresso.total) * 100 : 0}
                  sx={{
                    height: 10,
                    borderRadius: 5,
                    backgroundColor: '#e0e0e0',
                    '& .MuiLinearProgress-bar': {
                      backgroundColor: '#009739'
                    }
                  }}
                />
                <Typography variant="caption" color="text.secondary" sx={{ mt: 0.5, display: 'block' }}>
                  {progresso.total > 0 ? `${((progresso.processados / progresso.total) * 100).toFixed(1)}% concluído` : 'Iniciando...'}
                </Typography>
              </Box >

              <Grid container spacing={2} sx={{ mb: 3 }}>
                <Grid item xs={12} md={6}>
                  <Card elevation={1} sx={{ backgroundColor: '#fff' }}>
                    <CardContent>
                      <Typography variant="body2" color="text.secondary">
                        📊 Total de Discursos
                      </Typography>
                      <Typography variant="h3" sx={{ color: '#003366', fontWeight: 'bold' }}>
                        {progresso.total || discursos.length}
                      </Typography>
                      {progresso.total_original && progresso.total_original > progresso.total && (
                        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5 }}>
                          de {progresso.total_original} totais na comissão (Top {progresso.total})
                        </Typography>
                      )}
                    </CardContent>
                  </Card>
                </Grid>

                <Grid item xs={12} md={6}>
                  <Card elevation={1} sx={{ backgroundColor: '#fff' }}>
                    <CardContent>
                      <Typography variant="body2" color="text.secondary">
                        ✅ Já Processados
                      </Typography>
                      <Typography variant="h3" sx={{ color: '#009739', fontWeight: 'bold' }}>
                        {progresso.processados}
                      </Typography>
                    </CardContent>
                  </Card>
                </Grid>
              </Grid>

              {
                progresso.total_lotes > 0 && (
                  <Alert severity="info" sx={{ mb: 2 }}>
                    📦 Lote {progresso.lote_atual}/{progresso.total_lotes} em processamento
                  </Alert>
                )
              }

              <Typography variant="body2" color="text.secondary" sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 1, mt: 2, mb: 1 }}>
                <CircularProgress size={16} color="inherit" />
                Tempo de processamento: <strong>{Math.floor(tempoDecorrido / 60)}:{(tempoDecorrido % 60).toString().padStart(2, '0')}</strong>
              </Typography>

              {/* Aviso para datasets grandes e Amostragem */}
              {
                progresso.total_original && progresso.total_original > progresso.total ? (
                  <Alert severity="success" sx={{ mb: 2, backgroundColor: '#e8f5e9', color: '#1b5e20', border: '1px solid #7bc886' }}>
                    <Typography variant="body2" sx={{ fontWeight: 'bold', display: 'flex', alignItems: 'center' }}>
                      🧠 Otimização Semântica Ativada ({Math.round((progresso.total / progresso.total_original) * 100)}% do acervo lido)
                    </Typography>
                    <Typography variant="caption" sx={{ mt: 0.5, display: 'block' }}>
                      Para garantir uma análise profunda e praticamente instantânea, o robô interceptou e processará apenas os {progresso.total} discursos mais densos, longos e estruturados do Deputado neste período (filtrados de um poço inútil de {progresso.total_original} falas brutas, rejeitando resmungos de plenário como "simplesmente", "peço a palavra", etc).
                    </Typography>
                  </Alert>
                ) : progresso.total > 1000 && (
                  <Alert severity="info" sx={{ mb: 2 }}>
                    <Typography variant="body2" sx={{ fontWeight: 'bold' }}>
                      📊 Dataset Grande Detectado ({progresso.total} discursos)
                    </Typography>
                    <Typography variant="caption" sx={{ mt: 0.5, display: 'block' }}>
                      O sistema processará todos os discursos em lotes otimizados.
                      Tempo estimado: ~{Math.round((progresso.total / 50) * 30)} segundos
                    </Typography>
                  </Alert>
                )
              }

              {/* Informações detalhadas do progresso */}

            </Box >
          </Paper >
        )
        }


        {/* Resultados */}
        {
          relatorio && !loadingRelatorio && (
            <Box ref={relatorioRef} id="relatorio-para-impressao">
              {/* Título do Relatório */}
              <Box className="avoid-break" sx={{ textAlign: 'center', mb: 4, position: 'relative' }}>
                <Typography variant="h3" sx={{ color: '#003366', fontWeight: 'bold', mb: 1 }}>
                  Relatório de Atuação em Comissões
                </Typography>


              </Box>

              {/* Cabeçalho do Relatório com Informações do Parlamentar */}
              {dadosParlamentar && (
                <Paper elevation={3} sx={{ p: 4, mb: 4, bgcolor: '#FFFFFF', borderRadius: 4, border: '1px solid #e0e0e0' }} className="avoid-break">
                  <Grid container spacing={3} alignItems="center">
                    
                    {/* Foto do Parlamentar */}
                    <Grid item xs={12} md={2} sx={{ display: 'flex', justifyContent: 'center' }}>
                      <Avatar
                        src={dadosParlamentar.urlFoto || `https://www.camara.leg.br/internet/deputado/bandep/${dadosParlamentar.id}.jpg`}
                        referrerPolicy="no-referrer"
                        sx={{
                          width: 140,
                          height: 140,
                          border: `4px solid #009739`,
                          boxShadow: '0 4px 12px rgba(0,0,0,0.1)'
                        }}
                      >
                         {dadosParlamentar.nome ? dadosParlamentar.nome.charAt(0) : ''}
                      </Avatar>
                    </Grid>

                    {/* Nome e Selos */}
                    <Grid item xs={12} md={7}>
                      <Box>
                        <Typography variant="h3" fontWeight="bold" sx={{ color: '#003366', letterSpacing: '-0.5px' }}>
                          {dadosParlamentar.nome || parlamentarSelecionado || "Nome não disponível"}
                        </Typography>
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, mt: 2 }}>
                          <Chip
                            avatar={<Avatar 
                              src={getPartidoLogo(partidoSelecionado !== 'Todos' ? partidoSelecionado : dadosParlamentar?.partido, dadosParlamentar?.urlPartido)} 
                            />}
                            label={partidoSelecionado !== 'Todos' ? partidoSelecionado : (dadosParlamentar?.partido || 'N/D')}
                            sx={{
                              bgcolor: '#E8F5E9',
                              color: '#2E7D32',
                              fontWeight: 'bold',
                              px: 0.5,
                              fontSize: '0.9rem'
                            }}
                          />
                          <Chip
                            avatar={<Avatar 
                              src={getEstadoBandeira(estadoSelecionado !== 'Todos' ? estadoSelecionado : (dadosParlamentar?.uf || dadosParlamentar?.estado), dadosParlamentar?.urlEstado)} 
                            />}
                            label={estadoSelecionado !== 'Todos' ? estadoSelecionado : (dadosParlamentar?.uf || dadosParlamentar?.estado || 'N/D')}
                            sx={{
                              bgcolor: '#E3F2FD',
                              color: '#1565C0',
                              fontWeight: 'bold',
                              px: 0.5,
                              fontSize: '0.9rem'
                            }}
                          />
                        </Box>
                        <Typography variant="body1" sx={{ mt: 1, color: '#444', fontWeight: 600 }}>
                          Comissão: {comissaoSelecionada}
                        </Typography>
                      </Box>
                    </Grid>

                    {/* Bloco Institucional à direita (Logos Grandes Sem Fundo) */}
                    <Grid item xs={12} md={3} sx={{ display: 'flex', justifyContent: { xs: 'center', md: 'flex-end' }, alignItems: 'center' }}>
                      <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2 }}>
                        
                        {(dadosParlamentar?.urlPartido || (partidoSelecionado && partidoSelecionado !== 'Todos') || dadosParlamentar?.partido) && (
                          <Box
                            component="img"
                            src={getPartidoLogo(partidoSelecionado !== 'Todos' ? partidoSelecionado : dadosParlamentar?.partido, dadosParlamentar?.urlPartido)}
                            alt="Logo Partido"
                            sx={{
                              height: 70,
                              width: 'auto',
                              maxWidth: 140,
                              objectFit: 'contain',
                              filter: 'drop-shadow(0 2px 4px rgba(0,0,0,0.1))'
                            }}
                          />
                        )}

                        {(dadosParlamentar?.urlEstado || (estadoSelecionado && estadoSelecionado !== 'Todos') || dadosParlamentar?.uf || dadosParlamentar?.estado) && (
                          <Box
                            component="img"
                            src={getEstadoBandeira(estadoSelecionado !== 'Todos' ? estadoSelecionado : (dadosParlamentar?.uf || dadosParlamentar?.estado), dadosParlamentar?.urlEstado)}
                            alt="Bandeira Estado"
                            sx={{
                              height: 40,
                              width: 'auto',
                              borderRadius: '4px',
                              boxShadow: '0 2px 8px rgba(0,0,0,0.15)'
                            }}
                          />
                        )}
                      </Box>
                    </Grid>
                  </Grid>
                </Paper>
              )}

              {/* Relatório Analítico */}
              <Paper elevation={3} sx={{ p: 4, mb: 4 }} className="section-container">
                {/* DEBUG */}
                <Box sx={{ display: 'none' }}>
                  {console.log('RELATORIO COMPLETO:', relatorio)}
                </Box>

                <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, mb: 3 }}>
                  <Typography variant="h5" sx={{ color: '#003366', fontWeight: 'bold' }}>
                    📝 Relatório de Atuação
                  </Typography>
                  <Chip
                    label="✨ Novo - Gerado agora"
                    size="small"
                    sx={{ backgroundColor: '#2196f3', color: '#fff', fontWeight: 'bold' }}
                  />
                </Box>



                {/* Texto do Relatório */}
                {/* Texto do Relatório */}
                <Box sx={{
                  '& p': { lineHeight: 1.8, textAlign: 'justify', mb: 2 },
                  '& h1, & h2, & h3': { color: '#003366', mt: 3, mb: 2 },
                  '& ul, & ol': { pl: 3, mb: 2 },
                  '& li': { mb: 1 }
                }}>
                  <ReactMarkdown>
                    {relatorio.relatorio_analitico}
                  </ReactMarkdown>
                </Box>
              </Paper>

              {/* Métricas Gerais */}
              <Grid container spacing={3} sx={{ mb: 4 }} className="section-container">
                <Grid item xs={12} md={4}>
                  <Card elevation={2} sx={{ height: '100%' }} className="card-container">
                    <CardContent>
                      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 1 }}>
                        <Typography variant="h6" color="text.secondary">
                          📊 Objetividade Média
                        </Typography>
                        <Tooltip title="Mede o grau de clareza, fundamentação e uso de dados/evidências nos discursos. 0 = subjetivo/opinativo, 10 = totalmente objetivo/factual" arrow>
                          <IconButton size="small" sx={{ color: '#666' }}>
                            <HelpOutlineIcon fontSize="small" />
                          </IconButton>
                        </Tooltip>
                      </Box>
                      <Typography variant="h4" sx={{ color: '#009739', fontWeight: 'bold' }}>
                        {relatorio.indices_gerais?.objetividade_media?.toFixed(1) || 'N/A'}/10
                      </Typography>
                    </CardContent>
                  </Card>
                </Grid>

                <Grid item xs={12} md={4}>
                  <Card elevation={2} sx={{ height: '100%' }}>
                    <CardContent>
                      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 1 }}>
                        <Typography variant="h6" color="text.secondary">
                          ⚡ Tensão Média
                        </Typography>
                        <Tooltip title="Mede o nível de confronto, crítica e embate político nos discursos. 0 = consensual/colaborativo, 10 = altamente confrontativo/combativo" arrow>
                          <IconButton size="small" sx={{ color: '#666' }}>
                            <HelpOutlineIcon fontSize="small" />
                          </IconButton>
                        </Tooltip>
                      </Box>
                      <Typography variant="h4" sx={{ color: '#ED8B00', fontWeight: 'bold' }}>
                        {relatorio.indices_gerais?.tensao_media?.toFixed(1) || 'N/A'}/10
                      </Typography>
                    </CardContent>
                  </Card>
                </Grid>



                <Grid item xs={12} md={4}>
                  <Card elevation={2} sx={{ height: '100%' }}>
                    <CardContent>
                      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 1 }}>
                        <Typography variant="h6" color="text.secondary">
                          📈 Participação
                        </Typography>
                        <Tooltip title="Avaliação da frequência e qualidade das intervenções. Alta = participação ativa e constante. Média = participação regular. Baixa = participação esporádica" arrow>
                          <IconButton size="small" sx={{ color: '#666' }}>
                            <HelpOutlineIcon fontSize="small" />
                          </IconButton>
                        </Tooltip>
                      </Box>
                      <Chip
                        label={(relatorio.avaliacao_geral?.participacao || 'N/A').toUpperCase()}
                        sx={{
                          backgroundColor: relatorio.avaliacao_geral?.participacao === 'alta' ? '#009739' :
                            relatorio.avaliacao_geral?.participacao === 'media' ? '#ED8B00' : '#999',
                          color: '#fff',
                          fontWeight: 'bold',
                          fontSize: '1rem',
                          mt: 1
                        }}
                      />
                    </CardContent>
                  </Card>
                </Grid>
              </Grid>

              {/* Gráficos Lado a Lado */}
              <Grid container spacing={4} sx={{ mb: 4 }}>
                <Grid item xs={12} md={6}>
                  <Paper elevation={3} sx={{ p: 3, height: '100%', minHeight: '500px', display: 'flex', flexDirection: 'column' }}>
                    <Box sx={{ display: 'flex', alignItems: 'center', mb: 2 }}>
                      <TrendingUpIcon sx={{ color: '#d32f2f', mr: 1 }} />
                      <Typography variant="h6" sx={{ color: '#003366', fontWeight: 'bold' }}>
                        Evolução Diária - Média de Objetividade e Tensão por Data
                      </Typography>
                    </Box>
                    <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 2 }}>
                      Cada ponto representa a média dos discursos naquele dia
                    </Typography>
                    <Box sx={{ flexGrow: 1, minHeight: '400px' }}>
                      <ReactECharts
                        option={getGraficoEvolucaoOptions()}
                        style={{ height: '100%', width: '100%' }}
                        opts={{ renderer: 'svg' }}
                      />
                    </Box>
                  </Paper>
                </Grid>

                <Grid item xs={12} md={6}>
                  <Paper elevation={3} sx={{ p: 3, height: '100%', minHeight: '500px', display: 'flex', flexDirection: 'column' }}>
                    <Box sx={{ display: 'flex', alignItems: 'center', mb: 2 }}>
                      <FolderOpenIcon sx={{ color: '#546e7a', mr: 1 }} />
                      <Typography variant="h6" sx={{ color: '#003366', fontWeight: 'bold' }}>
                        Distribuição por Categorias
                      </Typography>
                    </Box>
                    <Box sx={{ flexGrow: 1, minHeight: '400px', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                      {relatorio.temas_principais && Object.keys(relatorio.temas_principais).length > 0 ? (
                        <ReactECharts
                          option={getGraficoCategoriasOptions()}
                          style={{ height: '100%', width: '100%' }}
                          opts={{ renderer: 'svg' }}
                        />
                      ) : (
                        <Typography variant="body2" color="text.secondary">
                          Dados insuficientes para gerar gráfico de categorias
                        </Typography>
                      )}
                    </Box>
                  </Paper>
                </Grid>
              </Grid>

              {/* Temas Principais */}
              {
                relatorio.temas_principais && Object.keys(relatorio.temas_principais).length > 0 && (
                  <Paper elevation={3} sx={{ p: 4, mb: 4 }}>
                    <Typography variant="h5" sx={{ color: '#003366', fontWeight: 'bold', mb: 3 }}>
                      🎯 Temas Principais
                    </Typography>
                    <Grid container spacing={3}>
                      {Object.entries(relatorio.temas_principais).map(([tema, dados]) => (
                        <Grid item xs={12} md={6} key={tema}>
                          <Card elevation={1}>
                            <CardContent>
                              <Typography variant="h6" sx={{ color: '#009739', mb: 1, textTransform: 'capitalize' }}>
                                {tema.replace(/_/g, ' ')}
                              </Typography>
                              <Box sx={{ display: 'flex', gap: 1, mb: 2 }}>
                                <Chip label={`Frequência: ${dados.frequencia}`} size="small" />
                                <Chip
                                  label={`Relevância: ${dados.relevancia_comissao}`}
                                  size="small"
                                  sx={{
                                    backgroundColor: dados.relevancia_comissao === 'alta' ? '#009739' : '#ED8B00',
                                    color: '#fff'
                                  }}
                                />

                              </Box>
                              {dados.exemplos && dados.exemplos.length > 0 && (
                                <Box>
                                  <Typography variant="body2" sx={{ fontWeight: 'bold', mb: 1 }}>
                                    Exemplos:
                                  </Typography>
                                  {dados.exemplos.map((ex, idx) => (
                                    <Typography key={idx} variant="body2" sx={{ fontStyle: 'italic', mb: 0.5 }}>
                                      • "{ex}"
                                    </Typography>
                                  ))}
                                </Box>
                              )}
                            </CardContent>
                          </Card>
                        </Grid>
                      ))}
                    </Grid>
                  </Paper>
                )
              }

              {/* Nuvem de Palavras (Bigramas) */}
              {
                relatorio.bigramas_frequentes && relatorio.bigramas_frequentes.length > 0 && (
                  <Paper elevation={3} sx={{ p: 4, mb: 4 }} className="avoid-break">
                    <Typography variant="h5" sx={{ color: '#003366', fontWeight: 'bold', mb: 3 }}>
                      ☁️ Termos Mais Frequentes (Bigramas)
                    </Typography>
                    <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 2, justifyContent: 'center', alignItems: 'center', p: 2 }}>
                      {relatorio.bigramas_frequentes.slice(0, 15).map((bg, idx) => {
                        // Tamanho baseado na frequência relativa
                        const maxFreq = relatorio.bigramas_frequentes[0].frequencia;
                        const size = 1 + (bg.frequencia / maxFreq) * 2.5; // Aumentado para dar mais destaque

                        // Cores variadas do tema
                        const colors = ['#003366', '#009739', '#ED8B00', '#005b9f', '#007c2e', '#b56b00'];
                        const color = colors[idx % colors.length]; // Ciclar cores para consistência visual

                        return (
                          <Typography
                            key={idx}
                            component="span"
                            sx={{
                              fontSize: `${size}rem`,
                              color: color,
                              fontWeight: 'bold',
                              cursor: 'default',
                              lineHeight: 1,
                              mx: 1, // Margem horizontal para espalhar
                              transition: 'all 0.3s ease',
                              '&:hover': {
                                transform: 'scale(1.2)',
                                zIndex: 10,
                                textShadow: '0px 2px 4px rgba(0,0,0,0.2)'
                              }
                            }}
                          >
                            {bg.bigrama}
                          </Typography>
                        );
                      })}
                    </Box>
                  </Paper>
                )
              }

              {/* Lista de Sessões Analisadas (Deduplicada e com Links Reais) */}
              {
                relatorio.sessoes_analisadas && relatorio.sessoes_analisadas.length > 0 ? (
                  <Paper elevation={3} sx={{ p: 4, mb: 4 }} className="avoid-break">
                    <Typography variant="h5" sx={{ color: '#003366', fontWeight: 'bold', mb: 3 }}>
                      📜 Sessões Analisadas
                    </Typography>
                    <Box sx={{ maxHeight: '400px', overflowY: 'auto' }}>
                      <ul style={{ listStyleType: 'none', padding: 0 }}>
                        {relatorio.sessoes_analisadas.map((sessao, idx) => (
                          <li key={idx} style={{ marginBottom: '10px', borderBottom: '1px solid #eee', paddingBottom: '10px' }}>
                            <Typography variant="body2">
                              <strong>{sessao.data}</strong> - Sessão {sessao.sessao} -{' '}
                              <a
                                href={sessao.link}
                                target="_blank"
                                rel="noopener noreferrer"
                                style={{ color: '#009739', textDecoration: 'none', fontWeight: 'bold' }}
                              >
                                {sessao.sessao} (Ver na Câmara)
                              </a>
                            </Typography>
                          </li>
                        ))}
                      </ul>
                    </Box>
                  </Paper>
                ) : (
                  // Fallback para versão antiga (se necessário)
                  relatorio.analise_discursos && relatorio.analise_discursos.length > 0 && (
                    <Paper elevation={3} sx={{ p: 4, mb: 4 }} className="avoid-break">
                      <Typography variant="h5" sx={{ color: '#003366', fontWeight: 'bold', mb: 3 }}>
                        📜 Sessões Analisadas
                      </Typography>
                      <Typography variant="body2" color="text.secondary">
                        (Detalhes disponíveis na próxima atualização)
                      </Typography>
                    </Paper>
                  )
                )
              }

              {/* Botão Exportar PDF (Rodapé) */}
              {relatorio && (
                <Box sx={{ mt: 4, mb: 4, textAlign: 'center', '@media print': { display: 'none' } }}>
                  <Button
                    variant="contained"
                    size="large"
                    startIcon={<PrintIcon />}
                    onClick={() => window.print()}
                    sx={{
                      backgroundColor: '#009739',
                      '&:hover': { backgroundColor: '#003366' },
                      px: 4,
                      py: 1.5
                    }}
                  >
                    Exportar PDF
                  </Button>
                
      <DataSourceFooter
        sources={[{"label":"Notas Taquigráficas — Câmara","href":"https://dadosabertos.camara.leg.br/swagger/api.html#api-Eventos","type":"camara"},{"label":"Discursos — Portal da Câmara","href":"https://www.camara.leg.br","type":"camara"}]}
        note="Discursos extraídos das notas taquigráficas oficiais da Câmara dos Deputados (2023–2026). Análise qualitativa gerada por IA — verificar nos registros originais."
      />
    </Box>
              )}

              {/* Mensagem inicial */}
              {
                !relatorio && !loading && !error && (
                  <Paper elevation={2} sx={{ p: 6, textAlign: 'center', backgroundColor: '#f5f5f5' }}>
                    <AccountBalanceIcon sx={{ fontSize: 80, color: '#003366', mb: 2 }} />
                    <Typography variant="h5" sx={{ color: '#003366', mb: 2 }}>
                      Selecione os filtros acima
                    </Typography>
                    <Typography variant="body1" color="text.secondary">
                      Escolha um estado, partido, parlamentar e comissão para visualizar a análise detalhada
                    </Typography>
                  </Paper>
                )
              }
            </Box >
          )
        }
      </Container >
    </>
  );
}

export default AtuacaoComissoes;
