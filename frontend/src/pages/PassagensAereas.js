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
  CircularProgress,
  Alert,
  Card,
  CardContent,
  Chip,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Avatar,
  Divider,
} from '@mui/material';
import {
  Flight as FlightIcon,
  TrendingUp as TrendingUpIcon,
  AttachMoney as AttachMoneyIcon,
  People as PeopleIcon,
  Business as BusinessIcon,
  LocationOn as LocationOnIcon,
  Search as SearchIcon,
  ContentPasteSearch as ContentPasteSearchIcon,
  AccountBalance as AccountBalanceIcon,
  History as HistoryIcon,
  Language as LanguageIcon,
  Timeline as TimelineIcon,
  Psychology as PsychologyIcon,
  Public as PublicIcon,
  Info as InfoIcon,
  Groups as GroupsIcon,
} from '@mui/icons-material';
import { 
  Drawer, 
  IconButton, 
  List, 
  ListItem, 
  ListItemIcon, 
  ListItemText,
  Tooltip,
  Skeleton
} from '@mui/material';
import ReactECharts from 'echarts-for-react';
import LeafletMap from '../components/LeafletMap';
import FilterSelector from '../components/FilterSelector';
import axios from '../config/axios';
import { API_HEADERS, API_BASE_URL, API_KEY } from '../config';
import { PARTIDO_LOGOS_FALLBACK } from '../utils/logos';
import DataSourceFooter from '../components/DataSourceFooter';

// CORES DO MANUAL DE MARCA
const COLORS = {
  VERDE: '#009739',
  AMARELO: '#FFF81C',
  AZUL: '#003366',
  BRANCO: '#FFFFFF',
  CINZA: '#666666'
};

// URLs de logos de partidos (Special:FilePath - Imunes a bloqueios)
const PassagensAereas = () => {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  // Estados para filtros unificados

  const [filtros, setFiltros] = useState({
    estado: 'Todos',
    partido: 'Todos',
    parlamentar: 'Todos',
  });

  const [dadosPassagens, setDadosPassagens] = useState(null);
  const [metricas, setMetricas] = useState(null);
  const [passageiros, setPassageiros] = useState([]);
  const [passagensCaras, setPassagensCaras] = useState([]);
  const [aeroportos, setAeroportos] = useState([]);
  const [comparisonAverages, setComparisonAverages] = useState(null);
  
  // Estados para Investigação OSINT
  const [isInvestigating, setIsInvestigating] = useState(false);
  const [investigationResult, setInvestigationResult] = useState(null);
  const [selectedPassageiro, setSelectedPassageiro] = useState(null);
  const [drawerOpen, setDrawerOpen] = useState(false);

  const normalizeWikiUrl = (url) => {
    if (!url || typeof url !== 'string') return url;
    if (url.includes('flagcdn.com') || url.includes('Special:FilePath')) return url;
    
    const match = url.match(/wikipedia\/(?:commons|pt)\/(?:thumb\/)?(?:[a-f0-9]\/[a-f0-9]{2}\/)?([^\/]+)(?:\/\a+px-[^\/]+)?$/i);
    if (match && match[1]) {
      return `https://commons.wikimedia.org/wiki/Special:FilePath/${match[1]}?width=150`;
    }
    return url;
  };

  const getPartidoLogo = (info) => {
    if (!info) return '';
    if (info.urlPartido) return normalizeWikiUrl(info.urlPartido);
    return PARTIDO_LOGOS_FALLBACK[info.sgPartido?.toUpperCase()] || '';
  };

  const getEstadoLogo = (info) => {
    if (!info) return '';
    if (info.urlEstado) return normalizeWikiUrl(info.urlEstado);
    const uf = (info.sgUF || info.estado || "").toUpperCase();
    
    // Tratamento especial para RN que falha no FlagCDN ou links quebrados
    if (uf === 'RN') return 'https://upload.wikimedia.org/wikipedia/commons/thumb/3/30/Bandeira_do_Rio_Grande_do_Norte.svg/300px-Bandeira_do_Rio_Grande_do_Norte.svg.png';
    
    return uf ? `https://flagcdn.com/w160/br-${uf.toLowerCase()}.png` : '';
  };

  const handlePartidoLogoError = (event, info) => {
    const fallback = PARTIDO_LOGOS_FALLBACK[info.sgPartido?.toUpperCase()];
    if (fallback && event.target.src !== fallback) {
      event.target.src = fallback;
    } else {
      event.target.style.display = 'none';
    }
  };

  useEffect(() => {
    carregarAeroportos();
  }, []);

  const carregarAeroportos = async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/aeroportos`, { headers: API_HEADERS });
      const data = await response.json();
      setAeroportos(data || []);
    } catch (err) {
      console.error('Erro ao carregar aeroportos:', err);
    }
  };

  const carregarMediasComparacao = async () => {
    setComparisonAverages(null);
  };

  const handleGerarAnalise = async () => {
    console.log('INICIANDO BUSCA DE DADOS...');
    console.log('Filtros aplicados:', filtros);

    // Reset de todos os dados anteriores
    setDadosPassagens(null);
    setMetricas(null);
    setPassageiros([]);
    setPassagensCaras([]);
    setComparisonAverages(null);

    setLoading(true);
    setError(null);

    try {
      const params = new URLSearchParams();
      const hasParlamentar = filtros.parlamentar && filtros.parlamentar !== 'Todos';

      // Quando há parlamentar selecionado, priorizamos o nome.
      // Isso evita bloquear resultados por partido/UF desatualizados após janela partidária.
      if (hasParlamentar) {
        params.append('parlamentar', filtros.parlamentar);
      } else {
        if (filtros.estado !== 'Todos') params.append('estado', filtros.estado);
        if (filtros.partido !== 'Todos') params.append('partido', filtros.partido);
      }
      params.append('_t', Date.now());

      const urlQuery = `/api/passagens-aereas/analise?${params.toString()}`;
      const response = await fetch(`${API_BASE_URL}${urlQuery}`, { 
        headers: {
          ...API_HEADERS,
          'Cache-Control': 'no-cache'
        } 
      });
      const analise = await response.json();

      console.log('✅ Resposta recebida!');

      if (!analise.success) {
        setError(analise.message || 'Nenhum dado de passagens aéreas encontrado para os filtros selecionados.');
        setDadosPassagens(null);
        setMetricas(null);
        setPassageiros([]);
        setPassagensCaras([]);
        setComparisonAverages(null);
        return;
      }

      const dadosCompletos = analise.dados_completos || [];

      if (dadosCompletos.length === 0) {
        setError('Nenhum dado de passagens aéreas encontrado para os filtros selecionados.');
        setDadosPassagens(null);
        setMetricas(analise.metricas || null);
        setPassageiros(analise.passageiros || []);
        setPassagensCaras([]);
        setComparisonAverages(null);
        return;
      }

      setDadosPassagens(dadosCompletos);
      calcularMetricas(dadosCompletos);
      processarPassageiros(dadosCompletos);
      identificarPassagensCaras(dadosCompletos);

      if (filtros.parlamentar !== 'Todos') {
        await carregarMediasComparacao();
      } else {
        setComparisonAverages(null);
      }

    } catch (err) {
      setError('Erro ao buscar dados. Tente novamente.');
      console.error('Erro:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleInvestigarPassageiro = async (passageiroNome) => {
    setSelectedPassageiro(passageiroNome);
    setIsInvestigating(true);
    setDrawerOpen(true);
    setInvestigationResult(null);

    try {
      const response = await fetch(`${API_BASE_URL}/api/passagens-aereas/investigar-passageiro`, {
        method: 'POST',
        headers: {
          ...API_HEADERS,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          passageiro: passageiroNome,
          parlamentar: filtros.parlamentar !== 'Todos' ? filtros.parlamentar : ''
        })
      });
      const data = await response.json();
      
      if (data.success) {
        setInvestigationResult(data);
      } else {
        setError('Ocorreu um erro ao realizar a investigação OSINT.');
      }
    } catch (err) {
      console.error('Erro na investigação OSINT:', err);
    } finally {
      setIsInvestigating(false);
    }
  };

  const calcularMetricas = (dados) => {
    const totalGasto = dados.reduce((sum, item) => sum + (item.vlrLiquido || 0), 0);
    const mediaGasto = totalGasto / dados.length;
    const fornecedoresUnicos = new Set(dados.map(item => item.txtFornecedor)).size;
    const parlamentaresUnicos = new Set(dados.map(item => item.nome)).size;

    // Agrupar por trecho
    const trechos = {};
    dados.forEach(item => {
      if (item.txtTrecho) {
        trechos[item.txtTrecho] = (trechos[item.txtTrecho] || 0) + 1;
      }
    });

    setMetricas({
      totalGasto,
      mediaGasto,
      totalPassagens: dados.length,
      fornecedoresUnicos,
      parlamentaresUnicos,
      trechosUnicos: Object.keys(trechos).length,
    });
  };

  const processarPassageiros = (dados) => {
    const passageirosPorNome = {};

    dados.forEach(item => {
      const nome = item.txtPassageiro || 'Não identificado';
      if (!passageirosPorNome[nome]) {
        passageirosPorNome[nome] = {
          nome,
          quantidade: 0,
          totalGasto: 0,
          isAssessor: !!(item.is_assessor),
          osint: item.osint // GARANTE A INTELIGÊNCIA AQUI
        };
      }
      passageirosPorNome[nome].quantidade++;
      passageirosPorNome[nome].totalGasto += (item.vlrLiquido || 0);
      if (item.is_assessor) {
        passageirosPorNome[nome].isAssessor = true;
      }
      // Se tiver inteligência em algum registro desse passageiro, garante que ela fique no objeto final
      if (item.osint && !passageirosPorNome[nome].osint) {
        passageirosPorNome[nome].osint = item.osint;
      }
    });

    const listaPassageiros = Object.values(passageirosPorNome)
      .sort((a, b) => b.totalGasto - a.totalGasto)
      .slice(0, 10);

    setPassageiros(listaPassageiros);
  };

  const identificarPassagensCaras = (dados) => {
    const passagensOrdenadas = [...dados]
      .sort((a, b) => (b.vlrLiquido || 0) - (a.vlrLiquido || 0))
      .map(item => ({
        ...item,
        osint: item.osint // PRESERVA A INTELIGÊNCIA NA LISTA DE CARAS
      }))
      .slice(0, 10);

    setPassagensCaras(passagensOrdenadas);
  };

  const formatarMoeda = (valor) => {
    return new Intl.NumberFormat('pt-BR', {
      style: 'currency',
      currency: 'BRL',
    }).format(valor || 0);
  };

  const getGraficoEvolucaoTemporalOptions = () => {
    if (!dadosPassagens) return {};

    // Agrupar dados por mês
    const gastosPorMes = {};
    dadosPassagens.forEach(item => {
      if (item.datEmissao) {
        const [dia, mes, ano] = item.datEmissao.split('/');
        const chave = `${mes}/${ano}`;
        gastosPorMes[chave] = (gastosPorMes[chave] || 0) + (item.vlrLiquido || 0);
      }
    });

    // Ordenar cronologicamente (MM/YYYY)
    const meses = Object.keys(gastosPorMes).sort((a, b) => {
      const [mesA, anoA] = a.split('/');
      const [mesB, anoB] = b.split('/');
      const dataA = new Date(parseInt(anoA), parseInt(mesA) - 1);
      const dataB = new Date(parseInt(anoB), parseInt(mesB) - 1);
      return dataA - dataB;
    });
    const valores = meses.map(mes => gastosPorMes[mes]);

    return {
      title: {
        text: 'Evolução Temporal dos Gastos com Passagens',
        left: 'center',
        textStyle: {
          color: '#003366',
          fontSize: 18,
          fontWeight: 'bold',
        },
      },
      tooltip: {
        trigger: 'axis',
        formatter: function (params) {
          const data = params[0];
          return `${data.name}<br/>${formatarMoeda(data.value)}`;
        },
      },
      xAxis: {
        type: 'category',
        data: meses,
        axisLabel: {
          rotate: 45,
          color: '#666666',
        },
      },
      yAxis: {
        type: 'value',
        axisLabel: {
          formatter: function (value) {
            return formatarMoeda(value);
          },
          color: '#666666',
        },
      },
      series: [
        {
          data: valores,
          type: 'line',
          smooth: true,
          areaStyle: {},
          itemStyle: {
            color: '#009739',
          },
        },
      ],
    };
  };

  const getGraficoDistribuicaoFornecedoresOptions = () => {
    if (!dadosPassagens) return {};

    const gastosPorFornecedor = {};
    dadosPassagens.forEach(item => {
      const fornecedor = item.txtFornecedor || 'Não identificado';
      gastosPorFornecedor[fornecedor] = (gastosPorFornecedor[fornecedor] || 0) + (item.vlrLiquido || 0);
    });

    const dados = Object.entries(gastosPorFornecedor)
      .map(([nome, valor]) => ({ name: nome, value: valor }))
      .sort((a, b) => b.value - a.value)
      .slice(0, 8);

    return {
      title: {
        text: 'Distribuição de Gastos por Fornecedor',
        left: 'center',
        textStyle: {
          color: '#003366',
          fontSize: 18,
          fontWeight: 'bold',
        },
      },
      tooltip: {
        trigger: 'item',
        formatter: function (params) {
          return `${params.name}<br/>${formatarMoeda(params.value)}<br/>${params.percent}%`;
        },
      },
      series: [
        {
          type: 'pie',
          radius: ['40%', '70%'],
          center: ['50%', '60%'],
          data: dados,
          itemStyle: {
            borderRadius: 8,
            borderColor: '#fff',
            borderWidth: 2,
          },
          label: {
            show: true,
            formatter: '{b}\n{d}%',
          },
        },
      ],
    };
  };

  const getGraficoViagensPorMesOptions = () => {
    if (!dadosPassagens) return {};

    // Contar viagens por mês
    const viagensPorMes = {};
    dadosPassagens.forEach(item => {
      if (item.datEmissao) {
        const [dia, mes, ano] = item.datEmissao.split('/');
        const chave = `${mes}/${ano}`;
        viagensPorMes[chave] = (viagensPorMes[chave] || 0) + 1;
      }
    });

    // Ordenar cronologicamente (MM/YYYY)
    const meses = Object.keys(viagensPorMes).sort((a, b) => {
      const [mesA, anoA] = a.split('/');
      const [mesB, anoB] = b.split('/');
      const dataA = new Date(parseInt(anoA), parseInt(mesA) - 1);
      const dataB = new Date(parseInt(anoB), parseInt(mesB) - 1);
      return dataA - dataB;
    });
    const quantidades = meses.map(mes => viagensPorMes[mes]);

    return {
      title: {
        text: 'Evolução de Viagens por Mês',
        left: 'center',
        textStyle: {
          color: '#003366',
          fontSize: 18,
          fontWeight: 'bold',
        },
      },
      tooltip: {
        trigger: 'axis',
      },
      xAxis: {
        type: 'category',
        data: meses,
        axisLabel: {
          rotate: 45,
          color: '#666666',
        },
      },
      yAxis: {
        type: 'value',
        axisLabel: {
          color: '#666666',
        },
      },
      series: [
        {
          data: quantidades,
          type: 'bar',
          itemStyle: {
            color: '#003366',
          },
        },
      ],
    };
  };

  const processarRotas = () => {
    if (!dadosPassagens) return [];

    const rotas = [];
    const trechosProcessados = new Set();

    dadosPassagens.forEach(item => {
      if (!item.txtTrecho) return;

      const trecho = item.txtTrecho;

      // Extrair origem e destino
      let origem, destino;

      if (trecho.includes('-') && !trecho.includes('/')) {
        // Formato simples: BSB-FLN
        [origem, destino] = trecho.split('-').map(s => s.trim());
      } else if (trecho.includes('/')) {
        // Formato complexo: VCP/BSB/VCP/NVT
        const partes = trecho.split('/').map(s => s.trim()).filter(s => s);
        if (partes.length >= 2) {
          origem = partes[0];
          destino = partes[partes.length - 1];
        }
      }

      if (origem && destino && origem !== destino) {
        const chave = `${origem}-${destino}`;
        if (!trechosProcessados.has(chave)) {
          rotas.push({
            origem,
            destino,
            trecho: item.txtTrecho,
            valor: item.vlrLiquido,
            fornecedor: item.txtFornecedor,
          });
          trechosProcessados.add(chave);
        }
      }
    });

    return rotas;
  };

  const getMapaRotasOptions = () => {
    if (!dadosPassagens || aeroportos.length === 0) return {};

    const rotas = processarRotas();

    // Criar um mapa de aeroportos por sigla - apenas aeroportos brasileiros
    const aeroportosMap = {};
    let aeroportosBrasileiros = 0;
    aeroportos.forEach(airport => {
      // Filtrar apenas aeroportos brasileiros (latitude entre -35 e 5, longitude entre -75 e -30)
      if (airport.latitude >= -35 && airport.latitude <= 5 &&
        airport.longitude >= -75 && airport.longitude <= -30) {
        aeroportosMap[airport.sigla] = {
          nome: airport.nome,
          coords: [airport.longitude, airport.latitude],
        };
        aeroportosBrasileiros++;
      }
    });

    console.log(`Total de aeroportos: ${aeroportos.length}, Aeroportos brasileiros: ${aeroportosBrasileiros}`);

    // Preparar dados para o mapa
    const pontosOrigem = [];
    const pontosDestino = [];
    const linhas = [];
    const aeroportosUsados = new Set();

    rotas.forEach(rota => {
      const origemData = aeroportosMap[rota.origem];
      const destinoData = aeroportosMap[rota.destino];

      if (origemData && destinoData) {
        aeroportosUsados.add(rota.origem);

        // Adicionar ponto de origem
        pontosOrigem.push({
          name: `${rota.origem} (${origemData.nome.substring(0, 30)})`,
          value: [origemData.coords[0], origemData.coords[1]],
        });

        // Adicionar ponto de destino
        pontosDestino.push({
          name: `${rota.destino} (${destinoData.nome.substring(0, 30)})`,
          value: [destinoData.coords[0], destinoData.coords[1]],
        });

        // Adicionar linha
        linhas.push({
          coords: [origemData.coords, destinoData.coords],
          lineStyle: {
            color: '#009739',
            width: 2,
            opacity: 0.8,
            type: 'solid',
          },
        });
      }
    });

    // Calcular limites dinâmicos baseados nos dados
    const allCoords = [...pontosOrigem, ...pontosDestino].map(p => p.value);
    if (allCoords.length === 0) {
      console.log('Nenhuma coordenada encontrada para o mapa');
      console.log('Aeroportos disponíveis:', Object.keys(aeroportosMap));
      console.log('Rotas processadas:', rotas);
      return {};
    }

    const lngs = allCoords.map(c => c[0]);
    const lats = allCoords.map(c => c[1]);
    const lngMin = Math.min(...lngs) - 3;
    const lngMax = Math.max(...lngs) + 3;
    const latMin = Math.min(...lats) - 3;
    const latMax = Math.max(...lats) + 3;

    return {
      title: {
        text: 'Mapa Georeferenciado de Rotas Aéreas - Brasil',
        subtext: 'Coordenadas: Latitude/Longitude | Dados reais dos aeroportos',
        left: 'center',
        top: 10,
        textStyle: {
          color: '#003366',
          fontSize: 18,
          fontWeight: 'bold',
        },
        subtextStyle: {
          color: '#666666',
          fontSize: 12,
        },
      },
      tooltip: {
        trigger: 'item',
        formatter: function (params) {
          return params.name || '';
        },
      },
      // Fundo simples com grid
      backgroundColor: '#fafafa',
      grid: {
        left: 60,
        right: 60,
        top: 80,
        bottom: 60,
      },
      xAxis: {
        name: 'Longitude',
        nameLocation: 'middle',
        nameGap: 30,
        nameTextStyle: {
          color: '#666666',
        },
        min: lngMin,
        max: lngMax,
        axisLabel: {
          color: '#666666',
          formatter: function (value) {
            return value.toFixed(1) + '°';
          }
        },
        axisLine: {
          lineStyle: {
            color: '#cccccc'
          }
        },
        splitLine: {
          show: true,
          lineStyle: {
            color: '#f0f0f0',
            type: 'dashed'
          }
        }
      },
      yAxis: {
        name: 'Latitude',
        nameTextStyle: {
          color: '#666666',
        },
        min: latMin,
        max: latMax,
        axisLabel: {
          color: '#666666',
          formatter: function (value) {
            return value.toFixed(1) + '°';
          }
        },
        axisLine: {
          lineStyle: {
            color: '#cccccc'
          }
        },
        splitLine: {
          show: true,
          lineStyle: {
            color: '#f0f0f0',
            type: 'dashed'
          }
        }
      },
      series: [
        {
          name: 'Rotas',
          type: 'lines',
          coordinateSystem: 'cartesian2d',
          data: linhas,
          effect: {
            show: true,
            period: 6,
            trailLength: 0.1,
            color: '#009739',
            symbolSize: 5,
          },
          lineStyle: {
            curveness: 0.2,
          },
        },
        {
          name: 'Aeroportos Origem',
          type: 'scatter',
          coordinateSystem: 'cartesian2d',
          data: pontosOrigem,
          symbolSize: 14,
          itemStyle: {
            color: '#003366',
            borderColor: '#009739',
            borderWidth: 3,
            shadowBlur: 10,
            shadowColor: 'rgba(0, 151, 57, 0.3)'
          },
          label: {
            show: false,
          },
          emphasis: {
            label: {
              show: true,
              position: 'top',
              formatter: '{b}',
              fontSize: 11,
              fontWeight: 'bold',
              color: '#003366'
            },
            itemStyle: {
              color: '#009739',
              shadowBlur: 15,
              shadowColor: 'rgba(0, 151, 57, 0.5)'
            },
          },
        },
        {
          name: 'Aeroportos Destino',
          type: 'scatter',
          coordinateSystem: 'cartesian2d',
          data: pontosDestino,
          symbolSize: 12,
          itemStyle: {
            color: '#ED8B00',
            borderColor: '#ffffff',
            borderWidth: 2,
            shadowBlur: 8,
            shadowColor: 'rgba(237, 139, 0, 0.3)'
          },
          label: {
            show: false,
          },
          emphasis: {
            label: {
              show: true,
              position: 'top',
              formatter: '{b}',
              fontSize: 11,
              fontWeight: 'bold',
              color: '#003366'
            },
            itemStyle: {
              color: '#ED8B00',
              borderColor: '#ffffff',
              borderWidth: 3,
              shadowBlur: 12,
              shadowColor: 'rgba(237, 139, 0, 0.5)'
            },
          },
        },
      ],
    };
  };

  return (
    <>
    <Container maxWidth="xl">
      <Box sx={{ mb: 4, backgroundColor: 'white', p: 3, borderRadius: '16px', display: 'flex', alignItems: 'center', gap: 4 }}>
        <Box sx={{ flex: 1 }}>
          <Typography
            variant="h3"
            component="h1"
            sx={{
              color: '#003366',
              fontWeight: 700,
              mb: 2,
              display: 'flex',
              alignItems: 'center',
              gap: 2,
            }}
          >
            <FlightIcon sx={{ fontSize: 40, color: '#009739' }} />
            Detalhamento das Passagens Aéreas
          </Typography>
          <Typography variant="h6" sx={{ color: '#666666' }}>
            Análise detalhada dos gastos com passagens aéreas dos parlamentares
          </Typography>
        </Box>
        <Box
          component="img"
          src="/Detalhamento_das_Passagens_Aereas.png"
          alt="Ilustração Passagens Aéreas"
          sx={{
            maxHeight: '220px',
            width: 'auto',
            borderRadius: '8px',
            display: { xs: 'none', md: 'block' }
          }}
        />
      </Box>

      {/* Filtros de Análise Unificados */}
      <FilterSelector
        onFiltersChange={(newFilters) => setFiltros(newFilters)}
        fields={['estado', 'partido', 'parlamentar']}
        useCurrentParty={true}
        requireSelection={true}
        requireAll={true}
      />

      <Paper elevation={2} sx={{ p: 4, mb: 4, textAlign: 'center' }}>
        <Button
          fullWidth
          variant="contained"
          size="large"
          onClick={handleGerarAnalise}
          disabled={loading || filtros.estado === 'Todos' || filtros.partido === 'Todos' || filtros.parlamentar === 'Todos'}
          startIcon={loading ? <CircularProgress size={20} /> : <FlightIcon />}
          sx={{
            backgroundColor: '#009739',
            '&:hover': {
              backgroundColor: '#007a2f',
            },
            py: 1.5,
            fontSize: '1.2rem',
            fontWeight: 'bold'
          }}
        >
          {loading ? 'Carregando dados...' : 'Gerar Análise de Passagens'}
        </Button>
      </Paper>

      {/* Error Alert */}
      {error && (
        <Alert severity="warning" sx={{ mb: 4 }}>
          {error}
        </Alert>
      )}

      {/* Loading Indicator */}
      {loading && (
        <Box sx={{ display: 'flex', justifyContent: 'center', my: 4 }}>
          <CircularProgress size={60} sx={{ color: '#009739' }} />
        </Box>
      )}

      {/* Informações do Parlamentar (Modelo Limpo) */}
      {metricas && filtros.parlamentar !== 'Todos' && dadosPassagens && dadosPassagens[0] && (
        <Paper elevation={3} sx={{ p: 4, mb: 4, bgcolor: '#FFFFFF', borderRadius: 4, border: '1px solid #e0e0e0' }}>
          <Grid container spacing={3} alignItems="center">
            <Grid item xs={12} md={2} sx={{ display: 'flex', justifyContent: 'center' }}>
              <Avatar
                src={dadosPassagens[0].ultimoStatus_urlFoto}
                alt={dadosPassagens[0].nome}
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
                  {dadosPassagens[0].nome}
                </Typography>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, mt: 2 }}>
                  <Chip
                    avatar={<Avatar src={getPartidoLogo(dadosPassagens[0])} />}
                    label={dadosPassagens[0].sgPartido}
                    sx={{
                      bgcolor: '#E8F5E9',
                      color: '#2E7D32',
                      fontWeight: 'bold',
                      px: 0.5,
                      fontSize: '0.9rem'
                    }}
                  />
                  <Chip
                    avatar={<Avatar src={getEstadoLogo(dadosPassagens[0])} />}
                    label={dadosPassagens[0].sgUF}
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
                  Análise de Rubrica: ✈️ Passagens Aéreas
                </Typography>
              </Box>
            </Grid>

            <Grid item xs={12} md={3} sx={{ display: 'flex', justifyContent: { xs: 'center', md: 'flex-end' }, alignItems: 'center' }}>
              <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2 }}>
                {dadosPassagens[0].sgPartido && (
                  <Box
                    component="img"
                    src={getPartidoLogo(dadosPassagens[0])}
                    onError={(event) => handlePartidoLogoError(event, dadosPassagens[0])}
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
                {dadosPassagens[0].sgUF && (
                  <Box
                    component="img"
                    src={getEstadoLogo(dadosPassagens[0])}
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

      {/* Comparações com Médias */}
      {comparisonAverages && filtros.parlamentar !== 'Todos' && dadosPassagens && dadosPassagens[0] && (
        <Paper elevation={2} sx={{ p: 4, mb: 4 }}>
          <Typography variant="h5" sx={{ color: '#003366', mb: 3 }}>
            📊 Comparação com Médias
          </Typography>

          <Grid container spacing={3}>
            <Grid item xs={12} md={4}>
              <Card sx={{
                backgroundColor: comparisonAverages.media_geral > 0 ?
                  (metricas.totalGasto > comparisonAverages.media_geral ? '#ffebee' : '#e8f5e8') : '#f5f5f5',
                border: comparisonAverages.media_geral > 0 ?
                  (metricas.totalGasto > comparisonAverages.media_geral ? '1px solid #f44336' : '1px solid #4caf50') : '1px solid #ddd'
              }}>
                <CardContent sx={{ textAlign: 'center' }}>
                  <Typography variant="h6" sx={{ color: '#003366', mb: 1 }}>
                    📊 vs Média Geral
                  </Typography>
                  {comparisonAverages.media_geral > 0 ? (
                    <>
                      <Typography
                        variant="h4"
                        sx={{
                          color: metricas.totalGasto > comparisonAverages.media_geral ? '#d32f2f' : '#2e7d32',
                          fontWeight: 700,
                          mb: 1
                        }}
                      >
                        {(((metricas.totalGasto - comparisonAverages.media_geral) / comparisonAverages.media_geral) * 100).toFixed(1)}%
                      </Typography>
                      <Typography variant="body2" sx={{ color: '#666666' }}>
                        Média geral: R$ {comparisonAverages.media_geral.toLocaleString('pt-BR', { minimumFractionDigits: 2 })}
                      </Typography>
                    </>
                  ) : (
                    <Typography variant="body1" sx={{ color: '#666666' }}>
                      Dados não disponíveis
                    </Typography>
                  )}
                </CardContent>
              </Card>
            </Grid>

            <Grid item xs={12} md={4}>
              <Card sx={{
                backgroundColor: comparisonAverages.media_estado > 0 ?
                  (metricas.totalGasto > comparisonAverages.media_estado ? '#ffebee' : '#e8f5e8') : '#f5f5f5',
                border: comparisonAverages.media_estado > 0 ?
                  (metricas.totalGasto > comparisonAverages.media_estado ? '1px solid #f44336' : '1px solid #4caf50') : '1px solid #ddd'
              }}>
                <CardContent sx={{ textAlign: 'center' }}>
                  <Typography variant="h6" sx={{ color: '#003366', mb: 1 }}>
                    📍 vs Média {dadosPassagens[0].sgUF}
                  </Typography>
                  {comparisonAverages.media_estado > 0 ? (
                    <>
                      <Typography
                        variant="h4"
                        sx={{
                          color: metricas.totalGasto > comparisonAverages.media_estado ? '#d32f2f' : '#2e7d32',
                          fontWeight: 700,
                          mb: 1
                        }}
                      >
                        {(((metricas.totalGasto - comparisonAverages.media_estado) / comparisonAverages.media_estado) * 100).toFixed(1)}%
                      </Typography>
                      <Typography variant="body2" sx={{ color: '#666666' }}>
                        Média do estado: R$ {comparisonAverages.media_estado.toLocaleString('pt-BR', { minimumFractionDigits: 2 })}
                      </Typography>
                    </>
                  ) : (
                    <Typography variant="body1" sx={{ color: '#666666' }}>
                      Dados não disponíveis
                    </Typography>
                  )}
                </CardContent>
              </Card>
            </Grid>

            <Grid item xs={12} md={4}>
              <Card sx={{
                backgroundColor: comparisonAverages.media_partido > 0 ?
                  (metricas.totalGasto > comparisonAverages.media_partido ? '#ffebee' : '#e8f5e8') : '#f5f5f5',
                border: comparisonAverages.media_partido > 0 ?
                  (metricas.totalGasto > comparisonAverages.media_partido ? '1px solid #f44336' : '1px solid #4caf50') : '1px solid #ddd'
              }}>
                <CardContent sx={{ textAlign: 'center' }}>
                  <Typography variant="h6" sx={{ color: '#003366', mb: 1 }}>
                    🏛️ vs Média {dadosPassagens[0].sgPartido}
                  </Typography>
                  {comparisonAverages.media_partido > 0 ? (
                    <>
                      <Typography
                        variant="h4"
                        sx={{
                          color: metricas.totalGasto > comparisonAverages.media_partido ? '#d32f2f' : '#2e7d32',
                          fontWeight: 700,
                          mb: 1
                        }}
                      >
                        {(((metricas.totalGasto - comparisonAverages.media_partido) / comparisonAverages.media_partido) * 100).toFixed(1)}%
                      </Typography>
                      <Typography variant="body2" sx={{ color: '#666666' }}>
                        Média do partido: R$ {comparisonAverages.media_partido.toLocaleString('pt-BR', { minimumFractionDigits: 2 })}
                      </Typography>
                    </>
                  ) : (
                    <Typography variant="body1" sx={{ color: '#666666' }}>
                      Dados não disponíveis
                    </Typography>
                  )}
                </CardContent>
              </Card>
            </Grid>
          </Grid>
        </Paper>
      )}

      {/* Métricas Resumo Geral */}
      {metricas && (
        <Box>
          <Paper elevation={2} sx={{ p: 4, mb: 4 }}>
            <Typography variant="h5" sx={{ color: '#003366', mb: 3 }}>
              📊 Resumo Geral
            </Typography>

            <Grid container spacing={3}>
              <Grid item xs={12} sm={6} md={2}>
                <Card sx={{
                  backgroundColor: '#E0E0E0',
                  height: '140px',
                  display: 'flex',
                  flexDirection: 'column'
                }}>
                  <CardContent sx={{
                    textAlign: 'center',
                    flex: 1,
                    display: 'flex',
                    flexDirection: 'column',
                    justifyContent: 'center',
                    padding: '16px 8px'
                  }}>
                    <AttachMoneyIcon sx={{ fontSize: 32, color: '#009739', mb: 1 }} />
                    <Typography variant="h6" sx={{
                      color: '#003366',
                      fontWeight: 600,
                      fontSize: '1.1rem',
                      lineHeight: 1.2,
                      mb: 0.5
                    }}>
                      {formatarMoeda(metricas.totalGasto)}
                    </Typography>
                    <Typography variant="body2" sx={{
                      color: '#666666',
                      fontSize: '0.8rem',
                      lineHeight: 1.2
                    }}>
                      Total de Gastos
                    </Typography>
                  </CardContent>
                </Card>
              </Grid>

              <Grid item xs={12} sm={6} md={2}>
                <Card sx={{
                  backgroundColor: '#E0E0E0',
                  height: '140px',
                  display: 'flex',
                  flexDirection: 'column'
                }}>
                  <CardContent sx={{
                    textAlign: 'center',
                    flex: 1,
                    display: 'flex',
                    flexDirection: 'column',
                    justifyContent: 'center',
                    padding: '16px 8px'
                  }}>
                    <FlightIcon sx={{ fontSize: 32, color: '#003366', mb: 1 }} />
                    <Typography variant="h6" sx={{
                      color: '#003366',
                      fontWeight: 600,
                      fontSize: '1.1rem',
                      lineHeight: 1.2,
                      mb: 0.5
                    }}>
                      {metricas.totalPassagens}
                    </Typography>
                    <Typography variant="body2" sx={{
                      color: '#666666',
                      fontSize: '0.8rem',
                      lineHeight: 1.2
                    }}>
                      Total de Passagens
                    </Typography>
                  </CardContent>
                </Card>
              </Grid>

              <Grid item xs={12} sm={6} md={2}>
                <Card sx={{
                  backgroundColor: '#E0E0E0',
                  height: '140px',
                  display: 'flex',
                  flexDirection: 'column'
                }}>
                  <CardContent sx={{
                    textAlign: 'center',
                    flex: 1,
                    display: 'flex',
                    flexDirection: 'column',
                    justifyContent: 'center',
                    padding: '16px 8px'
                  }}>
                    <TrendingUpIcon sx={{ fontSize: 32, color: '#009739', mb: 1 }} />
                    <Typography variant="h6" sx={{
                      color: '#009739',
                      fontWeight: 600,
                      fontSize: '1.1rem',
                      lineHeight: 1.2,
                      mb: 0.5
                    }}>
                      {formatarMoeda(metricas.mediaGasto)}
                    </Typography>
                    <Typography variant="body2" sx={{
                      color: '#666666',
                      fontSize: '0.8rem',
                      lineHeight: 1.2
                    }}>
                      Média por Passagem
                    </Typography>
                  </CardContent>
                </Card>
              </Grid>

              <Grid item xs={12} sm={6} md={2}>
                <Card sx={{
                  backgroundColor: '#E0E0E0',
                  height: '140px',
                  display: 'flex',
                  flexDirection: 'column'
                }}>
                  <CardContent sx={{
                    textAlign: 'center',
                    flex: 1,
                    display: 'flex',
                    flexDirection: 'column',
                    justifyContent: 'center',
                    padding: '16px 8px'
                  }}>
                    <BusinessIcon sx={{ fontSize: 32, color: '#003366', mb: 1 }} />
                    <Typography variant="h6" sx={{
                      color: '#003366',
                      fontWeight: 600,
                      fontSize: '1.1rem',
                      lineHeight: 1.2,
                      mb: 0.5
                    }}>
                      {metricas.fornecedoresUnicos}
                    </Typography>
                    <Typography variant="body2" sx={{
                      color: '#666666',
                      fontSize: '0.8rem',
                      lineHeight: 1.2
                    }}>
                      Fornecedores
                    </Typography>
                  </CardContent>
                </Card>
              </Grid>

              <Grid item xs={12} sm={6} md={2}>
                <Card sx={{
                  backgroundColor: '#E0E0E0',
                  height: '140px',
                  display: 'flex',
                  flexDirection: 'column'
                }}>
                  <CardContent sx={{
                    textAlign: 'center',
                    flex: 1,
                    display: 'flex',
                    flexDirection: 'column',
                    justifyContent: 'center',
                    padding: '16px 8px'
                  }}>
                    <PeopleIcon sx={{ fontSize: 32, color: '#009739', mb: 1 }} />
                    <Typography variant="h6" sx={{
                      color: '#009739',
                      fontWeight: 600,
                      fontSize: '1.1rem',
                      lineHeight: 1.2,
                      mb: 0.5
                    }}>
                      {metricas.parlamentaresUnicos}
                    </Typography>
                    <Typography variant="body2" sx={{
                      color: '#666666',
                      fontSize: '0.8rem',
                      lineHeight: 1.2
                    }}>
                      Parlamentares
                    </Typography>
                  </CardContent>
                </Card>
              </Grid>

              <Grid item xs={12} sm={6} md={2}>
                <Card sx={{
                  backgroundColor: '#E0E0E0',
                  height: '140px',
                  display: 'flex',
                  flexDirection: 'column'
                }}>
                  <CardContent sx={{
                    textAlign: 'center',
                    flex: 1,
                    display: 'flex',
                    flexDirection: 'column',
                    justifyContent: 'center',
                    padding: '16px 8px'
                  }}>
                    <FlightIcon sx={{ fontSize: 32, color: '#003366', mb: 1 }} />
                    <Typography variant="h6" sx={{
                      color: '#003366',
                      fontWeight: 600,
                      fontSize: '1.1rem',
                      lineHeight: 1.2,
                      mb: 0.5
                    }}>
                      {metricas.trechosUnicos}
                    </Typography>
                    <Typography variant="body2" sx={{
                      color: '#666666',
                      fontSize: '0.8rem',
                      lineHeight: 1.2
                    }}>
                      Trechos Únicos
                    </Typography>
                  </CardContent>
                </Card>
              </Grid>
            </Grid>
          </Paper>

          {/* Gráficos */}
          <Grid container spacing={4} sx={{ mb: 4 }}>
            <Grid item xs={12} md={6}>
              <Paper elevation={2} sx={{ p: 3 }}>
                <ReactECharts
                  option={getGraficoEvolucaoTemporalOptions()}
                  style={{ height: '400px', width: '100%' }}
                />
              </Paper>
            </Grid>

            <Grid item xs={12} md={6}>
              <Paper elevation={2} sx={{ p: 3 }}>
                <ReactECharts
                  option={getGraficoDistribuicaoFornecedoresOptions()}
                  style={{ height: '400px', width: '100%' }}
                />
              </Paper>
            </Grid>

            <Grid item xs={12}>
              <Paper elevation={2} sx={{ p: 3 }}>
                <ReactECharts
                  option={getGraficoViagensPorMesOptions()}
                  style={{ height: '400px', width: '100%' }}
                />
              </Paper>
            </Grid>
          </Grid>

          {/* Tabela de Passageiros */}
          {passageiros.length > 0 && (
            <Paper elevation={2} sx={{ p: 4, mb: 4 }}>
              <Typography variant="h5" sx={{ color: '#003366', mb: 3 }}>
                👥 Top 10 Passageiros
              </Typography>

              <TableContainer>
                <Table>
                  <TableHead>
                    <TableRow sx={{ backgroundColor: '#E0E0E0' }}>
                      <TableCell sx={{ fontWeight: 600, color: '#003366' }}>
                        Passageiro
                      </TableCell>
                      <TableCell sx={{ fontWeight: 600, color: '#003366' }}>
                        Quantidade de Passagens
                      </TableCell>
                      <TableCell sx={{ fontWeight: 600, color: '#003366' }}>
                        Total Gasto
                      </TableCell>
                      <TableCell sx={{ fontWeight: 600, color: '#003366' }}>
                        Média por Passagem
                      </TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {passageiros.map((passageiro, index) => (
                      <TableRow key={index} hover>
                        <TableCell>
                          <Typography variant="body2" sx={{ fontWeight: 500, display: 'flex', alignItems: 'center', gap: 1 }}>
                            {passageiro.nome}
                            {passageiro.isAssessor && (
                              <Chip
                                label="Assessor"
                                size="small"
                                sx={{ backgroundColor: '#E3F2FD', color: '#1565C0', fontWeight: 'bold', fontSize: '0.7rem', height: '20px' }}
                              />
                            )}
                          </Typography>
                        </TableCell>
                        <TableCell>
                          <Chip
                            label={passageiro.quantidade}
                            size="small"
                            sx={{ backgroundColor: '#003366', color: 'white' }}
                          />
                        </TableCell>
                        <TableCell>
                          <Typography variant="body2" sx={{ fontWeight: 600, color: '#009739' }}>
                            {formatarMoeda(passageiro.totalGasto)}
                          </Typography>
                        </TableCell>
                        <TableCell>
                          <Typography variant="body2">
                            {formatarMoeda(passageiro.totalGasto / passageiro.quantidade)}
                          </Typography>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </TableContainer>
            </Paper>
          )}

          {/* Tabela de Passagens Mais Caras */}
          {passagensCaras.length > 0 && (
            <Paper elevation={2} sx={{ p: 4, mb: 4 }}>
              <Typography variant="h5" sx={{ color: '#003366', mb: 3 }}>
                💰 Top 10 Passagens Mais Caras
              </Typography>

              <TableContainer>
                <Table>
                  <TableHead>
                    <TableRow sx={{ backgroundColor: '#E0E0E0' }}>
                      <TableCell sx={{ fontWeight: 600, color: '#003366' }}>
                        Parlamentar
                      </TableCell>
                      <TableCell sx={{ fontWeight: 600, color: '#003366' }}>
                        Passageiro
                      </TableCell>
                      <TableCell sx={{ fontWeight: 600, color: '#003366' }}>
                        Trecho
                      </TableCell>
                      <TableCell sx={{ fontWeight: 600, color: '#003366' }}>
                        Data
                      </TableCell>
                      <TableCell sx={{ fontWeight: 600, color: '#003366' }}>
                        Fornecedor
                      </TableCell>
                      <TableCell sx={{ fontWeight: 600, color: '#003366' }}>
                        Valor
                      </TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {passagensCaras.map((item, index) => (
                      <TableRow key={index} hover>
                        <TableCell>
                          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                            <Avatar
                              src={item.ultimoStatus_urlFoto}
                              alt={item.nome}
                              sx={{ width: 32, height: 32 }}
                            />
                            <Typography variant="body2" sx={{ fontWeight: 500 }}>
                              {item.nome}
                            </Typography>
                          </Box>
                        </TableCell>
                        <TableCell>
                          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.5 }}>
                            <Typography variant="body2" sx={{ fontWeight: 500 }}>
                              {item.txtPassageiro || '-'}
                            </Typography>
                            {item.osint && (
                              <Box sx={{ display: 'flex', gap: 0.5 }}>
                                {(item.osint.socios && item.osint.socios.length > 0) && (
                                  <Tooltip title="Sócio/Empresário vinculado">
                                    <PsychologyIcon sx={{ fontSize: 16, color: COLORS.VERDE }} />
                                  </Tooltip>
                                )}
                                {(item.osint.doacoes && item.osint.doacoes.length > 0) && (
                                  <Tooltip title="Doador registrado">
                                    <AccountBalanceIcon sx={{ fontSize: 16, color: COLORS.AMARELO }} />
                                  </Tooltip>
                                )}
                                {item.osint.outros && item.osint.outros.length > 0 && (
                                  <Tooltip title={`Viajou por: ${item.osint.outros.join(', ')}`}>
                                    <GroupsIcon sx={{ fontSize: 16, color: COLORS.AZUL }} />
                                  </Tooltip>
                                )}
                              </Box>
                            )}
                          </Box>
                        </TableCell>
                        <TableCell>
                          <Typography variant="body2">
                            {item.txtTrecho || '-'}
                          </Typography>
                        </TableCell>
                        <TableCell>
                          <Typography variant="body2">
                            {item.datEmissao || '-'}
                          </Typography>
                        </TableCell>
                        <TableCell>
                          <Typography variant="body2">
                            {item.txtFornecedor || '-'}
                          </Typography>
                        </TableCell>
                        <TableCell>
                          <Typography
                            variant="body2"
                            sx={{
                              fontWeight: 700,
                              color: '#ED8B00',
                              fontSize: '1.1rem',
                            }}
                          >
                            {formatarMoeda(item.vlrLiquido)}
                          </Typography>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </TableContainer>
            </Paper>
          )}

          {/* Mapa de Rotas */}
          {dadosPassagens && dadosPassagens.length > 0 && (
            <Paper elevation={2} sx={{ p: 4 }}>
              <Typography variant="h5" sx={{ color: '#003366', mb: 2 }}>
                🗺️ Mapa de Rotas Aéreas
              </Typography>
              <Typography variant="body2" sx={{ color: '#666666', mb: 3 }}>
                Visualização das principais rotas utilizadas
              </Typography>

              {/* Estatísticas das Rotas */}
              <Grid container spacing={2} sx={{ mb: 3 }}>
                <Grid item xs={12} sm={4}>
                  <Card sx={{ backgroundColor: '#E0E0E0' }}>
                    <CardContent sx={{ textAlign: 'center' }}>
                      <LocationOnIcon sx={{ fontSize: 30, color: '#009739', mb: 1 }} />
                      <Typography variant="h6" sx={{ color: '#003366', fontWeight: 600 }}>
                        {processarRotas().length}
                      </Typography>
                      <Typography variant="body2" sx={{ color: '#666666' }}>
                        Rotas Únicas
                      </Typography>
                    </CardContent>
                  </Card>
                </Grid>
                <Grid item xs={12} sm={4}>
                  <Card sx={{ backgroundColor: '#E0E0E0' }}>
                    <CardContent sx={{ textAlign: 'center' }}>
                      <FlightIcon sx={{ fontSize: 30, color: '#003366', mb: 1 }} />
                      <Typography variant="h6" sx={{ color: '#003366', fontWeight: 600 }}>
                        {new Set(processarRotas().map(r => r.origem)).size}
                      </Typography>
                      <Typography variant="body2" sx={{ color: '#666666' }}>
                        Aeroportos Origem
                      </Typography>
                    </CardContent>
                  </Card>
                </Grid>
                <Grid item xs={12} sm={4}>
                  <Card sx={{ backgroundColor: '#E0E0E0' }}>
                    <CardContent sx={{ textAlign: 'center' }}>
                      <FlightIcon sx={{ fontSize: 30, color: '#ED8B00', mb: 1 }} />
                      <Typography variant="h6" sx={{ color: '#003366', fontWeight: 600 }}>
                        {new Set(processarRotas().map(r => r.destino)).size}
                      </Typography>
                      <Typography variant="body2" sx={{ color: '#666666' }}>
                        Aeroportos Destino
                      </Typography>
                    </CardContent>
                  </Card>
                </Grid>
              </Grid>

              {/* Mapa Georeferenciado */}
              <Box sx={{ height: 600, mb: 3, borderRadius: 2, overflow: 'hidden', boxShadow: 2 }}>
                <LeafletMap
                  aeroportos={aeroportos}
                  rotas={processarRotas()}
                />
              </Box>

              <Divider sx={{ my: 3 }} />

              {/* Lista de Rotas */}
              <Typography variant="h6" sx={{ color: '#003366', mb: 2 }}>
                📋 Detalhamento das Rotas
              </Typography>
              <TableContainer sx={{ maxHeight: 400 }}>
                <Table stickyHeader size="small">
                  <TableHead>
                    <TableRow sx={{ backgroundColor: '#E0E0E0' }}>
                      <TableCell sx={{ fontWeight: 600, color: '#003366' }}>
                        Origem
                      </TableCell>
                      <TableCell sx={{ fontWeight: 600, color: '#003366' }}>
                        Destino
                      </TableCell>
                      <TableCell sx={{ fontWeight: 600, color: '#003366' }}>
                        Trecho Completo
                      </TableCell>
                      <TableCell sx={{ fontWeight: 600, color: '#003366' }}>
                        Fornecedor
                      </TableCell>
                      <TableCell sx={{ fontWeight: 600, color: '#003366' }}>
                        Valor
                      </TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {processarRotas().map((rota, index) => (
                      <TableRow key={index} hover>
                        <TableCell>
                          <Chip
                            label={rota.origem}
                            size="small"
                            sx={{ backgroundColor: '#009739', color: 'white', fontWeight: 600 }}
                          />
                        </TableCell>
                        <TableCell>
                          <Chip
                            label={rota.destino}
                            size="small"
                            sx={{ backgroundColor: '#ED8B00', color: 'white', fontWeight: 600 }}
                          />
                        </TableCell>
                        <TableCell>
                          <Typography variant="body2">
                            {rota.trecho}
                          </Typography>
                        </TableCell>
                        <TableCell>
                          <Typography variant="body2">
                            {rota.fornecedor}
                          </Typography>
                        </TableCell>
                        <TableCell>
                          <Typography variant="body2" sx={{ fontWeight: 600, color: '#009739' }}>
                            {formatarMoeda(rota.valor)}
                          </Typography>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </TableContainer>

              <Grid container spacing={2} sx={{ mt: 2 }}>
                <Grid item xs={12}>
                  <Alert severity="info">
                    <Typography variant="body2">
                      <strong>🗺️ Mapa Interativo:</strong>
                    </Typography>
                    <Typography variant="body2" component="div" sx={{ mt: 1 }}>
                      • Clique nos marcadores para ver informações dos aeroportos<br />
                      • Linhas verdes conectam os aeroportos com geolocalização precisa<br />
                      • <Chip label="Azul Escuro" size="small" sx={{ backgroundColor: '#003366', color: 'white', mx: 0.5 }} /> = Aeroportos de Origem<br />
                      • <Chip label="Laranja" size="small" sx={{ backgroundColor: '#ED8B00', color: 'white', mx: 0.5 }} /> = Aeroportos de Destino<br />
                      • <Chip label="Verde" size="small" sx={{ backgroundColor: '#009739', color: 'white', mx: 0.5 }} /> = Linhas de Rota
                    </Typography>
                  </Alert>
                </Grid>
              </Grid>
            </Paper>
          )}
        </Box>
      )}
    
      <DataSourceFooter
        sources={[{"label":"CEAP — Câmara dos Deputados","href":"https://dadosabertos.camara.leg.br/swagger/api.html#api-Despesas","type":"camara"},{"label":"Dados Abertos da Câmara","href":"https://dadosabertos.camara.leg.br","type":"camara"}]}
        note="Passagens aéreas custeadas pela CEAP, declaradas pelos gabinetes parlamentares ao sistema da Câmara dos Deputados."
      />
    </Container>

      {/* PAINEL LATERAL DE INVESTIGAÇÃO OSINT */}
      <Drawer
        anchor="right"
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        PaperProps={{
          sx: { width: { xs: '100%', sm: 450 }, p: 3, bgcolor: '#f8f9fa' }
        }}
      >
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
          <Typography variant="h5" sx={{ color: '#003366', fontWeight: 700, display: 'flex', alignItems: 'center', gap: 1 }}>
            <SearchIcon color="primary" /> DOSSIÊ OSINT
          </Typography>
          <Button onClick={() => setDrawerOpen(false)} size="small">Fechar</Button>
        </Box>

        <Paper elevation={1} sx={{ p: 2, mb: 3, borderRadius: 2, border: '1px solid #e0e0e0' }}>
          <Typography variant="overline" color="text.secondary">Passageiro Investigado</Typography>
          <Typography variant="h6" fontWeight="bold">{selectedPassageiro}</Typography>
        </Paper>

        {isInvestigating ? (
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            <Skeleton variant="text" height={100} />
            <Skeleton variant="rectangular" height={150} />
            <Skeleton variant="rectangular" height={150} />
            <Typography variant="body2" sx={{ textAlign: 'center', color: '#666', mt: 2 }}>
              Consultando bases governamentais e realizando varredura OSINT na web...
            </Typography>
          </Box>
        ) : investigationResult ? (
          <Box>
            <Alert icon={<InfoIcon />} severity="info" sx={{ mb: 3, borderRadius: 2 }}>
              <Typography variant="body2" fontWeight="bold">Resumo da IA:</Typography>
              <Typography variant="body2" sx={{ mt: 0.5, lineHeight: 1.6 }}>
                {investigationResult.dossie}
              </Typography>
            </Alert>

            <Typography variant="subtitle2" sx={{ mb: 1, fontWeight: 700, color: '#003366', display: 'flex', alignItems: 'center', gap: 1 }}>
              <BusinessIcon fontSize="small" /> Vínculos Societários
            </Typography>
            <List sx={{ bgcolor: 'white', borderRadius: 2, mb: 3, border: '1px solid #eee' }}>
              {investigationResult.vinculos.socios.length > 0 ? (
                investigationResult.vinculos.socios.map((socio, i) => (
                  <ListItem key={i} divider={i < investigationResult.vinculos.socios.length - 1}>
                    <ListItemText 
                      primary={socio.Nome} 
                      secondary={socio.Qualificação_Socio} 
                      primaryTypographyProps={{ fontSize: '0.9rem', fontWeight: 600 }}
                    />
                  </ListItem>
                ))
              ) : (
                <ListItem><ListItemText secondary="Nenhuma sociedade encontrada no banco." /></ListItem>
              )}
            </List>

            <Typography variant="subtitle2" sx={{ mb: 1, fontWeight: 700, color: '#003366', display: 'flex', alignItems: 'center', gap: 1 }}>
              <AccountBalanceIcon fontSize="small" /> Doações de Campanha
            </Typography>
            <List sx={{ bgcolor: 'white', borderRadius: 2, mb: 3, border: '1px solid #eee' }}>
              {investigationResult.vinculos.doacoes.length > 0 ? (
                investigationResult.vinculos.doacoes.map((doacao, i) => (
                  <ListItem key={i} divider={i < investigationResult.vinculos.doacoes.length - 1}>
                    <ListItemText 
                      primary={`Destinatário: ${doacao.parlamentar}`} 
                      secondary={`R$ ${doacao.valor_doado_campanha?.toLocaleString('pt-BR')} em ${doacao.data_doacao}`}
                      primaryTypographyProps={{ fontSize: '0.9rem', fontWeight: 600 }}
                    />
                  </ListItem>
                ))
              ) : (
                <ListItem><ListItemText secondary="Nenhuma doação encontrada no banco." /></ListItem>
              )}
            </List>

            <Typography variant="subtitle2" sx={{ mb: 1, fontWeight: 700, color: '#003366', display: 'flex', alignItems: 'center', gap: 1 }}>
              <PublicIcon fontSize="small" /> Fontes Públicas (Web)
            </Typography>
            <List sx={{ bgcolor: 'white', borderRadius: 2, border: '1px solid #eee' }}>
              {investigationResult.fontes_web.slice(0, 3).map((fonte, i) => (
                <ListItem key={i} button component="a" href={fonte.link} target="_blank" divider={i < 2}>
                  <ListItemText 
                    primary={fonte.titulo} 
                    secondary={fonte.snippet?.substring(0, 100) + '...'}
                    primaryTypographyProps={{ fontSize: '0.85rem', color: '#1a73e8', fontWeight: 600 }}
                  />
                </ListItem>
              ))}
            </List>
          </Box>
        ) : (
          <Typography color="text.secondary">Nenhuma informação disponível.</Typography>
        )}
      </Drawer>
    </>
  );
}

export default PassagensAereas;
