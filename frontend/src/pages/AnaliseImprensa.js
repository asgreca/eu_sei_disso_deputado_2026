import React, { useEffect, useMemo, useState } from 'react';
import {
  Box,
  Container,
  Typography,
  Paper,
  Grid,
  Button,
  CircularProgress,
  Alert,
  Stack,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Chip,
  Tooltip,
  Divider,
  LinearProgress,
} from '@mui/material';
import {
  Newspaper as NewspaperIcon,
  Refresh as RefreshIcon,
  Assessment as AssessmentIcon,
  SentimentSatisfiedAlt as SentimentSatisfiedIcon,
  SentimentDissatisfied as SentimentNegativeIcon,
  SentimentNeutral as SentimentNeutralIcon,
  ContentCopy as ContentCopyIcon,
  PictureAsPdf as PictureAsPdfIcon,
} from '@mui/icons-material';
import axios from '../config/axios';
import ReactECharts from 'echarts-for-react';
import FilterSelector from '../components/FilterSelector';

const defaultSelectValue = 'Selecione...';

const brandPalette = {
  azul: '#003366',
  azulClaro: '#1F4E79',
  verde: '#009739',
  verdeClaro: '#2BB673',
  laranja: '#ED8B00',
  amarelo: '#FFF81C',
  cinzaClaro: '#F3F6FA',
  cinzaMedio: '#DDE3EB',
  cinzaTexto: '#5F6A7D',
  branco: '#FFFFFF',
};

const metricCardsConfig = [
  {
    key: 'total_noticias',
    label: 'Total de Notícias',
    icon: <AssessmentIcon sx={{ color: brandPalette.azul, fontSize: 28 }} />,
  },
  {
    key: 'positivo',
    label: 'Sentimento Positivo',
    icon: <SentimentSatisfiedIcon sx={{ color: brandPalette.verde, fontSize: 28 }} />,
  },
  {
    key: 'negativo',
    label: 'Sentimento Negativo',
    icon: <SentimentNegativeIcon sx={{ color: brandPalette.laranja, fontSize: 28 }} />,
  },
  {
    key: 'neutro',
    label: 'Sentimento Neutro',
    icon: <SentimentNeutralIcon sx={{ color: brandPalette.amarelo, fontSize: 28 }} />,
  },
];

const AnaliseImprensa = () => {
  const [filtros, setFiltros] = useState({
    estado: 'Todos',
    partido: 'Todos',
    parlamentar: ''
  });

  const parlamentarSelecionado = filtros.parlamentar || '';
  const partidoSelecionado = filtros.partido || 'Todos';
  const estadoSelecionado = filtros.estado || 'Todos';

  const [loadingFiltros, setLoadingFiltros] = useState(false);
  const [loadingAnalise, setLoadingAnalise] = useState(false);
  const [loadingRelatorio, setLoadingRelatorio] = useState(false);

  const [analise, setAnalise] = useState(null);
  const [relatorioIA, setRelatorioIA] = useState(null);

  const [erro, setErro] = useState(null);
  const [erroRelatorio, setErroRelatorio] = useState(null);
  const [mensagemCopia, setMensagemCopia] = useState(null);

  /**
   * Carrega lista de estados ao iniciar
   */
  const onFiltersChange = (newFilters) => {
    setFiltros(prev => ({ ...prev, ...newFilters }));
  };

  const dadosCarregados = Boolean(analise && !analise.error);

  const intensidadeMedia = useMemo(() => {
    if (!analise?.metrics?.intensidade_media) return '0,0';
    return Number(analise.metrics.intensidade_media)
      .toFixed(2)
      .replace('.', ',');
  }, [analise]);

  const periodoCobertura = useMemo(() => {
    if (!analise?.metrics?.periodo_cobertura) return 'N/A';
    const dias = analise.metrics.periodo_cobertura;
    if (dias <= 0) return 'N/A';
    if (dias < 30) return `${dias} dia(s)`;
    const meses = Math.round(dias / 30);
    return `${meses} mês(es)`;
  }, [analise]);

  const opcoesSentimento = useMemo(() => {
    if (!analise?.sentiment_distribution) return null;

    const dados = Object.entries(analise.sentiment_distribution).map(([nome, valor]) => ({
      name: nome,
      value: valor,
    }));

    return {
      color: [brandPalette.verde, brandPalette.laranja, brandPalette.azulClaro],
      tooltip: {
        trigger: 'item',
        formatter: '{b}: {c} ({d}%)',
      },
      legend: {
        top: 'bottom',
        textStyle: { color: brandPalette.cinzaTexto },
      },
      series: [
        {
          type: 'pie',
          radius: ['35%', '70%'],
          avoidLabelOverlap: false,
          itemStyle: {
            borderRadius: 10,
            borderColor: brandPalette.branco,
            borderWidth: 3,
          },
          label: {
            color: brandPalette.azul,
            formatter: '{b}\n{d}%',
            fontWeight: 600,
          },
          labelLine: {
            smooth: true,
          },
          data: dados,
        },
      ],
    };
  }, [analise]);

  const opcoesTemporal = useMemo(() => {
    if (!analise?.temporal_evolution?.dates?.length) return null;

    const { dates, series } = analise.temporal_evolution;
    const cores = {
      positivo: brandPalette.verde,
      negativo: brandPalette.laranja,
      neutro: brandPalette.azulClaro,
    };

    return {
      tooltip: {
        trigger: 'axis',
        backgroundColor: brandPalette.branco,
        borderColor: brandPalette.cinzaMedio,
        borderWidth: 1,
        textStyle: { color: brandPalette.azul },
      },
      legend: {
        top: 10,
        textStyle: { color: brandPalette.cinzaTexto },
      },
      grid: { left: '3%', right: '3%', bottom: '3%', containLabel: true },
      xAxis: {
        type: 'category',
        data: dates,
        boundaryGap: false,
        axisLabel: { color: brandPalette.cinzaTexto },
        axisLine: { lineStyle: { color: brandPalette.cinzaMedio } },
      },
      yAxis: {
        type: 'value',
        axisLabel: { color: brandPalette.cinzaTexto },
        splitLine: { lineStyle: { color: brandPalette.cinzaMedio, type: 'dashed' } },
      },
      series: Object.entries(series).map(([sentimento, valores]) => ({
        name: sentimento,
        type: 'line',
        smooth: true,
        symbol: 'circle',
        symbolSize: 10,
        data: valores,
        lineStyle: { width: 3, color: cores[sentimento] ?? brandPalette.azul },
        itemStyle: { color: cores[sentimento] ?? brandPalette.azul },
        areaStyle: {
          opacity: 0.08,
          color: cores[sentimento] ?? brandPalette.azul,
        },
      })),
    };
  }, [analise]);

  const opcoesCategorias = useMemo(() => {
    if (!analise?.categories_distribution) return null;

    const categorias = Object.keys(analise.categories_distribution);
    if (!categorias.length) return null;

    const valores = Object.values(analise.categories_distribution);

    return {
      color: [brandPalette.azul],
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
      },
      grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
      xAxis: {
        type: 'category',
        data: categorias,
        axisLabel: {
          color: brandPalette.cinzaTexto,
          rotate: 20,
        },
        axisLine: { lineStyle: { color: brandPalette.cinzaMedio } },
      },
      yAxis: {
        type: 'value',
        axisLabel: { color: brandPalette.cinzaTexto },
        splitLine: { lineStyle: { color: brandPalette.cinzaMedio, type: 'dashed' } },
      },
      series: [
        {
          name: 'Notícias',
          type: 'bar',
          data: valores,
          barWidth: '45%',
          itemStyle: {
            borderRadius: [8, 8, 0, 0],
            color: (params) => {
              const palette = [
                brandPalette.azul,
                brandPalette.azulClaro,
                brandPalette.verde,
                brandPalette.verdeClaro,
                brandPalette.laranja,
              ];
              return palette[params.dataIndex % palette.length];
            },
          },
        },
      ],
    };
  }, [analise]);

  const executarAnalise = async () => {
    const parlamentarValido =
      parlamentarSelecionado && parlamentarSelecionado !== defaultSelectValue;

    if (!parlamentarValido) {
      setErro('Selecione um parlamentar para executar a análise.');
      return;
    }

    setLoadingAnalise(true);
    setErro(null);
    setAnalise(null);
    setRelatorioIA(null);
    setErroRelatorio(null);

    try {
      const params = {};
      if (filtros.estado !== 'Todos') params.estado = filtros.estado;
      if (filtros.partido !== 'Todos') params.partido = filtros.partido;
      if (filtros.parlamentar) params.parlamentar = filtros.parlamentar;

      const { data } = await axios.get('/api/imprensa/analise', { params });

      if (data?.error) {
        setErro(data.error);
        return;
      }

      setAnalise(data);
    } catch (error) {
      console.error('Erro ao executar análise de imprensa:', error);
      setErro('Erro ao executar análise. Tente novamente.');
    } finally {
      setLoadingAnalise(false);
    }
  };

  const gerarRelatorioIA = async () => {
    if (!analise) return;

    setLoadingRelatorio(true);
    setErroRelatorio(null);
    setRelatorioIA(null);

    try {
      const payload = {
        estado: filtros.estado !== 'Todos' ? filtros.estado : null,
        partido: filtros.partido !== 'Todos' ? filtros.partido : null,
        parlamentar:
          filtros.parlamentar ? filtros.parlamentar : null,
        noticias: analise.noticias ?? [],
        metrics: analise.metrics ?? {},
      };

      const { data } = await axios.post('/api/llm/imprensa-report', payload);

      if (data?.error) {
        setErroRelatorio(data.error);
        return;
      }

      setRelatorioIA(data?.report ?? null);
    } catch (error) {
      console.error('Erro ao gerar relatório IA:', error);
      setErroRelatorio('Erro ao gerar relatório com IA. Tente novamente.');
    } finally {
      setLoadingRelatorio(false);
    }
  };

  const copiarRelatorio = async () => {
    if (!relatorioIA) return;
    try {
      const tmp = document.createElement('div');
      tmp.innerHTML = relatorioIA;
      const texto = tmp.innerText;
      await navigator.clipboard.writeText(texto);
      setMensagemCopia('Relatório copiado para a área de transferência.');
      setTimeout(() => setMensagemCopia(null), 4000);
    } catch (error) {
      console.error('Erro ao copiar relatório:', error);
      setMensagemCopia('Não foi possível copiar o relatório. Copie manualmente.');
      setTimeout(() => setMensagemCopia(null), 4000);
    }
  };

  const gerarPDFPlaceholder = () => {
    window.print();
  };

  const limparAnalise = () => {
    setFiltros({
      estado: 'Todos',
      partido: 'Todos',
      parlamentar: ''
    });
  };

  const formatarDataMMYYYY = (dataISO) => {
    if (!dataISO) return 'N/A';
    const data = new Date(dataISO);
    if (Number.isNaN(data.getTime())) return 'N/A';
    const mes = String(data.getMonth() + 1).padStart(2, '0');
    const ano = data.getFullYear();
    return `${mes}/${ano}`;
  };

  const noticiasNormalizadas = useMemo(() => {
    if (!analise?.noticias?.length) return [];
    return analise.noticias.map((noticia) => ({
      ...noticia,
      data_formatada: formatarDataMMYYYY(noticia.data),
    }));
  }, [analise]);

  const hasMetricas = Boolean(analise?.metrics);

  return (
    <Container maxWidth="xl" sx={{ py: 4 }}>
      <Box sx={{ mb: 4, backgroundColor: 'white', p: 3, borderRadius: '16px', display: 'flex', alignItems: 'center', gap: 4 }}>
        <Box sx={{ flex: 1 }}>
          <Typography
            variant="h3"
            component="h1"
            sx={{
              color: brandPalette.azul,
              fontWeight: 700,
              mb: 2,
              display: 'flex',
              alignItems: 'center',
              gap: 2,
              fontFamily: 'Montserrat, sans-serif',
            }}
          >
            <NewspaperIcon sx={{ fontSize: 40, color: brandPalette.verde }} />
            Análise de Imprensa - Potencial Midiático
          </Typography>
          <Typography
            variant="h6"
            sx={{ color: brandPalette.cinzaTexto, fontFamily: 'Inter, sans-serif' }}
          >
            Monitoramento de notícias e percepção midiática dos parlamentares
          </Typography>
        </Box>
        <Box
          component="img"
          src="/Analise_de_Imprensa.png"
          alt="Ilustração Análise de Imprensa"
          sx={{
            maxHeight: '220px',
            width: 'auto',
            borderRadius: '8px',
            display: { xs: 'none', md: 'block' }
          }}
        />
      </Box>

      <Paper
        elevation={3}
        sx={{
          p: 3,
          mb: 4,
          backgroundColor: brandPalette.cinzaClaro,
          borderRadius: 3,
        }}
      >
        <Typography variant="h5" sx={{ color: brandPalette.azul, fontWeight: 700, mb: 2 }}>
          🎯 Filtros de Análise de Imprensa
        </Typography>
        <Divider sx={{ mb: 3 }} />
        {loadingFiltros && <LinearProgress sx={{ mb: 2 }} />}
        <FilterSelector 
          onFiltersChange={onFiltersChange}
          fields={['estado', 'partido', 'parlamentar']}
          useCurrentParty={true}
        />
        <Stack
          direction={{ xs: 'column', md: 'row' }}
          spacing={2}
          sx={{ mt: 3 }}
          alignItems="center"
        >
          <Button
            variant="contained"
            startIcon={<NewspaperIcon />}
            onClick={executarAnalise}
            disabled={
              loadingAnalise ||
              !filtros.parlamentar
            }
            sx={{
              backgroundColor: brandPalette.verde,
              '&:hover': { backgroundColor: '#007a2e' },
              minWidth: 220,
            }}
          >
            {loadingAnalise ? (
              <CircularProgress size={24} sx={{ color: brandPalette.branco }} />
            ) : (
              'Executar Análise'
            )}
          </Button>
          <Tooltip title="Limpar resultados">
            <span>
              <Button
                variant="outlined"
                color="primary"
                startIcon={<RefreshIcon />}
                onClick={limparAnalise}
                disabled={loadingAnalise}
              >
                Limpar
              </Button>
            </span>
          </Tooltip>
        </Stack>
      </Paper>

      {erro && (
        <Alert severity="warning" sx={{ mb: 4 }}>
          {erro}
        </Alert>
      )}

      {dadosCarregados && (
        <Paper elevation={2} sx={{ p: 3, mb: 4, borderRadius: 3 }}>
          <Grid container spacing={3} alignItems="center">
            <Grid item xs={12} md={6}>
              <Typography variant="h5" sx={{ color: brandPalette.azul, fontWeight: 700 }}>
                {analise.info_parlamentar?.nome}
              </Typography>
              <Typography variant="subtitle1" sx={{ color: brandPalette.cinzaTexto, mb: 2 }}>
                {analise.info_parlamentar?.estado} • {analise.info_parlamentar?.partido}
              </Typography>
              <Stack direction="row" spacing={1}>
                <Chip
                  label={`Período analisado: ${periodoCobertura}`}
                  color="primary"
                  variant="outlined"
                />
                <Chip
                  label={`Intensidade média: ${intensidadeMedia}`}
                  color="primary"
                  variant="outlined"
                />
              </Stack>
            </Grid>
            <Grid item xs={12} md={6}>
              <Stack
                direction="row"
                spacing={2}
                justifyContent={{ xs: 'flex-start', md: 'flex-end' }}
                alignItems="center"
              >
                {analise.info_parlamentar?.foto ? (
                  <Box
                    component="img"
                    src={analise.info_parlamentar.foto}
                    alt={`Foto de ${analise.info_parlamentar.nome}`}
                    sx={{
                      width: 120,
                      height: 120,
                      borderRadius: '12px',
                      objectFit: 'cover',
                      border: `3px solid ${brandPalette.azul}`,
                    }}
                  />
                ) : (
                  <Box
                    sx={{
                      width: 120,
                      height: 120,
                      borderRadius: '12px',
                      border: `2px dashed ${brandPalette.azul}`,
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      color: brandPalette.cinzaTexto,
                    }}
                  >
                    Sem foto
                  </Box>
                )}
                {analise.info_parlamentar?.logoPartido && (
                  <Box
                    component="img"
                    src={analise.info_parlamentar.logoPartido}
                    alt={`Logo ${analise.info_parlamentar.partido}`}
                    sx={{ width: 80, height: 80, objectFit: 'contain' }}
                  />
                )}
                {analise.info_parlamentar?.bandeiraEstado && (
                  <Box
                    component="img"
                    src={analise.info_parlamentar.bandeiraEstado}
                    alt={`Bandeira ${analise.info_parlamentar.estado}`}
                    sx={{ width: 80, height: 80, objectFit: 'contain' }}
                  />
                )}
              </Stack>
            </Grid>
          </Grid>
        </Paper>
      )}

      {dadosCarregados && hasMetricas && (
        <Box sx={{ mb: 4 }}>
          <Grid container spacing={3}>
            {metricCardsConfig.map((card) => (
              <Grid item xs={12} sm={6} md={3} key={card.key}>
                <Paper
                  elevation={2}
                  sx={{
                    p: 3,
                    borderRadius: 3,
                    bgcolor: brandPalette.branco,
                    borderLeft: `6px solid ${brandPalette.verde}`,
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 1,
                    height: '100%',
                  }}
                >
                  <Stack direction="row" spacing={2} alignItems="center">
                    <Box
                      sx={{
                        width: 48,
                        height: 48,
                        borderRadius: '12px',
                        backgroundColor: `${brandPalette.verde}1A`,
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                      }}
                    >
                      {card.icon}
                    </Box>
                    <Box>
                      <Typography variant="subtitle2" sx={{ color: brandPalette.cinzaTexto }}>
                        {card.label}
                      </Typography>
                      <Typography variant="h5" sx={{ fontWeight: 700, color: brandPalette.azul }}>
                        {analise.metrics[card.key] ?? 0}
                      </Typography>
                    </Box>
                  </Stack>
                </Paper>
              </Grid>
            ))}
          </Grid>
        </Box>
      )}

      {dadosCarregados && opcoesSentimento && (
        <Box sx={{ mb: 4 }}>
          <Typography variant="h5" sx={{ color: brandPalette.azul, fontWeight: 'bold', mb: 2 }}>
            📊 Distribuição de Sentimentos
          </Typography>
          <Typography variant="body2" sx={{ color: brandPalette.cinzaTexto, mb: 2 }}>
            Participação relativa das notícias positivas, negativas e neutras sobre o parlamentar.
          </Typography>
          <Paper sx={{ p: 3, borderRadius: 3, backgroundColor: brandPalette.branco }}>
            <ReactECharts option={opcoesSentimento} style={{ height: 360 }} />
          </Paper>
        </Box>
      )}

      {dadosCarregados && opcoesTemporal && (
        <Box sx={{ mb: 4 }}>
          <Typography variant="h5" sx={{ color: brandPalette.azul, fontWeight: 'bold', mb: 2 }}>
            📈 Evolução Temporal dos Sentimentos
          </Typography>
          <Typography variant="body2" sx={{ color: brandPalette.cinzaTexto, mb: 2 }}>
            Tendência do tom das notícias ao longo do tempo.
          </Typography>
          <Paper sx={{ p: 3, borderRadius: 3, backgroundColor: brandPalette.branco }}>
            <ReactECharts option={opcoesTemporal} style={{ height: 380 }} />
          </Paper>
        </Box>
      )}

      {dadosCarregados && opcoesCategorias && (
        <Box sx={{ mb: 4 }}>
          <Typography variant="h5" sx={{ color: brandPalette.azul, fontWeight: 'bold', mb: 2 }}>
            📂 Principais Categorias de Notícias
          </Typography>
          <Typography variant="body2" sx={{ color: brandPalette.cinzaTexto, mb: 2 }}>
            Temas mais recorrentes na cobertura midiática.
          </Typography>
          <Paper sx={{ p: 3, borderRadius: 3, backgroundColor: brandPalette.branco }}>
            <ReactECharts option={opcoesCategorias} style={{ height: 380 }} />
          </Paper>
        </Box>
      )}

      {dadosCarregados && analise?.graph && Array.isArray(analise.graph.nodes) && analise.graph.nodes.length > 0 && (
        <Box sx={{ mb: 4 }}>
          <Typography variant="h5" sx={{ color: brandPalette.azul, fontWeight: 'bold', mb: 2 }}>
            🔗 Gráfico de Relações - Veículos, Temas e Parlamentares
          </Typography>
          <Typography variant="body2" sx={{ color: brandPalette.cinzaTexto, mb: 2 }}>
            Visualização das conexões entre o parlamentar, veículos de comunicação, temas abordados e co-parlamentares nas notícias.
          </Typography>
          <Paper sx={{ p: 3, borderRadius: 3, backgroundColor: brandPalette.branco, overflow: 'hidden' }}>
            <ReactECharts
              option={{
                title: {
                  text: '🔗 Rede de Difusão: Parlamentar, Fontes e Sentimento',
                  left: 'center',
                  top: 10,
                  textStyle: { color: brandPalette.azul, fontWeight: 'bold', fontSize: 16 }
                },
                tooltip: {
                  trigger: 'item',
                  backgroundColor: 'rgba(255, 255, 255, 0.98)',
                  borderColor: brandPalette.azul,
                  borderWidth: 2,
                  padding: 10,
                  formatter: (params) => {
                    if (params.dataType === 'node') {
                      return `<div style="text-align:center"><b style="font-size:14px">${params.data.name}</b><br/><span style="color:#666">${params.data.category || 'Node'}</span></div>`;
                    }
                    return '';
                  }
                },
                legend: {
                  data: (analise.graph.categories || []).map(c => c.name),
                  bottom: 10,
                  textStyle: { color: brandPalette.cinzaTexto }
                },
                series: [
                  {
                    type: 'graph',
                    layout: 'force',
                    roam: true,
                    label: {
                      show: true,
                      position: 'right',
                      fontSize: 10,
                      color: brandPalette.azul,
                      fontWeight: 'bold',
                      backgroundColor: 'rgba(255, 255, 255, 0.95)',
                      borderColor: brandPalette.azul,
                      borderWidth: 1,
                      borderRadius: 4,
                      padding: [4, 8]
                    },
                    itemStyle: {
                      borderColor: '#fff',
                      borderWidth: 2,
                      shadowBlur: 10,
                      shadowColor: '#999',
                      borderRadius: '50%'
                    },
                    lineStyle: {
                      color: '#aaa',
                      curveness: 0.1,
                      opacity: 0.5,
                      width: 1.5
                    },
                    emphasis: {
                      lineStyle: {
                        width: 3,
                        color: brandPalette.verde,
                        opacity: 1
                      },
                      itemStyle: {
                        borderWidth: 3,
                        borderColor: brandPalette.verde,
                        shadowBlur: 20,
                        shadowColor: brandPalette.verde,
                        borderRadius: '50%'
                      },
                      label: {
                        show: true,
                        fontSize: 12
                      }
                    },
                    data: (analise.graph.nodes || []).map(node => ({
                      ...node,
                      symbolSize: node.symbolSize || [30, 30],
                      label: {
                        show: true,
                        position: 'bottom'
                      }
                    })),
                    links: (analise.graph.links || []).map(link => ({
                      ...link,
                      lineStyle: {
                        ...link.lineStyle,
                        opacity: link.lineStyle?.opacity || 0.4,
                        width: link.lineStyle?.width || 1.5
                      }
                    })),
                    categories: analise.graph.categories || [],
                    force: {
                      repulsion: 150,
                      gravity: 0.1,
                      edgeLength: [150, 250],
                      layoutAnimation: true,
                      friction: 0.6
                    }
                  }
                ]
              }}
              style={{ height: '650px', width: '100%' }}
              opts={{ renderer: 'svg' }}
            />
          </Paper>
        </Box>
      )}

      {dadosCarregados && (
        <Box sx={{ mb: 4 }}>
          <Stack direction={{ xs: 'column', md: 'row' }} spacing={2} alignItems="center" mb={2}>
            <Typography variant="h5" sx={{ color: brandPalette.azul, fontWeight: 'bold' }}>
              🤖 Relatório de Análise Midiática
            </Typography>
            <Box sx={{ flexGrow: 1 }} />
            {!relatorioIA ? (
              <Button
                variant="contained"
                onClick={gerarRelatorioIA}
                disabled={loadingRelatorio}
                startIcon={!loadingRelatorio && <Box component="img" src="/antunes_icon.png" sx={{ width: 24, height: 24, borderRadius: '50%' }} />}
                sx={{
                  backgroundColor: brandPalette.azul,
                  '&:hover': { backgroundColor: brandPalette.azulClaro },
                  minWidth: 200,
                }}
              >
                {loadingRelatorio ? (
                  <CircularProgress size={24} sx={{ color: brandPalette.branco }} />
                ) : (
                  'Gerar Relatório com Antunes'
                )}
              </Button>
            ) : (
              <Stack direction={{ xs: 'column', md: 'row' }} spacing={2}>
                <Button
                  variant="outlined"
                  startIcon={<ContentCopyIcon />}
                  onClick={copiarRelatorio}
                >
                  Copiar relatório
                </Button>
                <Button
                  variant="outlined"
                  startIcon={<PictureAsPdfIcon />}
                  onClick={gerarPDFPlaceholder}
                >
                  Gerar PDF
                </Button>
              </Stack>
            )}
          </Stack>
          {mensagemCopia && (
            <Alert severity="info" sx={{ mb: 2 }}>
              {mensagemCopia}
            </Alert>
          )}
          {erroRelatorio && (
            <Alert severity="warning" sx={{ mb: 2 }}>
              {erroRelatorio}
            </Alert>
          )}
          {relatorioIA && (
            <Paper sx={{ p: 4, borderRadius: 3, backgroundColor: brandPalette.branco }}>
              <Box
                sx={{
                  '& h1': {
                    color: brandPalette.azul,
                    borderBottom: `3px solid ${brandPalette.verde}`,
                    paddingBottom: '10px',
                    marginBottom: '20px',
                    fontSize: '1.8rem',
                    fontWeight: 'bold',
                  },
                  '& h2': {
                    color: brandPalette.azul,
                    marginTop: '30px',
                    marginBottom: '15px',
                    fontSize: '1.4rem',
                    fontWeight: 'bold',
                  },
                  '& p': {
                    marginBottom: '15px',
                    textAlign: 'justify',
                    color: '#333',
                    lineHeight: 1.8,
                  },
                  '& ul': {
                    marginLeft: '20px',
                    marginBottom: '25px',
                  },
                  '& li': {
                    marginBottom: '10px',
                    color: '#333',
                    lineHeight: 1.6,
                  },
                  '& strong': {
                    color: brandPalette.azul,
                    fontWeight: 'bold',
                  },
                  fontFamily: 'Inter, sans-serif',
                  lineHeight: 1.6,
                  color: '#333',
                }}
                dangerouslySetInnerHTML={{ __html: relatorioIA }}
              />
            </Paper>
          )}
        </Box>
      )}

      {dadosCarregados && noticiasNormalizadas.length > 0 && (
        <Box sx={{ mb: 4 }}>
          <Typography variant="h5" sx={{ color: brandPalette.azul, fontWeight: 'bold', mb: 2 }}>
            📰 Todas as Notícias Coletadas
          </Typography>
          <Typography variant="body2" sx={{ color: brandPalette.cinzaTexto, mb: 2 }}>
            Total de {noticiasNormalizadas.length} notícias analisadas.
          </Typography>
          <Paper sx={{ borderRadius: 3, backgroundColor: brandPalette.branco, overflow: 'hidden' }}>
            <Box sx={{ overflowX: 'auto', maxHeight: '520px' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead>
                  <tr style={{ backgroundColor: brandPalette.azul, color: brandPalette.branco }}>
                    <th style={{ padding: '12px', textAlign: 'left', fontWeight: 600 }}>Data</th>
                    <th style={{ padding: '12px', textAlign: 'left', fontWeight: 600 }}>Título</th>
                    <th style={{ padding: '12px', textAlign: 'left', fontWeight: 600 }}>Sentimento</th>
                    <th style={{ padding: '12px', textAlign: 'left', fontWeight: 600 }}>Categoria</th>
                    <th style={{ padding: '12px', textAlign: 'center', fontWeight: 600 }}>Link</th>
                  </tr>
                </thead>
                <tbody>
                  {noticiasNormalizadas.map((noticia, index) => (
                    <tr
                      key={`${noticia.titulo}-${index}`}
                      style={{ borderBottom: `1px solid ${brandPalette.cinzaMedio}` }}
                    >
                      <td style={{ padding: '12px', color: brandPalette.cinzaTexto }}>
                        {noticia.data_formatada}
                      </td>
                      <td
                        style={{
                          padding: '12px',
                          maxWidth: '420px',
                          wordWrap: 'break-word',
                          color: brandPalette.azul,
                          fontWeight: 600,
                        }}
                      >
                        {noticia.titulo || 'N/A'}
                      </td>
                      <td style={{ padding: '12px', color: brandPalette.cinzaTexto }}>
                        {noticia.tom_da_noticia === 'positivo' && '😊 Positivo'}
                        {noticia.tom_da_noticia === 'negativo' && '😞 Negativo'}
                        {noticia.tom_da_noticia === 'neutro' && '😐 Neutro'}
                        {!['positivo', 'negativo', 'neutro'].includes(noticia.tom_da_noticia) &&
                          (noticia.tom_da_noticia || 'N/A')}
                      </td>
                      <td style={{ padding: '12px', color: brandPalette.cinzaTexto }}>
                        {noticia.categoria || 'N/A'}
                      </td>
                      <td style={{ padding: '12px', textAlign: 'center' }}>
                        {noticia.link ? (
                          <a
                            href={noticia.link}
                            target="_blank"
                            rel="noopener noreferrer"
                            style={{
                              color: brandPalette.verde,
                              textDecoration: 'underline',
                              fontWeight: 'bold',
                            }}
                          >
                            Abrir notícia
                          </a>
                        ) : (
                          'N/A'
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Box>
          </Paper>
        </Box>
      )}

      {!loadingAnalise && !dadosCarregados && !erro && (
        <Paper sx={{ p: 6, textAlign: 'center', borderRadius: 3 }}>
          <Typography variant="h6" sx={{ color: brandPalette.cinzaTexto }}>
            Selecione um parlamentar e execute a análise para visualizar os resultados.
          </Typography>
        </Paper>
      )}
    </Container>
  );
};

export default AnaliseImprensa;
