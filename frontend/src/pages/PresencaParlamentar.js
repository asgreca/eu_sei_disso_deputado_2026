import React, { useState, useEffect } from 'react';
import {
  Box,
  Typography,
  Container,
  Paper,
  Grid,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Button,
  Card,
  CardContent,
  CircularProgress,
  Alert,
  Avatar,
  Chip,
  Divider,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Tooltip,
  IconButton,
  TextField,
} from '@mui/material';
import {
  EventAvailable as EventAvailableIcon,
  EventBusy as EventBusyIcon,
  Assessment as AssessmentIcon,
  TrendingUp as TrendingUpIcon,
  TrendingDown as TrendingDownIcon,
  Remove as RemoveIcon,
  HelpOutline as HelpOutlineIcon,
  Psychology as PsychologyIcon,
} from '@mui/icons-material';
import ReactECharts from 'echarts-for-react';
import ReactMarkdown from 'react-markdown';
import api from '../config/axios';
import { API_BASE_URL, API_KEY } from '../config';
import { PARTIDO_LOGOS_FALLBACK } from '../utils/logos';
import DataSourceFooter from '../components/DataSourceFooter';

// O axios já está configurado no arquivo ../config/api.js

const ESTADOS_FALLBACK = [
  'AC', 'AL', 'AM', 'AP', 'BA', 'CE', 'DF', 'ES', 'GO', 'MA', 'MG', 'MS', 'MT',
  'PA', 'PB', 'PE', 'PI', 'PR', 'RJ', 'RN', 'RO', 'RR', 'RS', 'SC', 'SE', 'SP', 'TO'
];

// Configurações de Marca (Manual de Marca)
const BRAND = {
  colors: {
    green: '#009739',
    yellow: '#FFF81C',
    blue: '#003366',
    white: '#FFFFFF',
    gray: '#666666',
    blueLight: '#4F81BD',
    greenLight: '#66BB6A',
    grayLight: '#E0E0E0',
    orangeDark: '#ED8B00',
    orangeLight: '#FFB74D',
  },
  typography: {
    titles: "'Montserrat', sans-serif",
    body: "'Inter', sans-serif",
    data: "'Roboto Mono', monospace",
  },
  borderRadius: '16px', // Curvas de Brasília
};

function PresencaParlamentar() {
  // Estados para filtros
  const [estados, setEstados] = useState([]);
  const [partidos, setPartidos] = useState([]);
  const [parlamentares, setParlamentares] = useState([]);
  const [comissoes, setComissoes] = useState([]);

  const [filtros, setFiltros] = useState({
    estado: 'Todos',
    partido: 'Todos',
    parlamentar: 'Todos',
    comissao: 'Todas',
    tipoComissao: 'Todas',
    dataInicio: '2023-01-01',
    dataFim: new Date().toISOString().split('T')[0],
  });

  // Loadings granulares por filtro
  const [loadingEstados, setLoadingEstados] = useState(false);
  const [loadingPartidos, setLoadingPartidos] = useState(false);
  const [loadingParlamentares, setLoadingParlamentares] = useState(false);
  const [loadingComissoes, setLoadingComissoes] = useState(false);

  // Dados do parlamentar
  const [dadosParlamentar, setDadosParlamentar] = useState(null);
  const [dadosPresenca, setDadosPresenca] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [loadingAnalise, setLoadingAnalise] = useState(false);
  const [analiseLLM, setAnaliseLLM] = useState(null);
  const [carregandoPeriodo, setCarregandoPeriodo] = useState(false);

  useEffect(() => {
    carregarEstados();
  }, []);

  useEffect(() => {
    if (filtros.estado !== 'Todos') {
      carregarPartidos(filtros.estado);
    } else {
      setPartidos([]);
      setFiltros(prev => ({ ...prev, partido: 'Todos', parlamentar: 'Todos', comissao: 'Todas' }));
    }
  }, [filtros.estado]);

  useEffect(() => {
    if (filtros.partido !== 'Todos' && filtros.estado !== 'Todos') {
      carregarParlamentares(filtros.estado, filtros.partido);
    } else {
      setParlamentares([]);
      setFiltros(prev => ({ ...prev, parlamentar: 'Todos', comissao: 'Todas' }));
    }
  }, [filtros.partido]);

  // Limpar dados e carregar comissões quando parlamentar mudar
  useEffect(() => {
    if (filtros.parlamentar !== 'Todos') {
      // Limpar dados anteriores quando mudar o parlamentar
      setDadosPresenca(null);
      setDadosParlamentar(null);
      // Resetar comissão para "Todas"
      setFiltros(prev => ({ ...prev, comissao: 'Todas' }));
      // Carregar comissões automaticamente
      carregarComissoes();
    } else {
      setDadosPresenca(null);
      setDadosParlamentar(null);
      setComissoes([]);
      setFiltros(prev => ({ ...prev, comissao: 'Todas' }));
    }
  }, [filtros.parlamentar, filtros.estado, filtros.partido]);

  // NÃO recarregar automaticamente quando a comissão mudar
  // O filtro só será aplicado quando o usuário clicar no botão "Buscar Dados de Presença"

  const axiosConfig = {
    headers: {
      'Cache-Control': 'no-cache',
      'Pragma': 'no-cache',
    }
  };

  const carregarEstados = async () => {
    setLoadingEstados(true);
    try {
      const response = await api.get(`/api/filtros/estados?_t=${Date.now()}`, axiosConfig);
      setEstados(response.data.estados || ESTADOS_FALLBACK);
    } catch (err) {
      console.error('Erro ao carregar estados:', err);
      setEstados(ESTADOS_FALLBACK);
    } finally {
      setLoadingEstados(false);
    }
  };

  const carregarPartidos = async (estado) => {
    setLoadingPartidos(true);
    try {
      const response = await api.get(`/api/filtros/partidos?estado=${estado}&atual=true&_t=${Date.now()}`, axiosConfig);
      setPartidos(response.data.partidos || []);
    } catch (err) {
      console.error('Erro ao carregar partidos:', err);
      setPartidos([]);
    } finally {
      setLoadingPartidos(false);
    }
  };

  const carregarParlamentares = async (estado, partido) => {
    setLoadingParlamentares(true);
    try {
      const response = await api.get(
        `/api/filtros/parlamentares?estado=${estado}&partido_atual=${partido}&_t=${Date.now()}`,
        axiosConfig
      );
      const rawList = response.data.parlamentares || [];
      setParlamentares(rawList.map(p => typeof p === 'object' ? (p.nome || p) : p));
    } catch (err) {
      console.error('Erro ao carregar parlamentares:', err);
      setParlamentares([]);
    } finally {
      setLoadingParlamentares(false);
    }
  };

  // Função auxiliar para processar e atualizar comissões
  const processarComissoes = (comissoesData) => {
    if (comissoesData && Array.isArray(comissoesData) && comissoesData.length > 0) {
      // Normalizar dados para garantir formato de objeto
      const comissoesNormalizadas = comissoesData.map(c => {
        if (typeof c === 'string') {
          // Tentar extrair dados da string antiga se necessário (fallback)
          return { id: c, nome: c, tipo: 'Desconhecido', label: c };
        }
        return {
          ...c,
          label: `${c.nome} (${c.tipo})` // Label para display interno se precisar
        };
      });

      setComissoes(comissoesNormalizadas);
      return true;
    } else {
      console.log('⚠️ Array de comissões vazio ou inválido');
      setComissoes([]);
      return false;
    }
  };

  // Função para carregar apenas as comissões (sem dados completos)
  const carregarComissoes = async () => {
    if (filtros.parlamentar === 'Todos') {
      setComissoes([]);
      return;
    }

    setLoadingComissoes(true);
    try {
      const params = {
        parlamentar: filtros.parlamentar,
        _t: Date.now()
      };

      if (filtros.estado !== 'Todos') {
        params.estado = filtros.estado;
      }
      if (filtros.partido !== 'Todos') {
        params.partido = filtros.partido;
      }
      // Sempre carregar sem filtro de comissão para pegar todas

      console.log('📤 Carregando lista de comissões...');
      const response = await api.get('/api/presenca/analise', { params, ...axiosConfig });

      if (response.data.error) {
        console.error('Erro ao carregar comissões:', response.data.error);
        setComissoes(['Todas']);
        return;
      }

      // Processar apenas as comissões
      if (response.data.comissoes) {
        processarComissoes(response.data.comissoes);
      } else {
        setComissoes(['Todas']);
      }
    } catch (err) {
      console.error('Erro ao carregar comissões:', err);
      setComissoes(['Todas']);
    } finally {
      setLoadingComissoes(false);
    }
  };

  const handleComissaoPresencaChange = async (novaComissao) => {
    setFiltros(prev => ({ ...prev, comissao: novaComissao }));
    if (novaComissao === 'Todas' || !novaComissao || filtros.parlamentar === 'Todos') return;
    try {
      setCarregandoPeriodo(true);
      const resp = await api.get('/api/presenca/periodo', {
        params: { parlamentar: filtros.parlamentar, comissao: novaComissao }
      });
      if (resp.data?.tem_dados) {
        setFiltros(prev => ({
          ...prev,
          comissao: novaComissao,
          dataInicio: resp.data.data_inicio,
          dataFim: resp.data.data_fim,
        }));
      }
    } catch (err) {
      console.warn('Não foi possível buscar período de presença:', err);
    } finally {
      setCarregandoPeriodo(false);
    }
  };

  const carregarDadosPresenca = async (forcarSemFiltroComissao = false) => {
    if (filtros.parlamentar === 'Todos') return;

    // Limpar estados anteriores (resetar IA e Gráficos)
    setDadosPresenca({ presencas: [], detalhamento_mensal: [], comparativa: {} });
    setAnaliseLLM(null); // <--- Reset do texto da IA
    setLoading(true);
    setError(null);

    try {
      const params = {
        parlamentar: filtros.parlamentar,
        data_inicio: filtros.dataInicio,
        data_fim: filtros.dataFim,
        _t: Date.now()
      };

      if (filtros.estado !== 'Todos') {
        params.estado = filtros.estado;
      }
      if (filtros.partido !== 'Todos') {
        params.partido = filtros.partido;
      }
      // Aplicar filtro de comissão se uma comissão específica foi selecionada
      // Quando forçar sem filtro (primeira carga), não enviar comissão para pegar todas
      if (!forcarSemFiltroComissao && filtros.comissao && filtros.comissao !== 'Todas') {
        params.comissao = filtros.comissao;
        console.log('📤 Aplicando filtro de comissão:', filtros.comissao);
      } else {
        console.log('📤 Carregando todas as comissões (sem filtro específico)');
      }

      const response = await api.get('/api/presenca/analise', { params, ...axiosConfig });

      if (response.data.error) {
        setError(response.data.error);
        setDadosPresenca(null);
        setLoading(false);
        return;
      }

      // Atualizar dados - isso vai atualizar as métricas automaticamente
      console.log('📊 Atualizando dadosPresenca com métricas:', response.data.metricas);
      setDadosPresenca(response.data);
      setDadosParlamentar(response.data.parlamentar);

      // Atualizar lista de comissões disponíveis (caso tenha mudado)
      if (response.data.comissoes) {
        processarComissoes(response.data.comissoes);
      }

    } catch (err) {
      console.error('Erro ao carregar dados de presença:', err);
      const errorMessage = err.response?.data?.detail || err.response?.data?.error || err.message || 'Erro ao carregar dados de presença. Tente novamente.';
      setError(errorMessage);
      setDadosPresenca(null);
    } finally {
      setLoading(false);
    }
  };

  const gerarAnaliseLLM = async () => {
    if (!dadosPresenca || filtros.parlamentar === 'Todos') {
      setError('Selecione um parlamentar primeiro.');
      return;
    }

    setLoadingAnalise(true);
    setError(null);

    try {
      // Determinar comissão para análise
      let comissaoAnalise = filtros.comissao;

      // Se estiver em "Todas", tentar encontrar a comissão com mais ausências
      if (comissaoAnalise === 'Todas' && dadosPresenca.presencas && dadosPresenca.presencas.length > 0) {
        // Encontrar comissão com mais ausências
        const comissaoComMaisAusencias = dadosPresenca.presencas
          .map(c => ({
            ...c,
            ausencias: c.reunioes - c.presencas
          }))
          .sort((a, b) => b.ausencias - a.ausencias)[0];

        if (comissaoComMaisAusencias && comissaoComMaisAusencias.ausencias > 0) {
          // Encontrar o objeto da comissão correspondente pelo ID
          const comissaoEncontrada = dadosPresenca.comissoes.find(c => String(c.id) === String(comissaoComMaisAusencias.id_orgao));
          if (comissaoEncontrada) {
            comissaoAnalise = String(comissaoEncontrada.id);
          }
        }
      }

      // Buscar discursos da comissão
      const params = {
        parlamentar: filtros.parlamentar,
        comissao: comissaoAnalise,
        _t: Date.now()
      };

      const response = await api.post('/api/llm/presenca-reunioes-faltadas', {
        parlamentar: filtros.parlamentar,
        comissao: comissaoAnalise,
        estado: filtros.estado,
        partido: filtros.partido,
        data_inicio: filtros.dataInicio,
        data_fim: filtros.dataFim,
        percentual_presenca: dadosPresenca?.metricas?.presenca_geral,
        media_comissao: dadosPresenca?.detalhes_comissao?.media_comissao
      }, axiosConfig);

      setAnaliseLLM(response.data);
    } catch (err) {
      console.error('Erro ao gerar análise LLM:', err);
      setError('Erro ao gerar análise. Tente novamente.');
    } finally {
      setLoadingAnalise(false);
    }
  };

  const formatarPercentual = (valor) => {
    if (valor === null || valor === undefined || isNaN(valor)) return 'N/A';
    return `${valor.toFixed(1)}%`;
  };

  const getGraficoEvolucaoMensalOptions = () => {
    if (!dadosPresenca || !dadosPresenca.evolucao_mensal || dadosPresenca.evolucao_mensal.length === 0) {
      return {};
    }

    const meses = dadosPresenca.evolucao_mensal.map(item => item.mes);
    const presencas = dadosPresenca.evolucao_mensal.map(item => item.presencas);
    const ausencias = dadosPresenca.evolucao_mensal.map(item => item.ausencias);

    // Preparar dados com bordas arredondadas
    const presencasData = presencas.map((val, idx) => ({
      value: val,
      itemStyle: {
        borderRadius: [0, 0, 20, 20]
      }
    }));

    const ausenciasData = ausencias.map((val, idx) => ({
      value: val,
      itemStyle: {
        borderRadius: [20, 20, 0, 0]
      }
    }));

    return {
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
        formatter: function (params) {
          let result = `${params[0].name}<br/>`;
          params.forEach(param => {
            result += `${param.seriesName}: ${param.value}<br/>`;
          });
          return result;
        }
      },
      legend: {
        data: ['Presenças', 'Ausências'],
        top: '5%'
      },
      grid: {
        left: '3%',
        right: '4%',
        bottom: '3%',
        containLabel: true
      },
      xAxis: {
        type: 'category',
        data: meses,
        axisLabel: {
          rotate: 45,
          interval: 0
        }
      },
      yAxis: {
        type: 'value',
        name: 'Quantidade de Sessões',
        nameLocation: 'middle',
        nameGap: 50
      },
      series: [
        {
          name: 'Presenças',
          type: 'bar',
          stack: 'presenca',
          data: dadosPresenca.evolucao_mensal.map(item => item.presencas),
          itemStyle: { color: BRAND.colors.green }
        },
        {
          name: 'Ausências',
          type: 'bar',
          stack: 'presenca',
          data: dadosPresenca.evolucao_mensal.map(item => item.ausencias),
          itemStyle: { color: BRAND.colors.orangeDark } // Substituindo vermelho por laranja escuro
        }
      ]
    };
  };

  const getGraficoComparativoMediaOptions = () => {
    if (!dadosPresenca || !dadosPresenca.detalhes_comissao) return {};
    const { media_comissao } = dadosPresenca.detalhes_comissao;
    const presencaParlamentar = dadosPresenca.metricas.presenca_geral;

    return {
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
        formatter: '{b}: {c}%'
      },
      grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
      xAxis: { type: 'value', max: 100, axisLabel: { formatter: '{value}%' } },
      yAxis: { type: 'category', data: ['Média da Comissão', 'Sua Presença'] },
      series: [
        {
          name: 'Presença (%)',
          type: 'bar',
          data: [
            { value: parseFloat(media_comissao.toFixed(1)), itemStyle: { color: BRAND.colors.gray } },
            { value: parseFloat(presencaParlamentar.toFixed(1)), itemStyle: { color: presencaParlamentar >= media_comissao ? BRAND.colors.green : BRAND.colors.orangeDark } }
          ],
          label: { show: true, position: 'right', formatter: '{c}%' }
        }
      ]
    };
  };

  const getGraficoCalendarioOptions = () => {
    if (!dadosPresenca || !dadosPresenca.detalhes_comissao || !dadosPresenca.detalhes_comissao.calendario || dadosPresenca.detalhes_comissao.calendario.length === 0) {
      return {};
    }
    const { calendario, range_inicio, range_fim } = dadosPresenca.detalhes_comissao;

    const data = calendario.map(item => [item.data, item.status === 'Presente' ? 1 : 0]);

    // Usar o range retornado pelo backend ou calcular a partir dos dados
    const range = (range_inicio && range_fim) ? [range_inicio, range_fim] : new Date().getFullYear().toString();

    return {
      tooltip: {
        formatter: function (params) {
          const dateParts = params.value[0].split('-');
          const dataFormatada = `${dateParts[2]}/${dateParts[1]}/${dateParts[0]}`;
          return dataFormatada + ': ' + (params.value[1] === 1 ? 'Presente' : 'Ausente');
        }
      },
      visualMap: {
        show: false,
        min: 0,
        max: 1,
        inRange: {
          color: [BRAND.colors.orangeDark, BRAND.colors.green] // Substituindo vermelho por laranja escuro
        }
      },
      calendar: {
        top: 30,
        left: 30,
        right: 30,
        cellSize: ['auto', 13],
        range: range,
        itemStyle: { borderWidth: 0.5 },
        yearLabel: { show: false },
        dayLabel: { nameMap: ['Dom', 'Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb'] },
        monthLabel: { nameMap: 'pt' }
      },
      series: {
        type: 'heatmap',
        coordinateSystem: 'calendar',
        data: data
      }
    };
  };

  const getGraficoDiaSemanaOptions = () => {
    if (!dadosPresenca || !dadosPresenca.detalhes_comissao || !dadosPresenca.detalhes_comissao.dia_semana) return {};
    const { dia_semana } = dadosPresenca.detalhes_comissao;

    const dias = Object.keys(dia_semana);
    const presencas = dias.map(d => dia_semana[d].presencas);
    const ausencias = dias.map(d => dia_semana[d].total - dia_semana[d].presencas);

    return {
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
      legend: { bottom: 0 },
      grid: { left: '3%', right: '4%', bottom: '15%', containLabel: true },
      xAxis: { type: 'category', data: dias },
      yAxis: { type: 'value' },
      series: [
        { name: 'Presenças', type: 'bar', stack: 'total', data: presencas, itemStyle: { color: BRAND.colors.green } },
        { name: 'Ausências', type: 'bar', stack: 'total', data: ausencias, itemStyle: { color: BRAND.colors.orangeDark } }
      ]
    };
  };

  const getGraficoTipoComissaoOptions = () => {
    if (!dadosPresenca || !dadosPresenca.presenca_por_tipo || dadosPresenca.presenca_por_tipo.length === 0) {
      return {};
    }

    return {
      tooltip: {
        trigger: 'item',
        formatter: '{b}: {c} ({d}%)'
      },
      legend: {
        bottom: '5%',
        left: 'center'
      },
      series: [
        {
          name: 'Tipo de Comissão',
          type: 'pie',
          radius: ['40%', '70%'],
          avoidLabelOverlap: false,
          itemStyle: {
            borderRadius: 10,
            borderColor: '#fff',
            borderWidth: 2
          },
          label: {
            show: false,
            position: 'center'
          },
          emphasis: {
            label: {
              show: true,
              fontSize: '18',
              fontWeight: 'bold'
            }
          },
          labelLine: {
            show: false
          },
          data: dadosPresenca.presenca_por_tipo.map(item => ({
            value: item.presencas,
            name: item.tipo
          }))
        }
      ]
    };
  };

  const getGraficoTopComissoesOptions = () => {
    if (!dadosPresenca || !dadosPresenca.ranking_comissoes || dadosPresenca.ranking_comissoes.length === 0) {
      return {};
    }

    // Pegar top 5 comissões (ou todas se menos de 5)
    const topComissoes = dadosPresenca.ranking_comissoes.slice(0, 5);
    const nomes = topComissoes.map(c => c.nome.length > 20 ? c.nome.substring(0, 20) + '...' : c.nome);
    const percentuais = topComissoes.map(c => parseFloat(c.percentual.toFixed(1)));

    return {
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
        formatter: '{b}: {c}%'
      },
      grid: {
        left: '3%',
        right: '4%',
        bottom: '3%',
        containLabel: true
      },
      xAxis: {
        type: 'value',
        max: 100,
        axisLabel: {
          formatter: '{value}%'
        }
      },
      yAxis: {
        type: 'category',
        data: nomes,
        inverse: true // Para mostrar o maior no topo
      },
      series: [
        {
          name: 'Presença (%)',
          type: 'bar',
          data: percentuais,
          itemStyle: {
            color: function (params) {
              const val = params.value;
              if (val >= 90) return BRAND.colors.green;
              if (val >= 70) return BRAND.colors.yellow;
              return BRAND.colors.orangeDark;
            },
            borderRadius: [0, 5, 5, 0]
          },
          label: {
            show: true,
            position: 'right',
            formatter: '{c}%'
          }
        }
      ]
    };
  };

  const separarComissoesPorTipo = (comissoes) => {
    const plenario = comissoes.filter(c => c.id_orgao === '0' || c.tipo === 'Plenário');
    const permanentes = comissoes.filter(c =>
      c.tipo && c.tipo.includes('Permanente') && !c.tipo.includes('Não')
    );
    const naoPermanentes = comissoes.filter(c =>
      c.tipo && c.tipo.includes('Não Permanente')
    );

    return { plenario, permanentes, naoPermanentes };
  };

const normalizeWikiUrl = (url) => {
    if (!url || typeof url !== 'string') return url;
    if (url.includes('flagcdn.com') || url.includes('Special:FilePath')) return url;
    const match = url.match(/wikipedia\/(?:commons|pt)\/(?:thumb\/)?(?:[a-f0-9]\/[a-f0-9]{2}\/)?([^\/]+)(?:\/\d+px-[^\/]+)?$/i);
    if (match && match[1]) {
      return `https://commons.wikimedia.org/wiki/Special:FilePath/${match[1]}?width=150`;
    }
    return url;
  };

  const getPartidoLogo = (partido, urlOriginal) => {
    const fallback = partido ? PARTIDO_LOGOS_FALLBACK[partido.trim().toUpperCase()] : null;
    return normalizeWikiUrl(fallback || urlOriginal);
  };

  const getEstadoLogo = (uf, urlOriginal) => {
    return normalizeWikiUrl(urlOriginal) || (uf ? `https://flagcdn.com/w160/br-${uf.toLowerCase()}.png` : "");
  };

  const SpinnerIcon = () => (
    <CircularProgress size={18} thickness={4} sx={{ mr: 1, color: 'inherit', opacity: 0.6 }} />
  );

  return (
    <Container maxWidth="xl" sx={{ py: 4, backgroundColor: '#F8F9FA', minHeight: '100vh', fontFamily: BRAND.typography.body }}>
      <Box sx={{ mb: 4, display: 'flex', alignItems: 'center', gap: 4, backgroundColor: 'white', p: 3, borderRadius: '16px' }}>
        <Avatar sx={{ bgcolor: BRAND.colors.blue, width: 56, height: 56, borderRadius: '12px' }}>
          <AssessmentIcon sx={{ fontSize: 32 }} />
        </Avatar>
        <Box sx={{ flex: 1 }}>
          <Typography variant="h4" sx={{ fontWeight: 700, color: BRAND.colors.blue, fontFamily: BRAND.typography.titles }}>
            Avaliação da Presença Parlamentar
          </Typography>
          <Typography variant="body1" color="text.secondary" sx={{ fontFamily: BRAND.typography.body }}>
            Acompanhe o histórico de presença do parlamentar em sessões do Plenário e em Comissões. Utilize os filtros para analisar o desempenho em órgãos específicos e gerar uma análise detalhada com Inteligência Artificial sobre as discussões perdidas em caso de ausência.
          </Typography>
        </Box>
        <Box
          component="img"
          src="/Avaliacao_da_Presenca_Parlamentar.png"
          alt="Ilustração Presença Parlamentar"
          sx={{
            maxHeight: '220px',
            width: 'auto',
            borderRadius: '8px',
            display: { xs: 'none', md: 'block' }
          }}
        />
      </Box>

      <Paper
        elevation={0}
        sx={{
          p: 3,
          mb: 4,
          borderRadius: BRAND.borderRadius,
          border: `1px solid ${BRAND.colors.grayLight}`,
          boxShadow: '0 4px 20px rgba(0,0,0,0.05)'
        }}
      >
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 3 }}>
          <TrendingUpIcon sx={{ color: BRAND.colors.blue }} />
          <Typography variant="h6" sx={{ fontWeight: 600, color: BRAND.colors.blue, fontFamily: BRAND.typography.titles }}>
            Filtros
          </Typography>
        </Box>

        <Grid container spacing={3}>
          <Grid item xs={12} sm={6} md={3}>
            <FormControl fullWidth>
              <InputLabel>Estado</InputLabel>
              <Select
                value={filtros.estado}
                label="Estado"
                onChange={(e) => setFiltros(prev => ({ ...prev, estado: e.target.value, partido: 'Todos', parlamentar: 'Todos', comissao: 'Todas' }))}
                disabled={loadingEstados}
                IconComponent={loadingEstados ? SpinnerIcon : undefined}
                sx={{ borderRadius: '12px' }}
              >
                <MenuItem value="Todos">Todos</MenuItem>
                {estados.map(estado => (
                  <MenuItem key={estado} value={estado}>{estado}</MenuItem>
                ))}
              </Select>
            </FormControl>
          </Grid>

          <Grid item xs={12} sm={6} md={3}>
            <FormControl fullWidth disabled={filtros.estado === 'Todos' || loadingPartidos}>
              <InputLabel>Partido</InputLabel>
              <Select
                value={filtros.partido}
                label="Partido"
                onChange={(e) => setFiltros(prev => ({ ...prev, partido: e.target.value, parlamentar: 'Todos', comissao: 'Todas' }))}
                disabled={filtros.estado === 'Todos' || loadingPartidos}
                IconComponent={loadingPartidos ? SpinnerIcon : undefined}
                sx={{ borderRadius: '12px' }}
              >
                <MenuItem value="Todos">Todos</MenuItem>
                {partidos.map(partido => (
                  <MenuItem key={partido} value={partido}>{partido}</MenuItem>
                ))}
              </Select>
            </FormControl>
          </Grid>

          <Grid item xs={12} sm={6} md={3}>
            <FormControl fullWidth disabled={filtros.partido === 'Todos' || loadingParlamentares}>
              <InputLabel>Parlamentar</InputLabel>
              <Select
                value={filtros.parlamentar}
                label="Parlamentar"
                onChange={(e) => setFiltros(prev => ({ ...prev, parlamentar: e.target.value, comissao: 'Todas' }))}
                disabled={filtros.partido === 'Todos' || loadingParlamentares}
                IconComponent={loadingParlamentares ? SpinnerIcon : undefined}
                sx={{ borderRadius: '12px' }}
              >
                <MenuItem value="Todos">Todos</MenuItem>
                {parlamentares.map(parlamentar => (
                  <MenuItem key={parlamentar} value={parlamentar}>{parlamentar}</MenuItem>
                ))}
              </Select>
            </FormControl>
          </Grid>

          <Grid item xs={12} sm={6} md={3}>
            <FormControl fullWidth disabled={filtros.parlamentar === 'Todos'}>
              <InputLabel>Tipo de Comissão</InputLabel>
              <Select
                value={filtros.tipoComissao}
                label="Tipo de Comissão"
                onChange={(e) => setFiltros(prev => ({ ...prev, tipoComissao: e.target.value, comissao: 'Todas' }))}
                sx={{ borderRadius: '12px' }}
              >
                <MenuItem value="Todas">Todas</MenuItem>
                <MenuItem value="Comissão Permanente">Comissão Permanente</MenuItem>
                <MenuItem value="Comissão Não Permanente">Comissão Não Permanente</MenuItem>
                <MenuItem value="Plenário">Plenário</MenuItem>
              </Select>
            </FormControl>
          </Grid>

          <Grid item xs={12} sm={6} md={3}>
            <FormControl fullWidth disabled={filtros.parlamentar === 'Todos' || loading || loadingComissoes}>
              <InputLabel>Comissão/Órgão</InputLabel>
              <Select
                value={filtros.comissao || 'Todas'}
                label="Comissão/Órgão"
                onChange={(e) => handleComissaoPresencaChange(e.target.value)}
                disabled={filtros.parlamentar === 'Todos' || loading || loadingComissoes}
                IconComponent={loadingComissoes ? SpinnerIcon : undefined}
                sx={{ borderRadius: '12px' }}
              >
                <MenuItem value="Todas">Todas</MenuItem>
                {comissoes && comissoes.length > 0 && comissoes
                  .filter(c => {
                    if (typeof c === 'string') return false;
                    if (filtros.tipoComissao === 'Todas') return true;
                    if (filtros.tipoComissao === 'Plenário') return c.tipo === 'Plenário' || String(c.id) === '0';
                    if (filtros.tipoComissao === 'Comissão Permanente') return c.tipo && c.tipo.includes('Permanente') && !c.tipo.includes('Não');
                    if (filtros.tipoComissao === 'Comissão Não Permanente') return c.tipo && c.tipo.includes('Não Permanente');
                    return true;
                  })
                  .map((comissao) => (
                    <MenuItem key={comissao.id} value={String(comissao.id)}>
                      {comissao.nome}
                    </MenuItem>
                  ))
                }
              </Select>
            </FormControl>
          </Grid>

          <Grid item xs={12} sm={6} md={3}>
            <TextField
              fullWidth
              label={carregandoPeriodo ? "⏳ Buscando período..." : "Data Início"}
              type="date"
              value={filtros.dataInicio}
              onChange={(e) => setFiltros(prev => ({ ...prev, dataInicio: e.target.value }))}
              InputLabelProps={{ shrink: true }}
              disabled={carregandoPeriodo}
              sx={{ '& .MuiOutlinedInput-root': { borderRadius: '12px' } }}
            />
          </Grid>

          <Grid item xs={12} sm={6} md={3}>
            <TextField
              fullWidth
              label={carregandoPeriodo ? "⏳ Buscando período..." : "Data Fim"}
              type="date"
              value={filtros.dataFim}
              onChange={(e) => setFiltros(prev => ({ ...prev, dataFim: e.target.value }))}
              InputLabelProps={{ shrink: true }}
              disabled={carregandoPeriodo}
              sx={{ '& .MuiOutlinedInput-root': { borderRadius: '12px' } }}
            />
          </Grid>

          <Grid item xs={12} md={3}>
            <Button
              variant="contained"
              onClick={() => carregarDadosPresenca()}
              disabled={filtros.parlamentar === 'Todos' || loading}
              sx={{
                mt: 1,
                py: 1.5,
                fontSize: '1rem',
                fontWeight: 'bold',
                backgroundColor: '#003366',
                '&:hover': {
                  backgroundColor: '#004080'
                }
              }}
              startIcon={loading ? <CircularProgress size={20} color="inherit" /> : <AssessmentIcon />}
            >
              {loading ? 'Carregando...' : '🔍 Buscar Dados de Presença'}
            </Button>
          </Grid>
        </Grid>
      </Paper>

      {error && (
        <Alert severity="error" sx={{ mb: 3 }} onClose={() => setError(null)}>
          {error}
        </Alert>
      )}

      {loading && (
        <Box sx={{ display: 'flex', justifyContent: 'center', my: 4 }}>
          <CircularProgress />
        </Box>
      )}

      {dadosPresenca && dadosParlamentar && !loading && (
        <>
          {/* Informações do Parlamentar (Modelo Limpo) */}
          <Paper elevation={3} sx={{ p: 4, mb: 4, bgcolor: '#FFFFFF', borderRadius: 4, border: '1px solid #e0e0e0' }}>
            <Grid container spacing={3} alignItems="center">
              <Grid item xs={12} md={2} sx={{ display: 'flex', justifyContent: 'center' }}>
                <Avatar
                  src={dadosParlamentar.foto}
                  alt={dadosParlamentar.nome}
                  sx={{
                    width: 140,
                    height: 140,
                    border: '4px solid #009739',
                    boxShadow: '0 4px 12px rgba(0,0,0,0.1)'
                  }}
                />
              </Grid>

              <Grid item xs={12} md={7}>
                <Box>
                  <Typography variant="h3" fontWeight="bold" sx={{ color: '#003366', letterSpacing: '-0.5px' }}>
                    {dadosParlamentar.nome}
                  </Typography>
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, mt: 2 }}>
                    <Chip
                      label={dadosParlamentar.partido}
                      sx={{
                        bgcolor: '#E8F5E9',
                        color: '#2E7D32',
                        fontWeight: 'bold',
                        px: 1,
                        fontSize: '0.9rem'
                      }}
                    />
                    <Chip
                      label={dadosParlamentar.estado}
                      sx={{
                        bgcolor: '#E3F2FD',
                        color: '#1565C0',
                        fontWeight: 'bold',
                        px: 1,
                        fontSize: '0.9rem'
                      }}
                    />
                  </Box>
                  <Typography variant="body1" sx={{ mt: 1, color: '#444', fontWeight: 600 }}>
                    Análise de Rubrica: 📊 Presença Parlamentar
                  </Typography>
                </Box>
              </Grid>

              <Grid item xs={12} md={3} sx={{ display: 'flex', justifyContent: { xs: 'center', md: 'flex-end' }, alignItems: 'center', gap: 2 }}>
                <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 1.5 }}>
                  {(dadosParlamentar.url_partido || dadosParlamentar.partido) && (
                    <Box
                      component="img"
                      src={getPartidoLogo(dadosParlamentar.partido, dadosParlamentar.url_partido)}
                      alt={dadosParlamentar.partido}
                      sx={{ height: 60, maxWidth: 100, objectFit: 'contain' }}
                    />
                  )}
                  {(dadosParlamentar.url_estado || dadosParlamentar.estado) && (
                    <Box
                      component="img"
                      src={getEstadoLogo(dadosParlamentar.estado, dadosParlamentar.url_estado)}
                      alt={dadosParlamentar.estado}
                      sx={{ height: 40, maxWidth: 60, objectFit: 'contain' }}
                    />
                  )}
                </Box>
              </Grid>
            </Grid>
          </Paper>
          {dadosPresenca && (
            <Box sx={{ mt: 4 }}>
              {/* Métricas Principais */}
              <Grid container spacing={3} sx={{ mb: 4 }}>
                <Grid item xs={12} md={4}>
                  <Card sx={{
                    height: '140px',
                    display: 'flex',
                    flexDirection: 'column',
                    justifyContent: 'center',
                    borderRadius: BRAND.borderRadius,
                    boxShadow: '0 4px 20px rgba(0,0,0,0.05)',
                    border: `1px solid ${BRAND.colors.grayLight}`,
                    backgroundColor: BRAND.colors.white
                  }}>
                    <CardContent sx={{ textAlign: 'center' }}>
                      <Typography variant="subtitle2" color="text.secondary" gutterBottom sx={{ fontWeight: 600, fontFamily: BRAND.typography.titles, textTransform: 'uppercase', letterSpacing: '0.5px' }}>
                        Presença Geral
                      </Typography>
                      <Typography variant="h3" sx={{ fontWeight: 700, color: BRAND.colors.green, fontFamily: BRAND.typography.data }}>
                        {formatarPercentual(dadosPresenca.metricas.presenca_geral)}
                      </Typography>
                      <Typography variant="caption" color="text.secondary" sx={{ fontFamily: BRAND.typography.body }}>
                        {filtros.comissao === 'Todas' ? 'Em todos os órgãos' : `Na ${comissoes.find(c => String(c.id) === filtros.comissao)?.nome || 'Comissão'}`}
                      </Typography>
                    </CardContent>
                  </Card>
                </Grid>
                <Grid item xs={12} md={4}>
                  <Card sx={{
                    height: '140px',
                    display: 'flex',
                    flexDirection: 'column',
                    justifyContent: 'center',
                    borderRadius: BRAND.borderRadius,
                    boxShadow: '0 4px 20px rgba(0,0,0,0.05)',
                    border: `1px solid ${BRAND.colors.grayLight}`,
                    backgroundColor: BRAND.colors.white
                  }}>
                    <CardContent sx={{ textAlign: 'center' }}>
                      <Typography variant="subtitle2" color="text.secondary" gutterBottom sx={{ fontWeight: 600, fontFamily: BRAND.typography.titles, textTransform: 'uppercase', letterSpacing: '0.5px' }}>
                        Sessões Participadas
                      </Typography>
                      <Typography variant="h3" sx={{ fontWeight: 700, color: BRAND.colors.blue, fontFamily: BRAND.typography.data }}>
                        {dadosPresenca.metricas.sessoes_participadas}
                      </Typography>
                      <Typography variant="caption" color="text.secondary" sx={{ fontFamily: BRAND.typography.body }}>
                        Sessões com presença registrada
                      </Typography>
                    </CardContent>
                  </Card>
                </Grid>
                <Grid item xs={12} md={4}>
                  <Card sx={{
                    height: '140px',
                    display: 'flex',
                    flexDirection: 'column',
                    justifyContent: 'center',
                    borderRadius: BRAND.borderRadius,
                    boxShadow: '0 4px 20px rgba(0,0,0,0.05)',
                    border: `1px solid ${BRAND.colors.grayLight}`,
                    backgroundColor: BRAND.colors.white
                  }}>
                    <CardContent sx={{ textAlign: 'center' }}>
                      <Typography variant="subtitle2" color="text.secondary" gutterBottom sx={{ fontWeight: 600, fontFamily: BRAND.typography.titles, textTransform: 'uppercase', letterSpacing: '0.5px' }}>
                        Sessões Realizadas
                      </Typography>
                      <Typography variant="h3" sx={{ fontWeight: 700, color: BRAND.colors.gray, fontFamily: BRAND.typography.data }}>
                        {dadosPresenca.metricas.sessoes_realizadas}
                      </Typography>
                      <Typography variant="caption" color="text.secondary" sx={{ fontFamily: BRAND.typography.body }}>
                        Total de sessões no período
                      </Typography>
                    </CardContent>
                  </Card>
                </Grid>
              </Grid>

              {/* Gráficos */}
              <Grid container spacing={3}>
                <Grid item xs={12}>
                  <Paper sx={{ p: 3, borderRadius: BRAND.borderRadius, border: `1px solid ${BRAND.colors.grayLight}`, boxShadow: '0 4px 20px rgba(0,0,0,0.05)' }}>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 2 }}>
                      <TrendingUpIcon sx={{ color: BRAND.colors.blue }} />
                      <Typography variant="h6" sx={{ fontWeight: 600, color: BRAND.colors.blue, fontFamily: BRAND.typography.titles }}>
                        Evolução Mensal de Presença {filtros.comissao !== 'Todas' && `(${comissoes.find(c => String(c.id) === filtros.comissao)?.nome})`}
                      </Typography>
                    </Box>
                    <ReactECharts option={getGraficoEvolucaoMensalOptions()} style={{ height: '400px' }} />
                  </Paper>
                </Grid>

                {filtros.comissao === 'Todas' ? (
                  <>
                    <Grid item xs={12} md={6}>
                      <Paper sx={{ p: 3, borderRadius: BRAND.borderRadius, border: `1px solid ${BRAND.colors.grayLight}`, boxShadow: '0 4px 20px rgba(0,0,0,0.05)' }}>
                        <Typography variant="h6" sx={{ fontWeight: 600, color: BRAND.colors.blue, mb: 2, fontFamily: BRAND.typography.titles }}>
                          Presença por Tipo de Órgão
                        </Typography>
                        <ReactECharts option={getGraficoTipoComissaoOptions()} style={{ height: '350px' }} />
                      </Paper>
                    </Grid>
                    <Grid item xs={12} md={6}>
                      <Paper sx={{ p: 3, borderRadius: BRAND.borderRadius, border: `1px solid ${BRAND.colors.grayLight}`, boxShadow: '0 4px 20px rgba(0,0,0,0.05)' }}>
                        <Typography variant="h6" sx={{ fontWeight: 600, color: BRAND.colors.blue, mb: 2, fontFamily: BRAND.typography.titles }}>
                          Top Comissões (Maior Presença)
                        </Typography>
                        <ReactECharts option={getGraficoTopComissoesOptions()} style={{ height: '350px' }} />
                      </Paper>
                    </Grid>
                  </>
                ) : (
                  <>
                    <Grid item xs={12} md={6}>
                      <Paper sx={{ p: 3, borderRadius: BRAND.borderRadius, border: `1px solid ${BRAND.colors.grayLight}`, boxShadow: '0 4px 20px rgba(0,0,0,0.05)' }}>
                        <Typography variant="h6" sx={{ fontWeight: 600, color: BRAND.colors.blue, mb: 2, fontFamily: BRAND.typography.titles }}>
                          Sua Presença vs. Média da Comissão
                        </Typography>
                        <ReactECharts option={getGraficoComparativoMediaOptions()} style={{ height: '350px' }} />
                      </Paper>
                    </Grid>
                    <Grid item xs={12} md={6}>
                      <Paper sx={{ p: 3, borderRadius: BRAND.borderRadius, border: `1px solid ${BRAND.colors.grayLight}`, boxShadow: '0 4px 20px rgba(0,0,0,0.05)' }}>
                        <Typography variant="h6" sx={{ fontWeight: 600, color: BRAND.colors.blue, mb: 2, fontFamily: BRAND.typography.titles }}>
                          Presença por Dia da Semana
                        </Typography>
                        <ReactECharts option={getGraficoDiaSemanaOptions()} style={{ height: '350px' }} />
                      </Paper>
                    </Grid>
                  </>
                )}
              </Grid>

            </Box>
          )}

          {/* Análise Comparativa */}
          {dadosPresenca.comparativa && (
            <Paper
              elevation={0}
              sx={{
                p: 3,
                mb: 4,
                borderRadius: BRAND.borderRadius,
                border: `1px solid ${BRAND.colors.grayLight}`,
                boxShadow: '0 4px 20px rgba(0,0,0,0.05)'
              }}
            >
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 3 }}>
                <AssessmentIcon sx={{ color: BRAND.colors.blue }} />
                <Typography variant="h6" sx={{ fontWeight: 600, color: BRAND.colors.blue, fontFamily: BRAND.typography.titles }}>
                  Análise Comparativa
                </Typography>
              </Box>
              <Grid container spacing={3}>
                <Grid item xs={12} md={4}>
                  <Card variant="outlined" sx={{ borderRadius: '12px', border: `1px solid ${BRAND.colors.grayLight}` }}>
                    <CardContent>
                      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                        <Box>
                          <Typography color="text.secondary" gutterBottom sx={{ fontWeight: 600, fontSize: '0.75rem', textTransform: 'uppercase' }}>
                            vs Média Geral
                          </Typography>
                          <Typography
                            variant="h5"
                            sx={{
                              fontWeight: 700,
                              color: dadosPresenca.comparativa.diff_geral >= 0 ? BRAND.colors.green : BRAND.colors.orangeDark,
                              fontFamily: BRAND.typography.data
                            }}
                          >
                            {dadosPresenca.comparativa.diff_geral >= 0 ? '+' : ''}
                            {dadosPresenca.comparativa.diff_geral.toFixed(1)}%
                          </Typography>
                        </Box>
                        {dadosPresenca.comparativa.diff_geral >= 0 ? (
                          <TrendingUpIcon sx={{ fontSize: 40, color: BRAND.colors.green }} />
                        ) : (
                          <TrendingDownIcon sx={{ fontSize: 40, color: BRAND.colors.orangeDark }} />
                        )}
                      </Box>
                      <Tooltip title={`Presença do parlamentar: ${dadosPresenca.comparativa.presenca_parlamentar.toFixed(1)}% | Média geral: ${dadosPresenca.comparativa.media_geral.toFixed(1)}%`}>
                        <IconButton size="small" sx={{ mt: 1 }}>
                          <HelpOutlineIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                    </CardContent>
                  </Card>
                </Grid>

                <Grid item xs={12} md={4}>
                  <Card variant="outlined" sx={{ borderRadius: '12px', border: `1px solid ${BRAND.colors.grayLight}` }}>
                    <CardContent>
                      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                        <Box>
                          <Typography color="text.secondary" gutterBottom sx={{ fontWeight: 600, fontSize: '0.75rem', textTransform: 'uppercase' }}>
                            vs Média do Estado ({dadosParlamentar.estado})
                          </Typography>
                          {dadosPresenca.comparativa.diff_estado !== null && dadosPresenca.comparativa.diff_estado !== undefined ? (
                            <Typography
                              variant="h5"
                              sx={{
                                fontWeight: 700,
                                color: dadosPresenca.comparativa.diff_estado >= 0 ? BRAND.colors.green : BRAND.colors.orangeDark,
                                fontFamily: BRAND.typography.data
                              }}
                            >
                              {dadosPresenca.comparativa.diff_estado >= 0 ? '+' : ''}
                              {dadosPresenca.comparativa.diff_estado.toFixed(1)}%
                            </Typography>
                          ) : (
                            <Typography variant="h5" color="text.secondary" sx={{ fontFamily: BRAND.typography.data }}>N/A</Typography>
                          )}
                        </Box>
                        {dadosPresenca.comparativa.diff_estado !== null && dadosPresenca.comparativa.diff_estado !== undefined && (
                          dadosPresenca.comparativa.diff_estado >= 0 ? (
                            <TrendingUpIcon sx={{ fontSize: 40, color: BRAND.colors.green }} />
                          ) : (
                            <TrendingDownIcon sx={{ fontSize: 40, color: BRAND.colors.orangeDark }} />
                          )
                        )}
                      </Box>
                      {dadosPresenca.comparativa.diff_estado !== null && dadosPresenca.comparativa.diff_estado !== undefined && (
                        <Tooltip title={`Presença do parlamentar: ${dadosPresenca.comparativa.presenca_parlamentar.toFixed(1)}% | Média do estado: ${dadosPresenca.comparativa.media_estado?.toFixed(1)}%`}>
                          <IconButton size="small" sx={{ mt: 1 }}>
                            <HelpOutlineIcon fontSize="small" />
                          </IconButton>
                        </Tooltip>
                      )}
                    </CardContent>
                  </Card>
                </Grid>

                <Grid item xs={12} md={4}>
                  <Card variant="outlined" sx={{ borderRadius: '12px', border: `1px solid ${BRAND.colors.grayLight}` }}>
                    <CardContent>
                      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                        <Box>
                          <Typography color="text.secondary" gutterBottom sx={{ fontWeight: 600, fontSize: '0.75rem', textTransform: 'uppercase' }}>
                            vs Média do Partido ({dadosParlamentar.partido})
                          </Typography>
                          {dadosPresenca.comparativa.diff_partido !== null && dadosPresenca.comparativa.diff_partido !== undefined ? (
                            <Typography
                              variant="h5"
                              sx={{
                                fontWeight: 700,
                                color: dadosPresenca.comparativa.diff_partido >= 0 ? BRAND.colors.green : BRAND.colors.orangeDark,
                                fontFamily: BRAND.typography.data
                              }}
                            >
                              {dadosPresenca.comparativa.diff_partido >= 0 ? '+' : ''}
                              {dadosPresenca.comparativa.diff_partido.toFixed(1)}%
                            </Typography>
                          ) : (
                            <Typography variant="h5" color="text.secondary" sx={{ fontFamily: BRAND.typography.data }}>N/A</Typography>
                          )}
                        </Box>
                        {dadosPresenca.comparativa.diff_partido !== null && dadosPresenca.comparativa.diff_partido !== undefined && (
                          dadosPresenca.comparativa.diff_partido >= 0 ? (
                            <TrendingUpIcon sx={{ fontSize: 40, color: BRAND.colors.green }} />
                          ) : (
                            <TrendingDownIcon sx={{ fontSize: 40, color: BRAND.colors.orangeDark }} />
                          )
                        )}
                      </Box>
                      {dadosPresenca.comparativa.diff_partido !== null && dadosPresenca.comparativa.diff_partido !== undefined && (
                        <Tooltip title={`Presença do parlamentar: ${dadosPresenca.comparativa.presenca_parlamentar.toFixed(1)}% | Média do partido: ${dadosPresenca.comparativa.media_partido?.toFixed(1)}%`}>
                          <IconButton size="small" sx={{ mt: 1 }}>
                            <HelpOutlineIcon fontSize="small" />
                          </IconButton>
                        </Tooltip>
                      )}
                    </CardContent>
                  </Card>
                </Grid>
              </Grid>
            </Paper>
          )}

          {/* Análise por Comissão */}
          {dadosPresenca.presencas && dadosPresenca.presencas.length > 0 && (
            <Paper sx={{ p: 3, mb: 4 }}>
              <Typography variant="h6" gutterBottom sx={{ mb: 2, color: '#003366' }}>
                🏛️ Análise por Comissão
              </Typography>

              {filtros.comissao === 'Todas' ? (
                <>
                  {(() => {
                    const { plenario, permanentes, naoPermanentes } = separarComissoesPorTipo(dadosPresenca.presencas);

                    return (
                      <>
                        {plenario.length > 0 && (
                          <>
                            <Typography variant="subtitle1" sx={{ mt: 2, mb: 1, fontWeight: 'bold' }}>
                              🏛️ Plenário
                            </Typography>
                            <TableContainer component={Paper} elevation={0} sx={{ borderRadius: BRAND.borderRadius, border: `1px solid ${BRAND.colors.grayLight}`, mb: 2 }}>
                              <Table size="small">
                                <TableHead sx={{ backgroundColor: BRAND.colors.grayLight }}>
                                  <TableRow>
                                    <TableCell><strong>Órgão</strong></TableCell>
                                    <TableCell align="right"><strong>Presença</strong></TableCell>
                                    <TableCell align="right"><strong>Sessões Participadas</strong></TableCell>
                                    <TableCell align="right"><strong>Sessões Realizadas</strong></TableCell>
                                  </TableRow>
                                </TableHead>
                                <TableBody>
                                  {plenario.map((comissao, idx) => (
                                    <TableRow key={idx}>
                                      <TableCell>{comissao.nome}</TableCell>
                                      <TableCell align="right">{formatarPercentual(comissao.percentual)}</TableCell>
                                      <TableCell align="right">{comissao.presencas.toLocaleString('pt-BR')}</TableCell>
                                      <TableCell align="right">{comissao.reunioes.toLocaleString('pt-BR')}</TableCell>
                                    </TableRow>
                                  ))}
                                </TableBody>
                              </Table>
                            </TableContainer>
                          </>
                        )}

                        {permanentes.length > 0 && (
                          <>
                            <Typography variant="subtitle1" sx={{ mt: 3, mb: 1, fontWeight: 'bold' }}>
                              📋 Comissões Permanentes
                            </Typography>
                            <TableContainer component={Paper} elevation={0} sx={{ borderRadius: BRAND.borderRadius, border: `1px solid ${BRAND.colors.grayLight}`, mb: 2 }}>
                              <Table size="small">
                                <TableHead sx={{ backgroundColor: BRAND.colors.grayLight }}>
                                  <TableRow>
                                    <TableCell><strong>Órgão</strong></TableCell>
                                    <TableCell align="right"><strong>Presença</strong></TableCell>
                                    <TableCell align="right"><strong>Sessões Participadas</strong></TableCell>
                                    <TableCell align="right"><strong>Sessões Realizadas</strong></TableCell>
                                  </TableRow>
                                </TableHead>
                                <TableBody>
                                  {permanentes.map((comissao, idx) => (
                                    <TableRow key={idx}>
                                      <TableCell>{comissao.nome}</TableCell>
                                      <TableCell align="right">{formatarPercentual(comissao.percentual)}</TableCell>
                                      <TableCell align="right">{comissao.presencas.toLocaleString('pt-BR')}</TableCell>
                                      <TableCell align="right">{comissao.reunioes.toLocaleString('pt-BR')}</TableCell>
                                    </TableRow>
                                  ))}
                                </TableBody>
                              </Table>
                            </TableContainer>
                          </>
                        )}

                        {naoPermanentes.length > 0 && (
                          <>
                            <Typography variant="subtitle1" sx={{ mt: 3, mb: 1, fontWeight: 'bold' }}>
                              📝 Comissões Não Permanentes
                            </Typography>
                            <TableContainer component={Paper} elevation={0} sx={{ borderRadius: BRAND.borderRadius, border: `1px solid ${BRAND.colors.grayLight}`, mb: 2 }}>
                              <Table size="small">
                                <TableHead sx={{ backgroundColor: BRAND.colors.grayLight }}>
                                  <TableRow>
                                    <TableCell><strong>Órgão</strong></TableCell>
                                    <TableCell align="right"><strong>Presença</strong></TableCell>
                                    <TableCell align="right"><strong>Sessões Participadas</strong></TableCell>
                                    <TableCell align="right"><strong>Sessões Realizadas</strong></TableCell>
                                  </TableRow>
                                </TableHead>
                                <TableBody>
                                  {naoPermanentes.map((comissao, idx) => (
                                    <TableRow key={idx}>
                                      <TableCell>{comissao.nome}</TableCell>
                                      <TableCell align="right">{formatarPercentual(comissao.percentual)}</TableCell>
                                      <TableCell align="right">{comissao.presencas.toLocaleString('pt-BR')}</TableCell>
                                      <TableCell align="right">{comissao.reunioes.toLocaleString('pt-BR')}</TableCell>
                                    </TableRow>
                                  ))}
                                </TableBody>
                              </Table>
                            </TableContainer>
                          </>
                        )}
                      </>
                    );
                  })()}
                </>
              ) : (
                <TableContainer component={Paper} elevation={0} sx={{ borderRadius: BRAND.borderRadius, border: `1px solid ${BRAND.colors.grayLight}` }}>
                  <Table size="small">
                    <TableHead sx={{ backgroundColor: BRAND.colors.grayLight }}>
                      <TableRow>
                        <TableCell><strong>Órgão</strong></TableCell>
                        <TableCell align="right"><strong>Presença</strong></TableCell>
                        <TableCell align="right"><strong>Sessões Participadas</strong></TableCell>
                        <TableCell align="right"><strong>Sessões Realizadas</strong></TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {dadosPresenca.presencas.map((comissao, idx) => (
                        <TableRow key={idx}>
                          <TableCell>{comissao.nome}</TableCell>
                          <TableCell align="right">{formatarPercentual(comissao.percentual)}</TableCell>
                          <TableCell align="right">{comissao.presencas.toLocaleString('pt-BR')}</TableCell>
                          <TableCell align="right">{comissao.reunioes.toLocaleString('pt-BR')}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </TableContainer>
              )}
            </Paper>
          )}



          {/* Detalhamento Mensal */}
          {dadosPresenca.detalhamento_mensal && dadosPresenca.detalhamento_mensal.length > 0 && (
            <Paper sx={{ p: 3, mb: 4 }}>
              <Typography variant="h6" gutterBottom sx={{ mb: 2, color: '#003366' }}>
                🔍 Detalhamento Mensal
              </Typography>
              <TableContainer component={Paper} elevation={0} sx={{ borderRadius: BRAND.borderRadius, border: `1px solid ${BRAND.colors.grayLight}` }}>
                <Table size="small">
                  <TableHead sx={{ backgroundColor: BRAND.colors.grayLight }}>
                    <TableRow>
                      <TableCell><strong>Mês</strong></TableCell>
                      <TableCell><strong>Órgão</strong></TableCell>
                      <TableCell><strong>Tipo</strong></TableCell>
                      <TableCell align="right"><strong>Presença</strong></TableCell>
                      <TableCell align="right"><strong>Sessões Participadas</strong></TableCell>
                      <TableCell align="right"><strong>Sessões Realizadas</strong></TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {dadosPresenca.detalhamento_mensal.map((item, idx) => (
                      <TableRow key={idx}>
                        <TableCell>{item.mes}</TableCell>
                        <TableCell>{item.orgao}</TableCell>
                        <TableCell>{item.tipo}</TableCell>
                        <TableCell align="right">{formatarPercentual(item.percentual)}</TableCell>
                        <TableCell align="right">{item.presencas.toLocaleString('pt-BR')}</TableCell>
                        <TableCell align="right">{item.total.toLocaleString('pt-BR')}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </TableContainer>
            </Paper>
          )}

          {/* Análise IA (Movido para o final) */}
          <Box sx={{ mt: 4, mb: 4 }}>
            <Button
              variant="contained"
              fullWidth
              size="large"
              onClick={gerarAnaliseLLM}
              disabled={loadingAnalise || loading}
              sx={{
                py: 2,
                borderRadius: '12px',
                backgroundColor: BRAND.colors.blue,
                '&:hover': { backgroundColor: '#002244' },
                fontWeight: 600,
                fontFamily: BRAND.typography.titles,
                textTransform: 'none',
                fontSize: '1.1rem',
                mb: 3
              }}
              startIcon={loadingAnalise ? <CircularProgress size={24} color="inherit" /> : <PsychologyIcon />}
            >
              {loadingAnalise ? 'Gerando Análise Inteligente...' : 'Gerar Análise de Impacto das Ausências (IA)'}
            </Button>

            {analiseLLM && (
              <Card sx={{ borderRadius: BRAND.borderRadius, border: `1px solid ${BRAND.colors.blue}`, backgroundColor: '#F0F7FF', boxShadow: '0 4px 20px rgba(0,51,102,0.1)' }}>
                <CardContent>
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 2 }}>
                    <PsychologyIcon sx={{ color: BRAND.colors.blue }} />
                    <Typography variant="h6" sx={{ fontWeight: 700, color: BRAND.colors.blue, fontFamily: BRAND.typography.titles }}>
                      Análise da Inteligência Artificial
                    </Typography>
                  </Box>
                  <Divider sx={{ mb: 2, borderColor: 'rgba(0,51,102,0.1)' }} />

                  {analiseLLM.error ? (
                    <Alert severity="warning" sx={{ borderRadius: '12px' }}>{analiseLLM.error}</Alert>
                  ) : (
                    <Box sx={{
                      color: BRAND.colors.blue,
                      fontFamily: BRAND.typography.body,
                      '& p': { marginBottom: '1em', lineHeight: 1.6 },
                      '& strong': { fontWeight: 700 },
                      '& ul': { paddingLeft: '1.5em', marginBottom: '1em' },
                      '& li': { marginBottom: '0.5em' }
                    }}>
                      <ReactMarkdown>
                        {analiseLLM.analise}
                      </ReactMarkdown>
                    </Box>
                  )}
                </CardContent>
              </Card>
            )}
          </Box>

          {/* Informações finais */}
          <Alert
            severity="info"
            sx={{
              borderRadius: '12px',
              backgroundColor: '#E3F2FD',
              color: BRAND.colors.blue,
              '& .MuiAlert-icon': { color: BRAND.colors.blue }
            }}
          >
            Os dados são calculados a partir da frequência registrada mensalmente nas comissões permanentes,
            comissões não permanentes e nas sessões plenárias encontradas no portal da Câmara dos Deputados.
            A análise por comissão mostra apenas as comissões onde o parlamentar é membro efetivo.
            <br /><br />
            <strong>Atenção:</strong> A análise detalhada de ausências pela Inteligência Artificial considera apenas os eventos ocorridos nos últimos 6 meses do período selecionado.
          </Alert>
        </>
      )}

      {!dadosPresenca && !loading && (
        <Alert
          severity="info"
          sx={{
            mt: 4,
            borderRadius: '12px',
            '& .MuiAlert-icon': { color: BRAND.colors.blue }
          }}
        >
          Selecione um parlamentar e clique em "Buscar Dados de Presença" para visualizar as estatísticas.
        </Alert>
      )}
    
      <DataSourceFooter
        sources={[{"label":"Presenças — API da Câmara","href":"https://dadosabertos.camara.leg.br/swagger/api.html#api-Eventos","type":"camara"},{"label":"Dados Abertos da Câmara","href":"https://dadosabertos.camara.leg.br","type":"camara"}]}
        note="Registros de presença em sessões plenárias e reuniões de comissões conforme o sistema oficial da Câmara dos Deputados."
      />
    </Container>
  );
}

export default PresencaParlamentar;
