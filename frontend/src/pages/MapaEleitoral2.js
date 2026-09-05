import React, { useState, useRef, useEffect } from 'react';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import {
  Box,
  Container,
  Typography,
  Paper,
  Grid,
  Card,
  CardContent,
  Avatar,
  Chip,
  CircularProgress,
  Alert,
  Button,
  LinearProgress,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
} from '@mui/material';
import axios from '../config/axios';
import { API_BASE_URL } from '../config';
import ReactMarkdown from 'react-markdown';
import FilterSelector from '../components/FilterSelector';
import EChartWrapper from '../components/EChartWrapper';
import DataSourceFooter from '../components/DataSourceFooter';
import {
  brandColors,
  createBarChartOption,
  createDonutChartOption,
  createGroupedHorizontalPercentBarChartOption,
  createHorizontalPercentBarChartOption,
  createHorizontalValueBarChartOption,
  createRadarChartOption,
  createTreeMapOption
} from '../utils/chartOptions';

const UF_TO_REGION = {
  RO: 'Norte', AC: 'Norte', AM: 'Norte', RR: 'Norte', PA: 'Norte', AP: 'Norte', TO: 'Norte',
  MA: 'Nordeste', PI: 'Nordeste', CE: 'Nordeste', RN: 'Nordeste', PB: 'Nordeste', PE: 'Nordeste', AL: 'Nordeste', SE: 'Nordeste', BA: 'Nordeste',
  MG: 'Sudeste', ES: 'Sudeste', RJ: 'Sudeste', SP: 'Sudeste',
  PR: 'Sul', SC: 'Sul', RS: 'Sul',
  MS: 'Centro-Oeste', MT: 'Centro-Oeste', GO: 'Centro-Oeste', DF: 'Centro-Oeste',
};

const getRegionLabel = (uf) => UF_TO_REGION[(uf || '').toUpperCase()] || 'Região';
const TERRITORIAL_DISCLAIMER = 'Leitura territorial probabilística com base nos microterritórios do IBGE onde o deputado concentrou votos. Isso não significa que todos os eleitores tenham exatamente esse perfil individual; trata-se de uma tendência comportamental inferida a partir do perfil do território.';
const ANTUNES_LOADING_STEPS = [
  {
    agent: 'Agente 1',
    title: 'Leitura territorial',
    description: 'Mapeando concentração de votos, municípios líderes e pontos de maior densidade eleitoral.',
  },
  {
    agent: 'Agente 2',
    title: 'Leitura sociológica',
    description: 'Comparando renda, estrutura domiciliar, saneamento e perfil urbano com estado e Brasil.',
  },
  {
    agent: 'Agente 3',
    title: 'Leitura político-competitiva',
    description: 'Buscando sobreposição com outros eleitos e avaliando onde a disputa territorial é mais aberta.',
  },
  {
    agent: 'Síntese',
    title: 'Relatório estratégico',
    description: 'Consolidando os achados finais do relatório.',
  },
];

const normalizeCommonsFileUrl = (value) => {
  const raw = String(value || '').trim();
  if (!raw) return '';

  const specialMatch = raw.match(/\/wiki\/Special:FilePath\/([^?]+)/i);
  if (specialMatch?.[1]) {
    return `https://commons.wikimedia.org/wiki/Special:FilePath/${specialMatch[1]}?width=320`;
  }

  const thumbMatch = raw.match(/upload\.wikimedia\.org\/wikipedia\/commons\/(?:thumb\/)?[^/]+\/[^/]+\/([^/]+?)(?:\/\d+px-[^/]+)?$/i);
  if (thumbMatch?.[1]) {
    return `https://commons.wikimedia.org/wiki/Special:FilePath/${thumbMatch[1]}?width=320`;
  }

  const directMatch = raw.match(/upload\.wikimedia\.org\/wikipedia\/commons\/(?:[^/]+\/[^/]+\/)?([^/]+\.(?:svg|png|jpg|jpeg|webp))$/i);
  if (directMatch?.[1]) {
    return `https://commons.wikimedia.org/wiki/Special:FilePath/${directMatch[1]}?width=320`;
  }

  return raw;
};

const MapaEleitoral2 = () => {
  const lastAutoLoadedParlamentarRef = useRef('');
  const [filters, setFilters] = useState({
    estado: '',
    partido: '',
    partidoAtual: '',
    parlamentar: '',
    parlamentarLabel: '',
  });
  const [selectedFilters, setSelectedFilters] = useState({ // New state for selected filters
    estado: '',
    partido: '',
    partidoAtual: '',
    parlamentar: '',
    parlamentarLabel: '',
  });

  const [analysisData, setAnalysisData] = useState(null);
  const [ibgeResumoTop10, setIbgeResumoTop10] = useState([]);
  const [ibgeTopRedutos, setIbgeTopRedutos] = useState([]);
  const [ibgeMetricBenchmarks, setIbgeMetricBenchmarks] = useState({});
  const [ibgeResumoContextoNota, setIbgeResumoContextoNota] = useState(null);
  const [ibgeResumoCacheStatus, setIbgeResumoCacheStatus] = useState(null);
  const [loading, setLoading] = useState(false);
  const [loadingIbgeResumo, setLoadingIbgeResumo] = useState(false);
  const [ibgeResumoError, setIbgeResumoError] = useState(null);
  const [error, setError] = useState(null);
  const mapContainerRef = useRef(null);
  const mapInstanceRef = useRef(null);
  const stateShapesRef = useRef({});

  // Estados para IA
  const [aiAnalysis, setAiAnalysis] = useState(null);
  const [loadingAi, setLoadingAi] = useState(false);
  const [aiLoadingStep, setAiLoadingStep] = useState(0);
  const [aiLoadingProgress, setAiLoadingProgress] = useState(0);
  const statCardSx = {
    height: '100%',
    minHeight: 190,
    borderRadius: '18px',
    backgroundColor: '#F8FAFC',
    border: '1px solid #E6ECF3',
    boxShadow: '0 10px 24px rgba(0, 51, 102, 0.08)',
  };

  const formatComparisonValue = (value, format) => {
    if (value === null || value === undefined) return 'N/D';
    if (format === 'currency') {
      return `R$ ${Number(value).toLocaleString('pt-BR', { maximumFractionDigits: 0 })}`;
    }
    if (format === 'percent') {
      return `${Number(value).toFixed(1)}%`;
    }
    if (format === 'number_1') {
      return Number(value).toLocaleString('pt-BR', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
    }
    return Number(value).toLocaleString('pt-BR', { maximumFractionDigits: 0 });
  };

  const compactInterpretation = (text) => {
    if (!text) return '';
    return text.replace(`${TERRITORIAL_DISCLAIMER} `, '').trim();
  };

  const extractTakeaway = (text) => {
    const compact = compactInterpretation(text);
    const [firstSentence] = compact.split(/(?<=[.!?])\s+/);
    return firstSentence || compact;
  };

  const asNumber = (value) => {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  };

  const asPercent = (value) => {
    const parsed = asNumber(value);
    if (parsed === null || parsed < 0 || parsed > 100) return null;
    return parsed;
  };

  const buildCoreRedutosByVote = (redutos) => {
    const valid = (redutos || [])
      .filter((item) => asNumber(item?.total_votos) !== null)
      .sort((a, b) => (asNumber(b?.total_votos) || 0) - (asNumber(a?.total_votos) || 0));

    const totalVotes = valid.reduce((sum, item) => sum + (asNumber(item?.total_votos) || 0), 0);
    if (!valid.length || totalVotes <= 0) {
      return {
        selected: [],
        selectedVotes: 0,
        totalVotes: 0,
        voteCoverage: 0,
        threshold: 100,
      };
    }

    const threshold = 100;
    const selected = [];
    let selectedVotes = 0;

    for (const item of valid) {
      selected.push(item);
      selectedVotes += asNumber(item?.total_votos) || 0;
      if ((selectedVotes / totalVotes) * 100 >= threshold) {
        break;
      }
    }

    return {
      selected,
      selectedVotes,
      totalVotes,
      voteCoverage: (selectedVotes / totalVotes) * 100,
      threshold,
    };
  };

  useEffect(() => {
    if (!loadingAi) {
      setAiLoadingStep(0);
      setAiLoadingProgress(0);
      return undefined;
    }

    setAiLoadingStep(0);
    setAiLoadingProgress(6);

    const stepIntervalId = window.setInterval(() => {
      setAiLoadingStep((current) => Math.min(current + 1, ANTUNES_LOADING_STEPS.length - 1));
    }, 3200);

    const progressIntervalId = window.setInterval(() => {
      setAiLoadingProgress((current) => {
        if (current >= 92) return current;
        const increment = current < 28 ? 5 : current < 55 ? 4 : current < 78 ? 3 : 1;
        return Math.min(current + increment, 92);
      });
    }, 900);

    return () => {
      window.clearInterval(stepIntervalId);
      window.clearInterval(progressIntervalId);
    };
  }, [loadingAi]);

  const weightedRedutoMetric = (redutos, field) => {
    const valid = (redutos || [])
      .map((item) => ({
        peso: asNumber(item?.total_votos),
        valor: asNumber(item?.indicadores?.[field]),
      }))
      .filter((item) => item.peso !== null && item.peso > 0 && item.valor !== null);

    if (!valid.length) return null;

    const totalWeight = valid.reduce((sum, item) => sum + item.peso, 0);
    if (!totalWeight) return null;

    return valid.reduce((sum, item) => sum + (item.peso * item.valor), 0) / totalWeight;
  };

  const weightedRedutoPercentMetric = (redutos, field) => {
    const valid = (redutos || [])
      .map((item) => ({
        peso: asNumber(item?.total_votos),
        valor: asPercent(item?.indicadores?.[field]),
      }))
      .filter((item) => item.peso !== null && item.peso > 0 && item.valor !== null);

    if (!valid.length) return null;

    const totalWeight = valid.reduce((sum, item) => sum + item.peso, 0);
    if (!totalWeight) return null;

    return valid.reduce((sum, item) => sum + (item.peso * item.valor), 0) / totalWeight;
  };

  const weightedRedutoAgePercentMetric = (redutos, field) => {
    const valid = (redutos || [])
      .map((item) => {
        const peso = asNumber(item?.total_votos);
        const indicadores = item?.indicadores || {};
        const direct = asPercent(indicadores?.[field]);
        if (direct !== null) {
          return { peso, valor: direct };
        }

        const a014 = asPercent(indicadores?.share_0_14);
        const a1524 = asPercent(indicadores?.share_15_24);
        const a2539 = asPercent(indicadores?.share_25_39);
        const a4059 = asPercent(indicadores?.share_40_59);
        if (field === 'share_60_mais' && [a014, a1524, a2539, a4059].every((v) => v !== null)) {
          const derived = Math.max(0, Math.min(100, 100 - a014 - a1524 - a2539 - a4059));
          return { peso, valor: derived };
        }
        return { peso, valor: null };
      })
      .filter((item) => item.peso !== null && item.peso > 0 && item.valor !== null);

    if (!valid.length) return null;
    const totalWeight = valid.reduce((sum, item) => sum + item.peso, 0);
    if (!totalWeight) return null;
    return valid.reduce((sum, item) => sum + (item.peso * item.valor), 0) / totalWeight;
  };

  const buildPopulationProfileCharts = (redutos) => {
    const core = buildCoreRedutosByVote(redutos);
    const selected = core.selected;

    if (!selected.length) {
      return { groups: [], core };
    }

    const percentChart = (title, subtitle, fields) => {
      const points = fields
        .map(([label, field]) => ({
          label,
          value: weightedRedutoPercentMetric(selected, field),
        }))
        .filter((item) => item.value !== null);

      if (!points.length) return null;

      return {
        title,
        span: 12,
        option: createHorizontalPercentBarChartOption(
          {
            labels: points.map((item) => item.label),
            values: points.map((item) => Number(item.value.toFixed(1))),
          },
          title,
          subtitle,
        ),
      };
    };

    const donutChart = (title, subtitle, fields) => {
      const points = fields
        .map(([label, field]) => ({
          name: label,
          value: weightedRedutoPercentMetric(selected, field),
        }))
        .filter((item) => item.value !== null);

      if (!points.length) return null;

      return {
        title,
        span: 6,
        option: createDonutChartOption(
          points.map((item) => ({ ...item, value: Number(item.value.toFixed(1)) })),
          title,
          subtitle,
        ),
      };
    };

    const radarChart = (title, subtitle, fields) => {
      const points = fields
        .map(([label, field]) => ({
          name: label,
          value: weightedRedutoPercentMetric(selected, field),
        }))
        .filter((item) => item.value !== null);

      if (!points.length) return null;

      return {
        title,
        span: 6,
        option: createRadarChartOption(
          points.map((item) => ({ ...item, value: Number(item.value.toFixed(1)) })),
          title,
          subtitle,
        ),
      };
    };

    const radarChartFromPoints = (title, subtitle, points) => {
      const validPoints = points.filter((item) => item.value !== null && item.value !== undefined);

      if (!validPoints.length) return null;

      return {
        title,
        span: 6,
        option: createRadarChartOption(
          validPoints.map((item) => ({ ...item, value: Number(item.value.toFixed(1)) })),
          title,
          subtitle,
        ),
      };
    };

    const benchmarkRadarChart = (title, subtitle, fields, options = {}) => {
      const labels = [];
      const territorioValues = [];
      const estadoValues = [];
      const brasilValues = [];

      fields.forEach(([label, field, transform]) => {
        const territorioRaw = weightedRedutoPercentMetric(selected, field);
        const estadoRaw = ibgeMetricBenchmarks?.[field]?.estado ?? null;
        const brasilRaw = ibgeMetricBenchmarks?.[field]?.brasil ?? null;

        const apply = (value) => {
          if (value === null || value === undefined) return null;
          return typeof transform === 'function' ? transform(value) : value;
        };

        const territorio = apply(territorioRaw);
        const estado = apply(estadoRaw);
        const brasil = apply(brasilRaw);

        if (territorio === null && estado === null && brasil === null) return;

        labels.push(label);
        territorioValues.push(Number((territorio || 0).toFixed(1)));
        estadoValues.push(Number((estado || 0).toFixed(1)));
        brasilValues.push(Number((brasil || 0).toFixed(1)));
      });

      if (!labels.length) return null;

      return {
        title,
        span: options.span || 6,
        option: createRadarChartOption(
          {
            indicators: labels,
            series: [
              {
                name: 'Território do deputado',
                values: territorioValues,
                lineStyle: { color: brandColors.verde, width: 3 },
                areaStyle: { color: 'rgba(0, 151, 57, 0.18)' },
                itemStyle: { color: brandColors.verde },
                symbolSize: 8,
              },
              {
                name: selectedFilters.estado || 'Estado',
                values: estadoValues,
                lineStyle: { color: brandColors.azul, width: 2, type: 'dashed' },
                areaStyle: { color: 'transparent' },
                itemStyle: { color: brandColors.azul },
                symbolSize: 5,
              },
              {
                name: 'Brasil',
                values: brasilValues,
                lineStyle: { color: brandColors.laranjaEscuro, width: 2, type: 'dashed' },
                areaStyle: { color: 'transparent' },
                itemStyle: { color: brandColors.laranjaEscuro },
                symbolSize: 5,
              },
            ],
          },
          title,
          subtitle,
        ),
      };
    };

    const valueChart = (title, subtitle, fields, formatter) => {
      const points = fields
        .map(([label, field]) => ({
          label,
          value: weightedRedutoMetric(selected, field),
        }))
        .filter((item) => item.value !== null);

      if (!points.length) return null;

      return {
        title,
        option: createHorizontalValueBarChartOption(
          {
            labels: points.map((item) => item.label),
            values: points.map((item) => Number(item.value.toFixed(1))),
          },
          title,
          subtitle,
          formatter,
        ),
      };
    };

    const benchmarkPercentChart = (title, subtitle, fields) => {
      const labels = [];
      const territorioValues = [];
      const estadoValues = [];
      const brasilValues = [];

      fields.forEach(([label, field]) => {
        const territorio = weightedRedutoPercentMetric(selected, field);
        const estado = ibgeMetricBenchmarks?.[field]?.estado ?? null;
        const brasil = ibgeMetricBenchmarks?.[field]?.brasil ?? null;

        if (territorio === null && estado === null && brasil === null) return;

        labels.push(label);
        territorioValues.push(Number((territorio || 0).toFixed(1)));
        estadoValues.push(Number((estado || 0).toFixed(1)));
        brasilValues.push(Number((brasil || 0).toFixed(1)));
      });

      if (!labels.length) return null;

      return {
        title,
        span: 12,
        option: createGroupedHorizontalPercentBarChartOption(
          {
            labels,
            series: [
              { name: 'Território do deputado', values: territorioValues },
              { name: selectedFilters.estado || 'Estado', values: estadoValues },
              { name: 'Brasil', values: brasilValues },
            ],
          },
          title,
          subtitle,
        ),
      };
    };

    const benchmarkRadarChartFromPoints = (title, subtitle, points, options = {}) => {
      const validPoints = (points || []).filter((item) => (
        item?.territorio !== null || item?.estado !== null || item?.brasil !== null
      ));

      if (!validPoints.length) return null;

      return {
        title,
        span: options.span || 6,
        option: createRadarChartOption(
          {
            indicators: validPoints.map((item) => item.name),
            series: [
              {
                name: 'Território do deputado',
                values: validPoints.map((item) => Number(((item.territorio || 0)).toFixed(1))),
                lineStyle: { color: brandColors.verde, width: 3 },
                areaStyle: { color: 'rgba(0, 151, 57, 0.18)' },
                itemStyle: { color: brandColors.verde },
                symbolSize: 8,
              },
              {
                name: selectedFilters.estado || 'Estado',
                values: validPoints.map((item) => Number(((item.estado || 0)).toFixed(1))),
                lineStyle: { color: brandColors.azul, width: 2, type: 'dashed' },
                areaStyle: { color: 'transparent' },
                itemStyle: { color: brandColors.azul },
                symbolSize: 5,
              },
              {
                name: 'Brasil',
                values: validPoints.map((item) => Number(((item.brasil || 0)).toFixed(1))),
                lineStyle: { color: brandColors.laranjaEscuro, width: 2, type: 'dashed' },
                areaStyle: { color: 'transparent' },
                itemStyle: { color: brandColors.laranjaEscuro },
                symbolSize: 5,
              },
            ],
          },
          title,
          subtitle,
        ),
      };
    };

    const weightedSumPercentMetric = (fieldNames) => {
      const values = fieldNames
        .map((field) => weightedRedutoPercentMetric(selected, field))
        .filter((value) => value !== null && value !== undefined);

      if (!values.length) return null;
      return Math.min(100, values.reduce((sum, value) => sum + value, 0));
    };

    const age014 = weightedRedutoAgePercentMetric(selected, 'share_0_14') || 0;
    const age60 = weightedRedutoAgePercentMetric(selected, 'share_60_mais') || 0;
    const age1524 = weightedRedutoAgePercentMetric(selected, 'share_15_24') || 0;
    const age2539 = weightedRedutoAgePercentMetric(selected, 'share_25_39') || 0;
    const age4059 = weightedRedutoAgePercentMetric(selected, 'share_40_59') || 0;
    const dominantAgeBand = [
      ['0 a 14 anos', age014],
      ['15 a 24 anos', age1524],
      ['25 a 39 anos', age2539],
      ['40 a 59 anos', age4059],
      ['60+ anos', age60],
    ].sort((a, b) => b[1] - a[1])[0];

    const rendaMedia = weightedRedutoMetric(selected, 'renda_media_responsavel');
    const moradoresPorDomicilio = weightedRedutoMetric(selected, 'moradores_por_domicilio');
    const rendaResumoCard = (ibgeResumoTop10 || []).find((item) => item?.label === 'Renda Média do Responsável');
    const rendaEstado = rendaResumoCard?.comparisons?.estado ?? null;
    const rendaRegiao = rendaResumoCard?.comparisons?.regiao ?? null;
    const rendaBrasil = rendaResumoCard?.comparisons?.brasil ?? null;
    const estruturaResumoCard = (ibgeResumoTop10 || []).find((item) => item?.label === 'Moradores por Domicílio');
    const moradoresEstado = estruturaResumoCard?.comparisons?.estado ?? null;
    const moradoresRegiao = estruturaResumoCard?.comparisons?.regiao ?? null;
    const moradoresBrasil = estruturaResumoCard?.comparisons?.brasil ?? null;
    const filhos = weightedRedutoPercentMetric(selected, 'share_filhos') || 0;
    const conjuges = weightedRedutoPercentMetric(selected, 'share_conjuges_companheiros') || 0;
    const netos = weightedRedutoPercentMetric(selected, 'share_netos_bisnetos') || 0;
    const pais = weightedRedutoPercentMetric(selected, 'share_pais_padrastos') || 0;

    const aguaRede = weightedRedutoPercentMetric(selected, 'rede_geral_agua') || 0;
    const esgotoRede = weightedRedutoPercentMetric(selected, 'rede_esgoto') || 0;
    const coletaLixo = weightedRedutoPercentMetric(selected, 'lixo_coletado') || 0;
    const semBanheiro = weightedRedutoPercentMetric(selected, 'sem_banheiro') || 0;

    const pavimentacao = weightedRedutoPercentMetric(selected, 'entorno_via_pavimentada') || 0;
    const iluminacao = weightedRedutoPercentMetric(selected, 'entorno_iluminacao_publica') || 0;
    const calcada = weightedRedutoPercentMetric(selected, 'entorno_calcada') || 0;
    const onibus = weightedRedutoPercentMetric(selected, 'entorno_ponto_onibus') || 0;
    const rampa = weightedRedutoPercentMetric(selected, 'entorno_rampa_cadeirante') || 0;
    const alfabetizacao = weightedRedutoPercentMetric(selected, 'alfabetizacao');
    const naoAlfabetizacao = weightedRedutoPercentMetric(selected, 'nao_alfabetizacao');
    const obitos = weightedRedutoMetric(selected, 'obitos_total');
    const respHomem = weightedRedutoPercentMetric(selected, 'resp_share_homem') || 0;
    const respMulher = weightedRedutoPercentMetric(selected, 'resp_share_mulher') || 0;
    const poco = weightedRedutoPercentMetric(selected, 'poco_artesiano') || 0;
    const fossa = weightedRedutoPercentMetric(selected, 'fossa_rudimentar_buraco') || 0;
    const lixoCeuAberto = weightedRedutoPercentMetric(selected, 'lixo_ceu_aberto') || 0;
    const casa = weightedRedutoPercentMetric(selected, 'share_casa') || 0;
    const estruturaDegradada = weightedRedutoPercentMetric(selected, 'share_estrutura_degradada') || 0;
    const territoryDisclaimer = TERRITORIAL_DISCLAIMER;

    const groups = [
      {
        key: 'demografia',
        title: 'Demografia',
        interpretation:
          age60 >= 20
            ? `${territoryDisclaimer} Nos setores onde o deputado é mais forte, o território sugere envelhecimento relativo, com ${age60.toFixed(1)}% de população idosa.`
            : age014 >= 22
              ? `${territoryDisclaimer} O território dos redutos sugere base mais familiar e jovem, com ${age014.toFixed(1)}% de crianças e adolescentes.`
              : `${territoryDisclaimer} O território dos redutos sugere predomínio adulto, com maior concentração na faixa de ${dominantAgeBand?.[0] || 'idade indefinida'} (${(dominantAgeBand?.[1] || 0).toFixed(1)}%).`,
        charts: [
          {
            title: 'Faixa Etária',
            span: 12,
            option: createHorizontalPercentBarChartOption(
              {
                labels: ['0 a 14 anos', '15 a 24 anos', '25 a 39 anos', '40 a 59 anos', '60+ anos'],
                values: [
                  Number((weightedRedutoAgePercentMetric(selected, 'share_0_14') || 0).toFixed(1)),
                  Number((weightedRedutoAgePercentMetric(selected, 'share_15_24') || 0).toFixed(1)),
                  Number((weightedRedutoAgePercentMetric(selected, 'share_25_39') || 0).toFixed(1)),
                  Number((weightedRedutoAgePercentMetric(selected, 'share_40_59') || 0).toFixed(1)),
                  Number((weightedRedutoAgePercentMetric(selected, 'share_60_mais') || 0).toFixed(1)),
                ],
              },
              'Faixa Etária',
              'Distribuição ponderada pelos votos do núcleo principal',
            ),
          },
          donutChart('Sexo', 'Composição média dos microterritórios dominantes', [
            ['Homens', 'share_homens'],
            ['Mulheres', 'share_mulheres'],
          ]),
        ].filter(Boolean),
      },
      {
        key: 'renda',
        title: 'Renda',
        interpretation: `${territoryDisclaimer} Nos setores onde o deputado concentra mais voto, a renda média do responsável gira em torno de ${rendaMedia !== null ? `R$ ${Number(rendaMedia).toLocaleString('pt-BR', { maximumFractionDigits: 0 })}` : 'N/D'}${rendaEstado !== null ? `, em comparação com ${selectedFilters.estado || 'o estado'} (${`R$ ${Number(rendaEstado).toLocaleString('pt-BR', { maximumFractionDigits: 0 })}`})` : ''}${rendaRegiao !== null ? `, ${getRegionLabel(selectedFilters.estado)} (${`R$ ${Number(rendaRegiao).toLocaleString('pt-BR', { maximumFractionDigits: 0 })}`})` : ''}${rendaBrasil !== null ? ` e Brasil (${`R$ ${Number(rendaBrasil).toLocaleString('pt-BR', { maximumFractionDigits: 0 })}`})` : ''}. Já a estrutura territorial mostra o tamanho médio dos lares no reduto. Esse indicador é relevante porque ajuda a distinguir territórios de famílias menores de áreas com lares mais cheios e dependência doméstica maior.`,
        charts: [
          (rendaMedia !== null && (rendaEstado !== null || rendaBrasil !== null)) ? {
            title: 'Renda Média do Responsável',
            option: createHorizontalValueBarChartOption(
              {
                labels: [
                  'Território do deputado',
                  ...(rendaEstado !== null ? [selectedFilters.estado || 'Estado'] : []),
                  ...(rendaRegiao !== null ? [getRegionLabel(selectedFilters.estado)] : []),
                  ...(rendaBrasil !== null ? ['Brasil'] : []),
                ],
                values: [
                  Number(rendaMedia.toFixed(1)),
                  ...(rendaEstado !== null ? [Number(rendaEstado.toFixed(1))] : []),
                  ...(rendaRegiao !== null ? [Number(rendaRegiao.toFixed(1))] : []),
                  ...(rendaBrasil !== null ? [Number(rendaBrasil.toFixed(1))] : []),
                ],
              },
              'Renda Média do Responsável',
              'Comparação do território dominante com estado, região e Brasil',
              (value) => `R$ ${Number(value).toLocaleString('pt-BR', { maximumFractionDigits: 0 })}`,
            ),
          } : valueChart(
            'Renda Média do Responsável',
            'Valor médio nominal mensal nos setores dominantes',
            [['Renda média', 'renda_media_responsavel']],
            (value) => `R$ ${Number(value).toLocaleString('pt-BR', { maximumFractionDigits: 0 })}`,
          ),
          (moradoresPorDomicilio !== null && (moradoresEstado !== null || moradoresRegiao !== null || moradoresBrasil !== null)) ? {
            title: 'Estrutura Territorial',
            option: createHorizontalValueBarChartOption(
              {
                labels: [
                  'Território do deputado',
                  ...(moradoresEstado !== null ? [selectedFilters.estado || 'Estado'] : []),
                  ...(moradoresRegiao !== null ? [getRegionLabel(selectedFilters.estado)] : []),
                  ...(moradoresBrasil !== null ? ['Brasil'] : []),
                ],
                values: [
                  Number(moradoresPorDomicilio.toFixed(1)),
                  ...(moradoresEstado !== null ? [Number(moradoresEstado.toFixed(1))] : []),
                  ...(moradoresRegiao !== null ? [Number(moradoresRegiao.toFixed(1))] : []),
                  ...(moradoresBrasil !== null ? [Number(moradoresBrasil.toFixed(1))] : []),
                ],
              },
              'Estrutura Territorial',
              'Moradores por domicílio: tamanho médio dos lares no reduto, comparado com estado, região e Brasil',
              (value) => Number(value).toLocaleString('pt-BR', { maximumFractionDigits: 1 }),
            ),
          } : valueChart(
            'Estrutura Territorial',
            'Moradores por domicílio: tamanho médio dos lares no território dominante',
            [
              ['Território do deputado', 'moradores_por_domicilio'],
            ],
            (value) => Number(value).toLocaleString('pt-BR', { maximumFractionDigits: 1 }),
          ),
        ].filter(Boolean),
      },
      {
        key: 'responsavel_domicilio',
        title: 'Responsável Pelo Domicílio',
        interpretation:
          respMulher >= 50
            ? `${territoryDisclaimer} No IBGE, “responsável pelo domicílio” é a pessoa identificada no Censo como responsável por aquela unidade domiciliar. Isso não é sinônimo perfeito de “chefe de família” nem descreve automaticamente o eleitor do deputado. Nos setores dominantes, há peso relevante de domicílios com responsável mulher, o que ajuda a caracterizar a organização social do território.`
            : `${territoryDisclaimer} No IBGE, “responsável pelo domicílio” é a pessoa identificada no Censo como responsável por aquela unidade domiciliar. Isso não é sinônimo perfeito de “chefe de família” nem descreve automaticamente o eleitor do deputado. Nos setores centrais do reduto, esse perfil aparece mais masculino, o que ajuda a caracterizar a organização social do território.`,
        charts: [
          donutChart('Sexo do Responsável', 'Pessoa registrada pelo IBGE como responsável pelo domicílio naquele território', [
            ['Homem', 'resp_share_homem'],
            ['Mulher', 'resp_share_mulher'],
          ]),
        ].filter(Boolean),
      },
      {
        key: 'familia',
        title: 'Estrutura Familiar',
        interpretation:
          filhos + conjuges >= 45
            ? `${territoryDisclaimer} Em termos práticos, o território sugere domicílios em que a pessoa responsável costuma viver principalmente com cônjuge e filhos. Este bloco não mede o perfil individual do eleitor; ele descreve o arranjo doméstico mais frequente nos setores onde o deputado concentra votos.`
            : netos + pais >= 12
              ? `${territoryDisclaimer} O território sugere convivência intergeracional mais forte, com pais, padrastos, netos ou bisnetos aparecendo com peso relevante ao lado da pessoa responsável pelo domicílio.`
              : `${territoryDisclaimer} A estrutura familiar do reduto é mais distribuída, sem um único arranjo doméstico totalmente dominante. O foco aqui é entender com quem a pessoa responsável pelo domicílio tende a morar.`,
        charts: [
          percentChart('Quem Mora Com A Pessoa Responsável', 'Leitura territorial do IBGE: este gráfico mostra quais vínculos aparecem com mais frequência no mesmo domicílio da pessoa responsável. As categorias podem coexistir na mesma casa, então não somam 100%.', [
            ['Cônjuge no domicílio', 'share_conjuges_companheiros'],
            ['Filhos no domicílio', 'share_filhos'],
            ['Pais/padrastos', 'share_pais_padrastos'],
            ['Netos/bisnetos', 'share_netos_bisnetos'],
            ['Outros parentes', 'share_outros_parentes'],
          ]),
          percentChart(
            'Quantas Pessoas Moram Na Casa',
            `Distribuição dos domicílios por número de moradores. No mesmo território, a renda média da pessoa responsável é ${rendaMedia !== null ? `R$ ${Number(rendaMedia).toLocaleString('pt-BR', { maximumFractionDigits: 0 })}` : 'N/D'}, mas o IBGE não cruza essa renda por faixa de tamanho do domicílio neste arquivo.`,
            [
            ['1 morador', 'share_domicilios_1_morador'],
            ['2 moradores', 'share_domicilios_2_moradores'],
            ['3 moradores', 'share_domicilios_3_moradores'],
            ['4 moradores', 'share_domicilios_4_moradores'],
            ['5+ moradores', 'share_domicilios_5_mais_moradores'],
            ],
          ),
        ].filter(Boolean),
      },
      {
        key: 'saneamento_habitacao',
        title: 'Saneamento e Habitação',
        interpretation:
          aguaRede >= 80 && esgotoRede >= 70 && coletaLixo >= 85
            ? `${territoryDisclaimer} O reduto está assentado em setores de infraestrutura relativamente consolidada, com boa cobertura de água, esgoto e coleta de lixo.`
          : semBanheiro >= 2 || esgotoRede < 50
              ? `${territoryDisclaimer} O território mostra sinais de precariedade urbana mais forte, sobretudo em saneamento e condições básicas do domicílio.`
              : `${territoryDisclaimer} O território combina infraestrutura parcial com heterogeneidade habitacional, sem padrão totalmente consolidado.`,
        charts: [
          benchmarkRadarChart(
            'Infraestrutura Básica',
            'Território preenchido; estado e Brasil em tracejado para comparação dos pontos positivos de infraestrutura',
            [
              ['Rede geral de água', 'rede_geral_agua'],
              ['Rede de esgoto', 'rede_esgoto'],
              ['Lixo coletado', 'lixo_coletado'],
              ['Com banheiro', 'sem_banheiro', (value) => Math.max(0, 100 - value)],
            ],
          ),
          donutChart('Tipo de Moradia', 'Forma predominante de ocupação residencial', [
            ['Casa', 'share_casa'],
            ['Apartamento', 'share_apartamento'],
            ['Condomínio', 'share_casa_condominio'],
            ['Cortiço', 'share_cortico'],
            ['Estrutura degradada', 'share_estrutura_degradada'],
          ]),
        ].filter(Boolean),
      },
      {
        key: 'vulnerabilidade_habitacional',
        title: 'Vulnerabilidade Habitacional',
        interpretation:
          estruturaDegradada >= 2 || lixoCeuAberto >= 2 || fossa >= 15
            ? `${territoryDisclaimer} Aqui o foco não é o tipo de moradia mais comum, mas os sinais de fragilidade do território. O reduto mostra marcas objetivas de vulnerabilidade em saneamento, descarte de resíduos ou padrões mais frágeis de ocupação residencial.`
            : `${territoryDisclaimer} Aqui observamos apenas sinais negativos de moradia e acesso incompleto. A vulnerabilidade habitacional não aparece como traço extremo no núcleo principal, mas ainda há bolsões de fragilidade em saneamento, descarte de resíduos e formas residenciais mais frágeis.`,
        charts: [
          benchmarkPercentChart('Marcadores de Vulnerabilidade', 'Comparação do reduto com a média do estado e do Brasil para sinais de precariedade territorial', [
            ['Poço artesiano', 'poco_artesiano'],
            ['Fossa rudimentar', 'fossa_rudimentar_buraco'],
            ['Lixo a céu aberto', 'lixo_ceu_aberto'],
            ['Sem banheiro', 'sem_banheiro'],
            ['Estrutura degradada', 'share_estrutura_degradada'],
          ]),
          benchmarkPercentChart('Formas Mais Frágeis de Moradia', 'Comparação do reduto com a média do estado e do Brasil nas formas residenciais mais associadas à precariedade', [
            ['Domicílio improvisado', 'share_domicilios_improvisados'],
            ['Estrutura degradada', 'share_estrutura_degradada'],
            ['Cortiço', 'share_cortico'],
            ['Maloca', 'share_maloca'],
            ['Sem banheiro', 'sem_banheiro'],
          ]),
          benchmarkRadarChart('Acesso Incompleto a Serviços Básicos', 'Reduto preenchido; estado e Brasil em tracejado para comparar sinais de cobertura incompleta em água, esgoto e resíduos', [
            ['Poço artesiano', 'poco_artesiano'],
            ['Sem esgoto', 'sem_esgoto'],
            ['Fossa rudimentar', 'fossa_rudimentar_buraco'],
            ['Lixo queimado', 'lixo_queimado'],
            ['Estrutura degradada', 'share_estrutura_degradada'],
            ['Lixo a céu aberto', 'lixo_ceu_aberto'],
          ], { span: 12 }),
        ].filter(Boolean),
      },
      {
        key: 'entorno',
        title: 'Entorno Urbano',
        interpretation:
          pavimentacao >= 75 && iluminacao >= 85 && calcada >= 70
            ? `${territoryDisclaimer} O entorno urbano dos setores mais fortes é relativamente estruturado. Isso importa porque pavimentação, iluminação, calçada e drenagem ajudam a mostrar o grau de consolidação urbana do território onde o deputado concentra votos, além de sinalizar condições de circulação, segurança cotidiana e qualidade do espaço público.`
            : pavimentacao < 70 && calcada < 60
              ? `${territoryDisclaimer} O reduto parece mais periférico ou em transição urbana. Essa leitura é importante porque mostra um território com circulação e acesso, mas ainda com urbanização desigual, o que ajuda a distinguir áreas plenamente consolidadas de áreas em expansão ou com infraestrutura incompleta.`
              : `${territoryDisclaimer} O entorno do reduto revela urbanização incompleta ou heterogênea. Esse bloco é importante porque ajuda a entender não só a moradia, mas a qualidade do espaço público ao redor dos domicílios: mobilidade, drenagem, acessibilidade e o nível de consolidação urbana do território.`,
        charts: [
          benchmarkPercentChart('Qualidade do Entorno', 'Comparação do reduto com a média do estado e do Brasil nos indicadores positivos de urbanização', [
            ['Via pavimentada', 'entorno_via_pavimentada'],
            ['Iluminação pública', 'entorno_iluminacao_publica'],
            ['Calçada', 'entorno_calcada'],
            ['Rampa cadeirante', 'entorno_rampa_cadeirante'],
            ['Bueiro', 'entorno_bueiro'],
          ]),
          benchmarkRadarChartFromPoints(
            'Acessibilidade e Paisagem',
            'Reduto preenchido; estado e Brasil em tracejado para comparar caminhabilidade, acessibilidade e arborização',
            [
              {
                name: 'Calçada sem obstáculo',
                territorio: weightedRedutoPercentMetric(selected, 'entorno_calcada_sem_obstaculo'),
                estado: ibgeMetricBenchmarks?.entorno_calcada_sem_obstaculo?.estado ?? null,
                brasil: ibgeMetricBenchmarks?.entorno_calcada_sem_obstaculo?.brasil ?? null,
              },
              {
                name: 'Rampa cadeirante',
                territorio: weightedRedutoPercentMetric(selected, 'entorno_rampa_cadeirante'),
                estado: ibgeMetricBenchmarks?.entorno_rampa_cadeirante?.estado ?? null,
                brasil: ibgeMetricBenchmarks?.entorno_rampa_cadeirante?.brasil ?? null,
              },
              {
                name: 'Trecho arborizado',
                territorio: weightedSumPercentMetric([
                  'entorno_arborizacao_1_2_arvores',
                  'entorno_arborizacao_3_4_arvores',
                  'entorno_arborizacao_5_mais_arvores',
                ]),
                estado: [
                  ibgeMetricBenchmarks?.entorno_arborizacao_1_2_arvores?.estado,
                  ibgeMetricBenchmarks?.entorno_arborizacao_3_4_arvores?.estado,
                  ibgeMetricBenchmarks?.entorno_arborizacao_5_mais_arvores?.estado,
                ].filter((v) => v !== null && v !== undefined).reduce((sum, v) => sum + Number(v), 0),
                brasil: [
                  ibgeMetricBenchmarks?.entorno_arborizacao_1_2_arvores?.brasil,
                  ibgeMetricBenchmarks?.entorno_arborizacao_3_4_arvores?.brasil,
                  ibgeMetricBenchmarks?.entorno_arborizacao_5_mais_arvores?.brasil,
                ].filter((v) => v !== null && v !== undefined).reduce((sum, v) => sum + Number(v), 0),
              },
              {
                name: 'Sem arborização',
                territorio: weightedRedutoPercentMetric(selected, 'entorno_sem_arvores'),
                estado: ibgeMetricBenchmarks?.entorno_sem_arvores?.estado ?? null,
                brasil: ibgeMetricBenchmarks?.entorno_sem_arvores?.brasil ?? null,
              },
            ],
            { span: 12 },
          ),
        ].filter(Boolean),
      },
      {
        key: 'educacao',
        title: 'Educação',
        interpretation:
          alfabetizacao !== null
            ? `${territoryDisclaimer} A alfabetização média dos setores mais fortes está em ${alfabetizacao.toFixed(1)}%, o que ajuda a situar o capital educacional básico do reduto.`
            : `${territoryDisclaimer} Ainda não há leitura educacional territorial suficientemente consistente para este reduto.`,
        charts: [
          benchmarkPercentChart('Alfabetização', 'Comparação do reduto com a média do estado e do Brasil no indicador educacional básico', [
            ['Alfabetizados', 'alfabetizacao'],
            ['Não alfabetizados', 'nao_alfabetizacao'],
          ]),
        ].filter(Boolean),
      },
    ];

    return { groups, core };
  };

  const buildZonaEleitoralProfile = (redutos) => {
    const validRedutos = (redutos || []).filter(
      (item) => asNumber(item?.total_votos) !== null && (item?.zonas || []).length > 0
    );

    if (!validRedutos.length) {
      return {
        zonas: [],
        core: { selected: [], voteCoverage: 0, threshold: 80, totalVotes: 0, paretoZoneCount: 0, paretoCoverage: 0 },
        cards: [],
        chart: null,
      };
    }

    const zoneMap = new Map();

    validRedutos.forEach((reduto) => {
      const zonas = Array.isArray(reduto.zonas) ? reduto.zonas.filter(Boolean) : [];
      const totalVotos = asNumber(reduto.total_votos) || 0;
      if (!zonas.length || totalVotos <= 0) return;

      const allocatedVotes = totalVotos / zonas.length;

      zonas.forEach((zona) => {
        const zoneKey = String(zona).trim();
        if (!zoneKey) return;

        if (!zoneMap.has(zoneKey)) {
          zoneMap.set(zoneKey, {
            zona: zoneKey,
            total_votos: 0,
            municipios: new Set(),
            bairros: new Set(),
            locais: new Set(),
            setores: new Set(),
            sessoes: 0,
            indicadores: {},
            _weightedSums: {},
          });
        }

        const entry = zoneMap.get(zoneKey);
        entry.total_votos += allocatedVotes;
        if (reduto.municipio) entry.municipios.add(reduto.municipio);
        if (Array.isArray(reduto.bairros)) reduto.bairros.forEach((b) => b && entry.bairros.add(b));
        if (Array.isArray(reduto.locais)) reduto.locais.forEach((l) => l && entry.locais.add(l));
        if (reduto.cd_setor) entry.setores.add(String(reduto.cd_setor));
        entry.sessoes += asNumber(reduto.quantidade_sessoes) || 0;

        Object.entries(reduto.indicadores || {}).forEach(([field, value]) => {
          const numericValue = asNumber(value);
          if (numericValue === null) return;
          entry._weightedSums[field] = (entry._weightedSums[field] || 0) + (numericValue * allocatedVotes);
        });
      });
    });

    const zonas = Array.from(zoneMap.values())
      .map((entry) => {
        const indicadores = {};
        Object.entries(entry._weightedSums).forEach(([field, sum]) => {
          indicadores[field] = entry.total_votos > 0 ? (sum / entry.total_votos) : null;
        });
        return {
          zona: entry.zona,
          total_votos: Math.round(entry.total_votos),
          municipios: Array.from(entry.municipios),
          bairros: Array.from(entry.bairros),
          locais: Array.from(entry.locais),
          quantidade_setores: entry.setores.size,
          quantidade_sessoes: Math.round(entry.sessoes),
          indicadores,
        };
      })
      .sort((a, b) => (b.total_votos || 0) - (a.total_votos || 0));

    const totalVotes = zonas.reduce((sum, item) => sum + (item.total_votos || 0), 0);
    const threshold = 80;
    const selected = [];
    let selectedVotes = 0;

    for (const zona of zonas) {
      selected.push(zona);
      selectedVotes += zona.total_votos || 0;
      if (totalVotes > 0 && ((selectedVotes / totalVotes) * 100) >= threshold) {
        break;
      }
    }

    const paretoZoneCount = Math.max(1, Math.ceil(zonas.length * 0.2));
    const paretoSelected = zonas.slice(0, paretoZoneCount);
    const paretoVotes = paretoSelected.reduce((sum, item) => sum + (item.total_votos || 0), 0);
    const paretoCoverage = totalVotes > 0 ? (paretoVotes / totalVotes) * 100 : 0;

    const topZona = zonas[0] || null;
    const segundaZona = zonas[1] || null;
    const liderancaGap = topZona && segundaZona
      ? ((topZona.total_votos - segundaZona.total_votos) / (topZona.total_votos || 1)) * 100
      : null;

    const cards = [
      {
        label: 'Zonas Pareto',
        value: `${selected.length}`,
        caption: `quantas zonas são necessárias para alcançar ${threshold}% dos votos agregados por zona`,
      },
      {
        label: 'Pareto 20% Zonas',
        value: `${paretoCoverage.toFixed(1)}%`,
        caption: `participação das ${paretoZoneCount} zonas mais fortes no total de votos distribuídos por zona`,
      },
      {
        label: 'Zona Líder',
        value: topZona ? `Zona ${topZona.zona}` : 'N/D',
        caption: topZona ? `${(topZona.total_votos || 0).toLocaleString('pt-BR')} votos estimados na principal zona eleitoral` : 'sem leitura consolidada',
      },
      {
        label: 'Vantagem da Líder',
        value: liderancaGap !== null ? `${liderancaGap.toFixed(1)}%` : 'N/D',
        caption: liderancaGap !== null ? 'quanto a zona líder supera a segunda colocada em votos estimados' : 'sem segunda zona para comparação',
      },
    ];

    const chart = zonas.length
      ? createTreeMapOption(
          zonas.slice(0, 12).map((item) => ({
            name: `Zona ${item.zona}`,
            value: item.total_votos || 0,
          })),
          'Zonas Eleitorais Mais Fortes'
        )
      : null;

    return {
      zonas,
      core: {
        selected,
        voteCoverage: totalVotes > 0 ? (selectedVotes / totalVotes) * 100 : 0,
        threshold,
        totalVotes,
        paretoZoneCount,
        paretoCoverage,
      },
      cards,
      chart,
    };
  };

  useEffect(() => {
    loadStateShapes();

    return () => {
      if (mapInstanceRef.current) {
        mapInstanceRef.current.remove();
        mapInstanceRef.current = null;
      }
    };
  }, []);

  const loadStateShapes = async () => {
    try {
      const response = await fetch('/br_states.json');
      const geojson = await response.json();
      const shapes = {};

      (geojson?.features || []).forEach((feature) => {
        const sigla = feature?.properties?.SIGLA;
        const geometry = feature?.geometry;
        if (sigla && geometry) {
          shapes[sigla] = geometry;
        }
      });

      stateShapesRef.current = shapes;
    } catch (err) {
      console.error('Erro ao carregar polígonos dos estados:', err);
    }
  };

  const handleFilterChange = (newFilters) => {
    setFilters((prev) => ({ ...prev, ...newFilters }));
    setSelectedFilters(prev => ({
      ...prev,
      ...newFilters
    }));
    // Limpar análise anterior ao mudar filtros
    if (newFilters.parlamentar !== undefined) {
      lastAutoLoadedParlamentarRef.current = '';
      setAnalysisData(null);
      setIbgeResumoTop10([]);
      setIbgeTopRedutos([]);
      setIbgeMetricBenchmarks({});
      setIbgeResumoError(null);
      setAiAnalysis(null);
    }
  };

  const handleAnalyze = async () => {
    if (!selectedFilters.parlamentar) {
      setError('Selecione um parlamentar para visualizar o mapa eleitoral.');
      return;
    }

    lastAutoLoadedParlamentarRef.current = (selectedFilters.parlamentarLabel || selectedFilters.parlamentar || '').trim();

    setLoading(true);
    setError(null);
    setAnalysisData(null);
    setIbgeResumoTop10([]);
    setIbgeTopRedutos([]);
    setIbgeMetricBenchmarks({});
    setIbgeResumoContextoNota(null);
    setIbgeResumoCacheStatus(null);
    setIbgeResumoError(null);
    setAiAnalysis(null); // Resetar análise de IA
    clearMapInstance();

    try {
      const nomeParlamentar = encodeURIComponent(selectedFilters.parlamentar);
      const response = await axios.get(`${API_BASE_URL}/api/mapa-eleitoral/votos/${nomeParlamentar}`, {
        params: {
          estado: selectedFilters.estado || undefined,
          partido: selectedFilters.partido || undefined,
        },
      });

      if (response.data.error) {
        setError(response.data.error);
        return;
      }

      setAnalysisData(response.data);
      void loadIbgeResumo(selectedFilters.parlamentar, selectedFilters.estado, selectedFilters.partido);

      const pontosMapa = normalizeMapPoints(response.data);

      setTimeout(() => {
        if (pontosMapa.length > 0) {
          loadLeafletMap(pontosMapa);
        } else if (response.data.municipios && response.data.municipios.length > 0) {
          loadFallbackMap(response.data.municipios);
        }
      }, 100);
    } catch (err) {
      setError('Erro ao executar análise: ' + err.message);
    } finally {
      setLoading(false);
    }
  };

  const loadIbgeResumo = async (parlamentar, estado, partido) => {
    if (!parlamentar) return;

    setLoadingIbgeResumo(true);
    setIbgeResumoError(null);
    setIbgeTopRedutos([]);
    setIbgeMetricBenchmarks({});
    setIbgeResumoContextoNota(null);
    setIbgeResumoCacheStatus(null);
    try {
      const response = await axios.get(`${API_BASE_URL}/api/mapa-eleitoral/ibge-top10/${encodeURIComponent(parlamentar)}`, {
        params: {
          estado: estado || undefined,
          partido: partido || undefined,
        },
      });
      const resumo = response.data?.ibgeResumoTop10 || [];
      setIbgeResumoTop10(resumo);
      setIbgeTopRedutos(response.data?.topRedutos || []);
      setIbgeMetricBenchmarks(response.data?.metricBenchmarks || {});
      setIbgeResumoContextoNota(response.data?.contextoNota || null);
      setIbgeResumoCacheStatus(response.data?.cacheStatus || null);
      if (resumo.length === 0) {
        setIbgeResumoError(
          response.data?.message ||
          'Os dados socioeconômicos territoriais do IBGE não ficaram disponíveis para os redutos deste carregamento.'
        );
      }
    } catch (err) {
      console.error('Erro ao carregar resumo IBGE do top 10:', err);
      setIbgeResumoTop10([]);
      setIbgeTopRedutos([]);
      setIbgeMetricBenchmarks({});
      setIbgeResumoError('Não foi possível carregar a síntese socioeconômica territorial já materializada no banco neste momento.');
    } finally {
      setLoadingIbgeResumo(false);
    }
  };

  const handleGenerateAnalysis = async () => {
    if (!selectedFilters.parlamentar) return;

    setLoadingAi(true);
    try {
      const response = await axios.get(
        `${API_BASE_URL}/api/analise-perfil-eleitor/${encodeURIComponent(selectedFilters.parlamentar)}`,
        {
          params: {
            estado: selectedFilters.estado || undefined,
            partido: selectedFilters.partido || undefined,
          },
          timeout: 180000,
        }
      );
      if (response.data.analise) {
        setAiAnalysis(response.data.analise);
      } else {
        setAiAnalysis("Não foi possível montar o relatório territorial no momento.");
      }
    } catch (error) {
      console.error("Erro na IA:", error);
      const apiMessage =
        error?.response?.data?.analise ||
        error?.response?.data?.detail ||
        error?.message;
      setAiAnalysis(apiMessage ? `Erro ao gerar análise: ${apiMessage}` : "Erro ao montar o relatório territorial.");
    } finally {
      setLoadingAi(false);
    }
  };

  const clearMapInstance = () => {
    if (mapInstanceRef.current) {
      mapInstanceRef.current.remove();
      mapInstanceRef.current = null;
    }
  };

  const toNumber = (value) => {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  };

  const normalizeMapPoints = (data) => {
    const rawPoints = Array.isArray(data?.zonas) && data.zonas.length > 0
      ? data.zonas
      : [
          ...(Array.isArray(data?.municipios) ? data.municipios : []),
        ];

    return rawPoints
      .map((point) => {
        const lat = toNumber(point.lat ?? point.latitude ?? point.LAT);
        const lng = toNumber(point.lng ?? point.longitude ?? point.LONG);
        const totalVotos = toNumber(point.total_votos ?? point.totalVotos ?? point.votos) || 0;

        return {
          lat,
          lng,
          total_votos: totalVotos,
          municipio: point.municipio ?? point.NM_MUNICIPIO ?? 'N/A',
          estado: point.estado ?? point.SG_UF ?? 'N/A',
          local_votacao: point.local_votacao ?? point.NM_LOCAL_VOTACAO ?? [],
          endereco: point.endereco ?? point.DS_ENDERECO ?? [],
          bairro: point.bairro ?? point.NM_BAIRRO ?? [],
          qtd_secoes: toNumber(point.qtd_secoes) || 0,
          quantidade_zonas: toNumber(point.quantidade_zonas) || 0,
          quantidade_secoes: toNumber(point.quantidade_secoes) || 0,
          zonas: Array.isArray(point.zona ?? point.zonas ?? point.NR_ZONA) ? (point.zona ?? point.zonas ?? point.NR_ZONA) : [point.zona ?? point.zonas ?? point.NR_ZONA].filter(Boolean),
          secoes: Array.isArray(point.secao ?? point.secoes ?? point.NR_SECAO) ? (point.secao ?? point.secoes ?? point.NR_SECAO) : [point.secao ?? point.secoes ?? point.NR_SECAO].filter(Boolean),
        };
      })
      .filter((point) => point.lat !== null && point.lng !== null && point.lat !== 0 && point.lng !== 0);
  };

  const microterritorioCharts = buildPopulationProfileCharts(ibgeTopRedutos);
  const zonaEleitoralProfile = buildZonaEleitoralProfile(ibgeTopRedutos);
  const hasMicroterritorioCharts = microterritorioCharts.groups.length > 0;
  const hasZonaEleitoralProfile = zonaEleitoralProfile.zonas.length > 0;

  const isPointInsideRing = (lng, lat, ring) => {
    let inside = false;

    for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      const xi = ring[i][0];
      const yi = ring[i][1];
      const xj = ring[j][0];
      const yj = ring[j][1];

      const intersects = ((yi > lat) !== (yj > lat))
        && (lng < ((xj - xi) * (lat - yi)) / ((yj - yi) || Number.EPSILON) + xi);

      if (intersects) inside = !inside;
    }

    return inside;
  };

  const isPointInsidePolygon = (lng, lat, polygonCoordinates) => {
    if (!Array.isArray(polygonCoordinates) || polygonCoordinates.length === 0) {
      return false;
    }

    if (!isPointInsideRing(lng, lat, polygonCoordinates[0])) {
      return false;
    }

    for (let i = 1; i < polygonCoordinates.length; i += 1) {
      if (isPointInsideRing(lng, lat, polygonCoordinates[i])) {
        return false;
      }
    }

    return true;
  };

  const isPointInsideState = (point, uf) => {
    const geometry = stateShapesRef.current[uf];

    if (!geometry) {
      return point.estado === uf;
    }

    if (geometry.type === 'Polygon') {
      return isPointInsidePolygon(point.lng, point.lat, geometry.coordinates);
    }

    if (geometry.type === 'MultiPolygon') {
      return geometry.coordinates.some((polygon) => isPointInsidePolygon(point.lng, point.lat, polygon));
    }

    return point.estado === uf;
  };

  const filterPointsByState = (points, uf) => {
    if (!uf) {
      return points;
    }

    return points.filter((point) => isPointInsideState(point, uf));
  };

  const interpolateColor = (startColor, endColor, factor) => {
    const start = startColor.match(/\w\w/g).map((value) => parseInt(value, 16));
    const end = endColor.match(/\w\w/g).map((value) => parseInt(value, 16));
    const mixed = start.map((channel, index) => {
      const value = Math.round(channel + (end[index] - channel) * factor);
      return value.toString(16).padStart(2, '0');
    });

    return `#${mixed.join('')}`;
  };

  const getHeatColor = (ratio) => {
    if (ratio <= 0.33) {
      return interpolateColor(brandColors.azul, brandColors.azulClaro, ratio / 0.33);
    }

    if (ratio <= 0.66) {
      return interpolateColor(brandColors.azulClaro, brandColors.verde, (ratio - 0.33) / 0.33);
    }

    return interpolateColor(brandColors.verde, brandColors.laranjaEscuro, (ratio - 0.66) / 0.34);
  };

  const drawDiffuseHeatLayer = (map, pontos, maxVotos) => {
    const overlayPane = map.getPanes().overlayPane;
    const canvas = document.createElement('canvas');
    canvas.style.position = 'absolute';
    canvas.style.top = '0';
    canvas.style.left = '0';
    canvas.style.pointerEvents = 'none';
    canvas.style.mixBlendMode = 'multiply';
    canvas.style.opacity = '0.88';
    overlayPane.appendChild(canvas);

    const redraw = () => {
      const size = map.getSize();
      const topLeft = map.containerPointToLayerPoint([0, 0]);

      canvas.width = size.x;
      canvas.height = size.y;
      canvas.style.width = `${size.x}px`;
      canvas.style.height = `${size.y}px`;
      L.DomUtil.setPosition(canvas, topLeft);

      const ctx = canvas.getContext('2d');
      ctx.clearRect(0, 0, size.x, size.y);

      pontos.forEach((ponto) => {
        const point = map.latLngToContainerPoint([ponto.lat, ponto.lng]);
        const ratio = Math.max(0.06, (ponto.total_votos || 0) / maxVotos);
        const radius = Math.max(28, Math.min(90, 28 + ratio * 62));
        const color = getHeatColor(ratio);
        const gradient = ctx.createRadialGradient(point.x, point.y, 0, point.x, point.y, radius);

        gradient.addColorStop(0, `${color}CC`);
        gradient.addColorStop(0.35, `${color}80`);
        gradient.addColorStop(0.7, `${color}32`);
        gradient.addColorStop(1, `${color}00`);

        ctx.beginPath();
        ctx.fillStyle = gradient;
        ctx.arc(point.x, point.y, radius, 0, Math.PI * 2);
        ctx.fill();
      });
    };

    redraw();
    map.on('move zoom resize', redraw);

    return () => {
      map.off('move zoom resize', redraw);
      canvas.remove();
    };
  };

  const loadLeafletMap = (pontos) => {
    if (!mapContainerRef.current || !pontos || pontos.length === 0) {
      console.error('loadLeafletMap: sem container ou pontos válidos', pontos?.length);
      return;
    }

    clearMapInstance();

    if (!mapContainerRef.current) {
      console.error('loadLeafletMap: container nao disponivel');
      return;
    }

    mapContainerRef.current.innerHTML = '';

    const mapDiv = document.createElement('div');
    mapDiv.style.width = '100%';
    mapDiv.style.height = '600px';
    mapDiv.style.borderRadius = '12px';
    mapDiv.style.background = '#EAF2FB';
    mapDiv.id = 'leaflet-heat-map-' + Date.now();
    mapContainerRef.current.appendChild(mapDiv);

    const map = L.map(mapDiv, {
      zoomControl: true,
      scrollWheelZoom: true,
    });

    mapInstanceRef.current = map;

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '&copy; OpenStreetMap',
      maxZoom: 19,
    }).addTo(map);

    const ufDoParlamentar = analysisData?.info?.estado || selectedFilters.estado;
    const pontosValidos = filterPointsByState(
      pontos.filter((point) => point.lat && point.lng),
      ufDoParlamentar
    );

    if (pontosValidos.length === 0) {
      mapDiv.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;font-size:1.2rem;color:#666;">Sem coordenadas disponiveis</div>';
      return;
    }

    const maxVotos = Math.max(...pontosValidos.map((point) => point.total_votos || 1), 1);

    const bounds = L.latLngBounds(pontosValidos.map((point) => [point.lat, point.lng]));
    map.fitBounds(bounds, { padding: [50, 50] });

    const cleanupHeatLayer = drawDiffuseHeatLayer(map, pontosValidos, maxVotos);
    map.on('unload', cleanupHeatLayer);

    pontosValidos.forEach((zona) => {
      const ratio = Math.max(0.06, (zona.total_votos || 0) / maxVotos);
      const color = getHeatColor(ratio);

      const bairros = Array.isArray(zona.bairro) ? zona.bairro : [zona.bairro].filter(Boolean);
      const locais = Array.isArray(zona.local_votacao) ? zona.local_votacao : [zona.local_votacao].filter(Boolean);
      const enderecos = Array.isArray(zona.endereco) ? zona.endereco : [zona.endereco].filter(Boolean);

      L.circleMarker([zona.lat, zona.lng], {
        radius: Math.max(5, Math.min(11, 5 + ratio * 6)),
        fillColor: color,
        color: brandColors.branco,
        weight: 1.6,
        opacity: 0.95,
        fillOpacity: 0.95,
      }).addTo(map).bindPopup(
        [
          `<strong>${zona.municipio || 'N/A'}/${zona.estado || 'N/A'}</strong>`,
          bairros.length ? `Bairros: ${bairros.join(', ')}` : null,
          locais.length ? `Locais: ${locais.join(' | ')}` : null,
          enderecos.length ? `Endereços: ${enderecos.join(' | ')}` : null,
          zona.zonas.length ? `Zonas: ${zona.zonas.join(', ')}` : null,
          zona.secoes.length ? `Seções: ${zona.secoes.join(', ')}` : null,
          `Votos: ${(zona.total_votos || 0).toLocaleString('pt-BR')}`,
          `Coordenadas: ${zona.lat.toFixed(5)}, ${zona.lng.toFixed(5)}`,
          zona.quantidade_zonas ? `Total de zonas nesta coordenada: ${zona.quantidade_zonas}` : null,
          zona.quantidade_secoes ? `Total de seções nesta coordenada: ${zona.quantidade_secoes}` : null,
        ].filter(Boolean).join('<br>')
      );
    });

    setTimeout(() => {
      map.invalidateSize();
    }, 0);
  };

  const loadFallbackMap = (municipios) => {
    if (!mapContainerRef.current || !municipios || municipios.length === 0) return;

    const mapDiv = document.createElement('div');
    mapDiv.style.cssText = `
      width: 100%;
      height: 600px;
      background: linear-gradient(135deg, #009739 0%, #003366 100%);
      border-radius: 12px;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      color: white;
      position: relative;
      overflow: hidden;
    `;

    const title = document.createElement('h2');
    title.textContent = '🗺️ Mapa Eleitoral - Redutos';
    title.style.cssText = `
      margin: 0 0 30px 0;
      font-size: 2rem;
      text-align: center;
      text-shadow: 2px 2px 4px rgba(0,0,0,0.3);
    `;

    const statsGrid = document.createElement('div');
    statsGrid.style.cssText = `
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
      gap: 20px;
      width: 100%;
      max-width: 900px;
      padding: 0 20px;
    `;

    const totalVotos = municipios.reduce((sum, m) => sum + (m.total_votos || 0), 0);
    const municipiosUnicos = municipios.length;
    const municipioMaisVotos = municipios[0];
    const totalSessoes = municipios.reduce((sum, m) => sum + (m.sessoes || 0), 0);

    const statistics = [
      { label: 'Municípios', valor: municipiosUnicos, cor: brandColors.verde },
      { label: 'Total de Votos', valor: (totalVotos || 0).toLocaleString('pt-BR'), cor: '#4F81BD' },
      { label: 'Sessões Eleitorais', valor: (totalSessoes || 0).toLocaleString('pt-BR'), cor: '#FFF81C' },
      { label: 'Maior Reduto', valor: municipioMaisVotos?.municipio || 'N/A', cor: '#66BB6A' },
    ];

    statistics.forEach((stat) => {
      const statDiv = document.createElement('div');
      statDiv.style.cssText = `
        background: rgba(255,255,255,0.1);
        padding: 20px;
        border-radius: 12px;
        text-align: center;
        backdrop-filter: blur(10px);
        border: 1px solid rgba(255,255,255,0.2);
      `;

      statDiv.innerHTML = `
        <div style="font-size: 2.5rem; font-weight: bold; color: ${stat.cor}; margin-bottom: 10px;">
          ${stat.valor}
        </div>
        <div style="font-size: 1rem; opacity: 0.9;">
          ${stat.label}
        </div>
      `;

      statsGrid.appendChild(statDiv);
    });

    const listDiv = document.createElement('div');
    listDiv.style.cssText = `
      margin-top: 30px;
      max-height: 250px;
      overflow-y: auto;
      width: 100%;
      max-width: 800px;
      padding: 0 20px;
    `;

    const topList = document.createElement('div');
    topList.style.cssText = `
      display: grid;
      gap: 10px;
    `;

    municipios.slice(0, 10).forEach((municipio, index) => {
      const item = document.createElement('div');
      item.style.cssText = `
        background: rgba(255,255,255,0.1);
        padding: 12px;
        border-radius: 8px;
        display: flex;
        justify-content: space-between;
        align-items: center;
        backdrop-filter: blur(5px);
        border: 1px solid rgba(255,255,255,0.1);
      `;

      item.innerHTML = `
        <div style="display: flex; align-items: center; gap: 10px; flex: 1;">
          <span style="font-weight: bold; color: ${brandColors.amarelo}; font-size: 1.2rem;">
            #${index + 1}
          </span>
          <div>
            <div style="font-weight: 600;">${municipio.municipio || 'N/A'}, ${municipio.estado || 'N/A'}</div>
            <div style="font-size: 0.9rem; opacity: 0.8;">${municipio.sessoes || 0} sessões</div>
          </div>
        </div>
        <div style="color: ${brandColors.verde}; font-weight: bold; font-size: 1.1rem;">
          ${(municipio.total_votos || 0).toLocaleString('pt-BR')} votos
        </div>
      `;

      topList.appendChild(item);
    });

    listDiv.appendChild(topList);

    mapDiv.appendChild(title);
    mapDiv.appendChild(statsGrid);
    mapDiv.appendChild(listDiv);

    mapContainerRef.current.innerHTML = '';
    mapContainerRef.current.appendChild(mapDiv);
  };

  return (
    <Box sx={{ backgroundColor: '#FFFFFF', minHeight: '100vh', py: 3 }}>
      <Container maxWidth="xl">
        <Typography variant="h3" sx={{ color: '#003366', mb: 4, fontWeight: 'bold' }}>
          🗺️ Mapa Eleitoral - Redutos
        </Typography>
        <Typography variant="body1" sx={{ color: '#666666', mb: 4 }}>
          Visualize geograficamente onde cada parlamentar teve mais votos nas eleições de 2022
        </Typography>

        <FilterSelector
        requireSelection={true}
        requireAll={true}
          onFiltersChange={handleFilterChange}
          fields={['estado', 'partido', 'parlamentar']}
          showComissao={false}
          useCurrentParty={true}
        />

        <Box sx={{ mt: 3, mb: 3 }}>
          <Button
            variant="contained"
            size="large"
            onClick={handleAnalyze}
            disabled={loading || !selectedFilters.estado || selectedFilters.estado === 'Todos' || !selectedFilters.partido || selectedFilters.partido === 'Todos' || !selectedFilters.parlamentar || selectedFilters.parlamentar === 'Todos'}
            sx={{
              borderRadius: '14px',
              px: 4,
              py: 1.5,
              backgroundColor: '#009739',
              color: 'white',
              fontWeight: 'bold',
              boxShadow: '0 8px 20px rgba(0, 151, 57, 0.25)',
              '&:hover': {
                backgroundColor: '#007d2f',
              },
            }}
          >
            {loading ? 'Carregando análise eleitoral...' : 'Executar Filtro'}
          </Button>
        </Box>

        {(!selectedFilters.parlamentar || loading) && (
          <Box sx={{ mb: 3 }}>
            <Alert
              severity="info"
              sx={{ borderRadius: '12px' }}
            >
              {loading
                ? `Carregando o mapa e os redutos territoriais de ${selectedFilters.parlamentarLabel || selectedFilters.parlamentar}...`
                : 'Selecione um parlamentar e clique em "Executar Filtro" para carregar o mapa eleitoral e os redutos já processados.'}
            </Alert>
          </Box>
        )}

        {error && (
          <Alert severity="error" sx={{ mb: 3 }}>
            {error}
          </Alert>
        )}

        {loading && (
          <Box sx={{ display: 'flex', justifyContent: 'center', my: 5 }}>
            <CircularProgress size={60} />
          </Box>
        )}

        {analysisData && !loading && (
          <>
            {analysisData.info && (
              <Paper sx={{ p: 4, mb: 3, borderRadius: '12px', bgcolor: '#003366', color: 'white' }}>
                <Grid container spacing={3} alignItems="center">
                  <Grid item xs={12} md={3}>
                    {analysisData.info.foto && (
                      <Box sx={{ bgcolor: 'white', borderRadius: '50%', p: 0.5, width: 148, height: 148, mx: 'auto', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                        <Avatar
                          src={analysisData.info.foto}
                          sx={{ width: 140, height: 140, border: '4px solid #009739' }}
                        />
                      </Box>
                    )}
                  </Grid>
                  <Grid item xs={12} md={6}>
                    <Typography variant="h5" sx={{ fontWeight: 'bold', color: 'white', mb: 2 }}>
                      {analysisData.info?.nome || 'N/A'}
                    </Typography>
                    <Box sx={{ display: 'flex', gap: 2, flexWrap: 'wrap' }}>
                      <Chip label={analysisData.info?.partido || 'N/A'} sx={{ backgroundColor: 'white', color: '#009739', fontWeight: 'bold' }} />
                      <Chip label={analysisData.info?.estado || 'N/A'} sx={{ backgroundColor: 'rgba(255,255,255,0.2)', color: 'white', fontWeight: 'bold' }} />
                    </Box>
                  </Grid>
                  <Grid item xs={12} md={3} sx={{ display: 'flex', gap: 2, justifyContent: 'center' }}>
                    {normalizeCommonsFileUrl(analysisData.info.logoPartido) && (
                      <Box sx={{ bgcolor: 'white', borderRadius: '50%', p: 2, width: 120, height: 120, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                        <Box component="img" src={normalizeCommonsFileUrl(analysisData.info.logoPartido)} sx={{ maxWidth: '100%', maxHeight: '100%', display: 'block', objectFit: 'contain' }} />
                      </Box>
                    )}
                    {normalizeCommonsFileUrl(analysisData.info.estado_logo_url) && (
                      <Box sx={{ bgcolor: 'white', borderRadius: '50%', p: 2, width: 120, height: 120, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                        <Box component="img" src={normalizeCommonsFileUrl(analysisData.info.estado_logo_url)} sx={{ maxWidth: '100%', maxHeight: '100%', display: 'block', objectFit: 'contain' }} />
                      </Box>
                    )}
                  </Grid>
                </Grid>
              </Paper>
            )}

            {analysisData.stats && (
              <Grid container spacing={3} sx={{ mb: 4 }}>
                <Grid item xs={12} sm={6} lg={3}>
                  <Card sx={statCardSx}>
                    <CardContent sx={{ p: 3.5, height: '100%', display: 'flex', flexDirection: 'column', justifyContent: 'space-between' }}>
                      <Typography variant="h6" sx={{ color: '#5F6B7A', mb: 2, fontWeight: 700 }}>
                        {analysisData.stats?.fonte_total_votos === 'tse_csv_oficial' ? 'Total Oficial de Votos' : 'Total de Votos'}
                      </Typography>
                      <Typography variant="h2" sx={{ fontWeight: 800, color: brandColors.verde, lineHeight: 1, letterSpacing: '-0.03em' }}>
                        {(analysisData.stats?.total_votos || analysisData.stats?.totalVotos || 0).toLocaleString('pt-BR')}
                      </Typography>
                    </CardContent>
                  </Card>
                </Grid>
                <Grid item xs={12} sm={6} lg={3}>
                  <Card sx={statCardSx}>
                    <CardContent sx={{ p: 3.5, height: '100%', display: 'flex', flexDirection: 'column', justifyContent: 'space-between' }}>
                      <Typography variant="h6" sx={{ color: '#5F6B7A', mb: 2, fontWeight: 700 }}>
                        Municípios
                      </Typography>
                      <Typography variant="h2" sx={{ fontWeight: 800, color: brandColors.azul, lineHeight: 1, letterSpacing: '-0.03em' }}>
                        {analysisData.stats?.total_municipios || analysisData.stats?.totalMunicipios || 0}
                      </Typography>
                    </CardContent>
                  </Card>
                </Grid>
                <Grid item xs={12} sm={6} lg={3}>
                  <Card sx={statCardSx}>
                    <CardContent sx={{ p: 3.5, height: '100%', display: 'flex', flexDirection: 'column', justifyContent: 'space-between' }}>
                      <Typography variant="h6" sx={{ color: '#5F6B7A', mb: 2, fontWeight: 700 }}>
                        Sessões Eleitorais
                      </Typography>
                      <Typography variant="h2" sx={{ fontWeight: 800, color: brandColors.azulClaro, lineHeight: 1, letterSpacing: '-0.03em' }}>
                        {(analysisData.stats?.total_secoes || analysisData.stats?.totalSessoes || 0).toLocaleString('pt-BR')}
                      </Typography>
                    </CardContent>
                  </Card>
                </Grid>
                <Grid item xs={12} sm={6} lg={3}>
                  <Card sx={statCardSx}>
                    <CardContent sx={{ p: 3.5, height: '100%', display: 'flex', flexDirection: 'column', justifyContent: 'space-between' }}>
                      <Typography variant="h6" sx={{ color: '#5F6B7A', mb: 2, fontWeight: 700 }}>
                        Principal Reduto
                      </Typography>
                      <Typography
                        variant="h4"
                        sx={{
                          fontWeight: 800,
                          color: brandColors.verdeClaro,
                          lineHeight: 1.12,
                          letterSpacing: '-0.02em',
                          overflowWrap: 'anywhere',
                          wordBreak: 'break-word',
                          display: '-webkit-box',
                          WebkitLineClamp: 3,
                          WebkitBoxOrient: 'vertical',
                          overflow: 'hidden',
                        }}
                      >
                        {analysisData.stats?.principal_reduto || 'N/A'}
                      </Typography>
                    </CardContent>
                  </Card>
                </Grid>
              </Grid>
            )}

            <Box sx={{ mb: 4 }}>
              <Typography variant="h5" sx={{ color: '#003366', fontWeight: 'bold', mb: 2 }}>
                🗺️ Mapa de Redutos Eleitorais
              </Typography>
              <Paper sx={{ p: 3, borderRadius: '12px', backgroundColor: '#FFFFFF', overflow: 'hidden' }}>
                <Box
                  ref={mapContainerRef}
                  sx={{
                    width: '100%',
                    minHeight: '600px',
                    borderRadius: '12px',
                  }}
                />
                <Alert severity="info" sx={{ mt: 2, borderRadius: '8px' }}>
                  <Typography variant="body2" sx={{ color: '#003366' }}>
                    <strong>ℹ️ Sobre as coordenadas:</strong> As coordenadas geográficas utilizadas neste mapa foram obtidas através de biblioteca de geocoding e podem conter erros.
                    Alguns pontos podem estar localizados fora do estado do parlamentar ou em localizações imprecisas.
                    Os dados são apresentados apenas para fins de visualização geográfica dos redutos eleitorais.
                  </Typography>
                </Alert>
              </Paper>
            </Box>

            {analysisData.topMunicipios && analysisData.topMunicipios.length > 0 && (
              <Box sx={{ mb: 4 }}>
                <Typography variant="h5" sx={{ color: '#003366', fontWeight: 'bold', mb: 2 }}>
                  🏆 Top 10 Municípios - Mais Votos
                </Typography>
                <Paper sx={{ p: 3, borderRadius: '12px', backgroundColor: '#FFFFFF' }}>
                  <EChartWrapper
                    option={createTreeMapOption(
                      analysisData.topMunicipios.slice(0, 10).map(m => ({
                        name: m.municipio,
                        value: m.total_votos
                      })),
                      'Top 10 Municípios'
                    )}
                    height="500px"
                  />
                  {loadingIbgeResumo && (
                    <Box sx={{ mt: 2, py: 2 }}>
                      <Typography variant="body2" sx={{ color: '#5F6B7A' }}>
                        Carregando síntese socioeconômica do IBGE para o top 10...
                      </Typography>
                    </Box>
                  )}
                  {!loadingIbgeResumo && ibgeResumoError && (
                    <Alert severity="info" sx={{ mt: 2, borderRadius: '10px' }}>
                      <Typography variant="body2" sx={{ color: '#003366' }}>
                        {ibgeResumoError}
                      </Typography>
                      <Typography variant="caption" sx={{ display: 'block', mt: 1, color: '#5F6B7A' }}>
                        Quando disponíveis, estes blocos passam a usar microterritórios específicos do IBGE, vinculados aos polígonos/setores onde o deputado concentrou votos.
                      </Typography>
                    </Alert>
                  )}
                  {!loadingIbgeResumo && !ibgeResumoError && ibgeResumoContextoNota && (
                    <Alert severity={ibgeResumoCacheStatus === 'hit_granular' ? 'success' : 'warning'} sx={{ mt: 2, borderRadius: '10px' }}>
                      <Typography variant="body2" sx={{ color: '#003366' }}>
                        {ibgeResumoContextoNota}
                      </Typography>
                      {ibgeResumoCacheStatus === 'hit_municipal' && (
                        <Typography variant="caption" sx={{ display: 'block', mt: 1, color: '#5F6B7A' }}>
                          O fallback municipal deixou de ser a referência desejada. Para refletir o reduto real, a página precisa do cache territorial granular por polígono/setor censitário.
                        </Typography>
                      )}
                    </Alert>
                  )}
                  {ibgeResumoTop10?.filter((item) => item?.value && item.value !== 'N/D').length > 0 && (
                    <Box sx={{ mt: 2 }}>
                      <Typography variant="h6" sx={{ color: brandColors.azul, fontWeight: 800, mb: 0.5 }}>
                        Resumo Executivo do Reduto
                      </Typography>
                      <Typography variant="body2" sx={{ color: '#5F6B7A', lineHeight: 1.7, mb: 2 }}>
                        Comece por estes indicadores-chave. Eles sintetizam o perfil médio do território onde o deputado concentra votos e funcionam como âncoras para interpretar os gráficos abaixo.
                      </Typography>
                    <Grid container spacing={2} sx={{ mt: 1 }}>
                      {ibgeResumoTop10
                        .filter((item) => item?.value && item.value !== 'N/D')
                        .map((item, index) => (
                        <Grid item xs={12} sm={6} lg={3} key={item.label}>
                          <Card
                            sx={{
                              height: '100%',
                              borderRadius: '16px',
                              backgroundColor: '#F8FAFC',
                              border: '1px solid #E6ECF3',
                              boxShadow: '0 8px 20px rgba(0, 51, 102, 0.06)',
                            }}
                          >
                            <CardContent sx={{ p: 2.5 }}>
                              <Typography variant="body2" sx={{ color: '#5F6B7A', fontWeight: 700, mb: 1 }}>
                                {item.label}
                              </Typography>
                              <Typography
                                variant="h4"
                                sx={{
                                  color: [brandColors.verde, brandColors.azul, brandColors.azulClaro, brandColors.laranjaEscuro][index % 4],
                                  fontWeight: 800,
                                  lineHeight: 1.1,
                                  letterSpacing: '-0.02em',
                                  mb: 1,
                                  overflowWrap: 'anywhere',
                                }}
                              >
                                {item.value}
                              </Typography>
                              <Typography variant="caption" sx={{ color: '#6B7280', lineHeight: 1.5 }}>
                                {item.caption}
                              </Typography>
                              {(
                                item.comparisons?.estado !== null && item.comparisons?.estado !== undefined
                              ) || (
                                item.comparisons?.regiao !== null && item.comparisons?.regiao !== undefined
                              ) || (
                                item.comparisons?.brasil !== null && item.comparisons?.brasil !== undefined
                              ) ? (
                                <Box sx={{ mt: 1.5, pt: 1.5, borderTop: '1px solid #E5E7EB' }}>
                                  {item.comparisons?.estado !== null && item.comparisons?.estado !== undefined && (
                                    <Typography variant="caption" sx={{ display: 'block', color: '#6B7280' }}>
                                      {selectedFilters.estado || 'Estado'}: {formatComparisonValue(item.comparisons?.estado, item.format)}
                                    </Typography>
                                  )}
                                  {item.comparisons?.regiao !== null && item.comparisons?.regiao !== undefined && (
                                    <Typography variant="caption" sx={{ display: 'block', color: '#6B7280' }}>
                                      {getRegionLabel(selectedFilters.estado)}: {formatComparisonValue(item.comparisons?.regiao, item.format)}
                                    </Typography>
                                  )}
                                  {item.comparisons?.brasil !== null && item.comparisons?.brasil !== undefined && (
                                    <Typography variant="caption" sx={{ display: 'block', color: '#6B7280' }}>
                                      Brasil: {formatComparisonValue(item.comparisons?.brasil, item.format)}
                                    </Typography>
                                  )}
                                  {item.deltaBrasil && (
                                    <Typography
                                      variant="caption"
                                      sx={{
                                        display: 'block',
                                        mt: 0.5,
                                        color: item.deltaBrasil.trim().startsWith('+') ? brandColors.verde : brandColors.laranjaEscuro,
                                        fontWeight: 700,
                                      }}
                                    >
                                      {item.deltaBrasil}
                                    </Typography>
                                  )}
                                </Box>
                              ) : null}
                            </CardContent>
                          </Card>
                        </Grid>
                      ))}
                    </Grid>
                    </Box>
                  )}
                  {!loadingIbgeResumo && ibgeResumoCacheStatus === 'hit_granular' && hasMicroterritorioCharts && (
                    <Box sx={{ mt: 4 }}>
                      <Paper
                        sx={{
                          p: 2.5,
                          mb: 2.5,
                          borderRadius: '16px',
                          background: 'linear-gradient(180deg, #F8FAFC 0%, #FFFFFF 100%)',
                          border: '1px solid #E6ECF3',
                          boxShadow: '0 8px 20px rgba(0, 51, 102, 0.05)',
                        }}
                      >
                        <Typography variant="h6" sx={{ color: brandColors.azul, fontWeight: 800, mb: 0.5 }}>
                          Perfil da População nos Microterritórios Dominantes
                        </Typography>
                        <Typography variant="body2" sx={{ color: '#5F6B7A', lineHeight: 1.7 }}>
                          Estes gráficos descrevem o território, não o indivíduo. Eles usam os 10 microterritórios mais fortes do deputado e mostram a tendência média das regiões onde ele concentra votos.
                        </Typography>
                        <Typography variant="caption" sx={{ display: 'block', mt: 1.25, color: '#6B7280' }}>
                          Núcleo usado: {microterritorioCharts.core.selected.length} microterritórios, cobrindo{' '}
                          {microterritorioCharts.core.voteCoverage.toFixed(1)}% dos votos do top 10 setorial.
                        </Typography>
                      </Paper>
                      <Grid container spacing={2}>
                        {microterritorioCharts.groups.map((group) => (
                          <Grid item xs={12} key={group.key}>
                            <Card
                              sx={{
                                borderRadius: '18px',
                                backgroundColor: '#FFFFFF',
                                border: '1px solid #E6ECF3',
                                boxShadow: '0 8px 20px rgba(0, 51, 102, 0.05)',
                              }}
                            >
                              <CardContent sx={{ p: 2.5 }}>
                                <Grid container spacing={2}>
                                  <Grid item xs={12} lg={4}>
                                    <Box sx={{ pr: { lg: 1 } }}>
                                      <Typography variant="h6" sx={{ color: brandColors.azul, fontWeight: 800, mb: 1 }}>
                                        {group.title}
                                      </Typography>
                                      <Typography variant="body2" sx={{ color: brandColors.azul, fontWeight: 700, lineHeight: 1.6, mb: 1.5 }}>
                                        {extractTakeaway(group.interpretation)}
                                      </Typography>
                                      <Typography variant="body2" sx={{ color: '#5F6B7A', lineHeight: 1.7 }}>
                                        {compactInterpretation(group.interpretation)}
                                      </Typography>
                                    </Box>
                                  </Grid>
                                  <Grid item xs={12} lg={8}>
                                    {group.charts.length > 0 && (
                                      <Grid container spacing={2}>
                                        {group.charts.map((chart) => (
                                          <Grid item xs={12} lg={chart.span || (group.charts.length > 1 ? 6 : 12)} key={`${group.key}-${chart.title}`}>
                                            <Paper
                                              sx={{
                                                p: 1.5,
                                                borderRadius: '14px',
                                                backgroundColor: '#F8FAFC',
                                                border: '1px solid #E6ECF3',
                                              }}
                                            >
                                              <EChartWrapper option={chart.option} height="320px" />
                                            </Paper>
                                          </Grid>
                                        ))}
                                      </Grid>
                                    )}
                                  </Grid>
                                </Grid>
                              </CardContent>
                            </Card>
                          </Grid>
                        ))}
                      </Grid>
                    </Box>
                  )}
                  {!loadingIbgeResumo && ibgeResumoCacheStatus === 'hit_granular' && hasZonaEleitoralProfile && (
                    <Box sx={{ mt: 4 }}>
                      <Box sx={{ mb: 2.5 }}>
                        <Typography variant="h6" sx={{ color: brandColors.azul, fontWeight: 800, mb: 0.5 }}>
                          Pareto Territorial das Zonas Eleitorais Mais Fortes
                        </Typography>
                        <Typography variant="body2" sx={{ color: '#5F6B7A', lineHeight: 1.7 }}>
                          Este bloco mostra <strong>quão concentrada está a votação do deputado em poucas zonas eleitorais</strong>. Aqui o foco não é o perfil social
                          do território, mas a distribuição dos votos: quantas zonas sustentam a maior parte da votação, qual é a zona líder e quanta vantagem ela
                          tem sobre a segunda colocada.
                        </Typography>
                        <Typography variant="caption" sx={{ display: 'block', mt: 1, color: '#6B7280' }}>
                          No recorte atual, {zonaEleitoralProfile.core.selected.length} zonas já concentram {zonaEleitoralProfile.core.voteCoverage.toFixed(1)}% dos votos
                          agregados por zona. Já o grupo das {zonaEleitoralProfile.core.paretoZoneCount} zonas mais fortes, equivalente a 20% do total mapeado,
                          responde sozinho por {zonaEleitoralProfile.core.paretoCoverage.toFixed(1)}% dos votos.
                        </Typography>
                      </Box>

                      <Grid container spacing={2} sx={{ mb: 2 }}>
                        {zonaEleitoralProfile.cards.map((item, index) => (
                          <Grid item xs={12} sm={6} lg={3} key={item.label}>
                            <Card
                              sx={{
                                height: '100%',
                                borderRadius: '16px',
                                backgroundColor: '#F8FAFC',
                                border: '1px solid #E6ECF3',
                                boxShadow: '0 8px 20px rgba(0, 51, 102, 0.06)',
                              }}
                            >
                              <CardContent sx={{ p: 2.5 }}>
                                <Typography variant="body2" sx={{ color: '#5F6B7A', fontWeight: 700, mb: 1 }}>
                                  {item.label}
                                </Typography>
                                <Typography
                                  variant="h4"
                                  sx={{
                                    color: [brandColors.azul, brandColors.verde, brandColors.azulClaro, brandColors.laranjaEscuro][index % 4],
                                    fontWeight: 800,
                                    lineHeight: 1.1,
                                    letterSpacing: '-0.02em',
                                    mb: 1,
                                    overflowWrap: 'anywhere',
                                  }}
                                >
                                  {item.value}
                                </Typography>
                                <Typography variant="caption" sx={{ color: '#6B7280', lineHeight: 1.5 }}>
                                  {item.caption}
                                </Typography>
                              </CardContent>
                            </Card>
                          </Grid>
                        ))}
                      </Grid>

                      {zonaEleitoralProfile.chart && (
                        <Paper
                          sx={{
                            p: 1.5,
                            borderRadius: '14px',
                            backgroundColor: '#F8FAFC',
                            border: '1px solid #E6ECF3',
                            mb: 2,
                          }}
                        >
                          <EChartWrapper option={zonaEleitoralProfile.chart} height="380px" />
                        </Paper>
                      )}

                      <TableContainer component={Paper} sx={{ borderRadius: '14px', border: '1px solid #E6ECF3', boxShadow: 'none' }}>
                        <Table size="small">
                          <TableHead>
                            <TableRow sx={{ backgroundColor: '#F8FAFC' }}>
                              <TableCell sx={{ fontWeight: 800, color: brandColors.azul }}>Zona</TableCell>
                              <TableCell sx={{ fontWeight: 800, color: brandColors.azul }}>Votos</TableCell>
                              <TableCell sx={{ fontWeight: 800, color: brandColors.azul }}>Municípios</TableCell>
                              <TableCell sx={{ fontWeight: 800, color: brandColors.azul }}>Setores</TableCell>
                              <TableCell sx={{ fontWeight: 800, color: brandColors.azul }}>Renda Média</TableCell>
                              <TableCell sx={{ fontWeight: 800, color: brandColors.azul }}>Água / Esgoto</TableCell>
                            </TableRow>
                          </TableHead>
                          <TableBody>
                            {zonaEleitoralProfile.zonas.slice(0, 10).map((zona) => (
                              <TableRow key={zona.zona}>
                                <TableCell>{zona.zona}</TableCell>
                                <TableCell>{(zona.total_votos || 0).toLocaleString('pt-BR')}</TableCell>
                                <TableCell>{zona.municipios.slice(0, 3).join(', ') || 'N/D'}</TableCell>
                                <TableCell>{zona.quantidade_setores}</TableCell>
                                <TableCell>
                                  {zona.indicadores?.renda_media_responsavel !== null && zona.indicadores?.renda_media_responsavel !== undefined
                                    ? `R$ ${Number(zona.indicadores.renda_media_responsavel).toLocaleString('pt-BR', { maximumFractionDigits: 0 })}`
                                    : 'N/D'}
                                </TableCell>
                                <TableCell>
                                  {zona.indicadores?.rede_geral_agua !== null && zona.indicadores?.rede_geral_agua !== undefined
                                    ? `${Number(zona.indicadores.rede_geral_agua).toFixed(1)}%`
                                    : 'N/D'}
                                  {' / '}
                                  {zona.indicadores?.rede_esgoto !== null && zona.indicadores?.rede_esgoto !== undefined
                                    ? `${Number(zona.indicadores.rede_esgoto).toFixed(1)}%`
                                    : 'N/D'}
                                </TableCell>
                              </TableRow>
                            ))}
                          </TableBody>
                        </Table>
                      </TableContainer>
                    </Box>
                  )}
                  {!loadingIbgeResumo && ibgeResumoCacheStatus === 'hit_granular' && !hasMicroterritorioCharts && (
                    <Alert severity="info" sx={{ mt: 3, borderRadius: '10px' }}>
                      <Typography variant="body2" sx={{ color: '#003366' }}>
                        O cache granular já existe, mas ainda não trouxe indicadores setoriais suficientes para desenhar os gráficos populacionais deste parlamentar.
                      </Typography>
                    </Alert>
                  )}
                </Paper>
              </Box>
            )}

            {analysisData.bairros && analysisData.bairros.length > 0 && (
              <Box sx={{ mb: 4 }}>
                <Typography variant="h5" sx={{ color: '#003366', fontWeight: 'bold', mb: 2 }}>
                  📊 Detalhamento por Bairro
                </Typography>
                <Paper sx={{ p: 3, borderRadius: '12px', backgroundColor: '#f8f9fa' }}>
                  <Typography variant="body2" sx={{ color: '#666666', mb: 2 }}>
                    Exibindo Top 20 bairros (de {analysisData.bairros.length} total)
                  </Typography>
                  <TableContainer>
                    <Table>
                      <TableHead>
                        <TableRow sx={{ backgroundColor: '#e8f5e9' }}>
                          <TableCell sx={{ fontWeight: 'bold', color: '#003366' }}>#</TableCell>
                          <TableCell sx={{ fontWeight: 'bold', color: '#003366' }}>Bairro</TableCell>
                          <TableCell sx={{ fontWeight: 'bold', color: '#003366' }}>Município</TableCell>
                          <TableCell sx={{ fontWeight: 'bold', color: '#003366' }}>UF</TableCell>
                          <TableCell align="right" sx={{ fontWeight: 'bold', color: '#003366' }}>Total de Votos</TableCell>
                          <TableCell align="right" sx={{ fontWeight: 'bold', color: '#003366' }}>Percentual (%)</TableCell>
                        </TableRow>
                      </TableHead>
                      <TableBody>
                        {analysisData.bairros.slice(0, 20).map((bairro, index) => (
                          <TableRow
                            key={`${bairro.bairro}-${bairro.municipio}-${index}`}
                            sx={{
                              '&:nth-of-type(odd)': { backgroundColor: '#FFFFFF' },
                              '&:hover': { backgroundColor: '#f0f0f0' },
                            }}
                          >
                            <TableCell sx={{ fontWeight: 'bold', color: '#009739' }}>#{index + 1}</TableCell>
                            <TableCell sx={{ fontWeight: 'bold', color: '#003366' }}>
                              {bairro.bairro || 'N/A'}
                            </TableCell>
                            <TableCell>{bairro.municipio || 'N/A'}</TableCell>
                            <TableCell>{bairro.estado || 'N/A'}</TableCell>
                            <TableCell align="right">{(bairro.total_votos || 0).toLocaleString('pt-BR')}</TableCell>
                            <TableCell align="right">{bairro.percentual ? bairro.percentual.toFixed(2) : '0.00'}%</TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </TableContainer>
                </Paper>
              </Box>
            )}

            {/* Seção de Análise de IA */}
            <Box sx={{ mb: 4 }}>
              <Paper sx={{ p: 4, borderRadius: '12px', backgroundColor: '#e3f2fd', border: '1px solid #bbdefb' }}>
                <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 2 }}>
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
                    <Box component="img" src="/assets/images/manifesto/antunes_community.png" sx={{ width: 60, height: 60, objectFit: 'contain' }} />
                    <Typography variant="h5" sx={{ color: '#0d47a1', fontWeight: 'bold' }}>
                      Robô Antunes analisa o perfil do eleitor de {selectedFilters.parlamentarLabel || selectedFilters.parlamentar || '...'}
                    </Typography>
                  </Box>
                  {!aiAnalysis && !loadingAi && (
                    <Button
                      variant="contained"
                      onClick={handleGenerateAnalysis}
                      sx={{
                        backgroundColor: '#1565c0',
                        '&:hover': { backgroundColor: '#0d47a1' },
                        fontWeight: 'bold',
                        textTransform: 'none',
                        borderRadius: '8px',
                        px: 3
                      }}
                    >
                      ✨ Gerar Análise Inteligente
                    </Button>
                  )}
                </Box>

                {loadingAi && (
                  <Box sx={{ py: 2 }}>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, mb: 3 }}>
                      <CircularProgress size={28} sx={{ color: '#1565c0' }} />
                      <Box>
                        <Typography variant="body1" sx={{ color: '#0d47a1', fontWeight: 700 }}>
                          {ANTUNES_LOADING_STEPS[aiLoadingStep].agent}: {ANTUNES_LOADING_STEPS[aiLoadingStep].title}
                        </Typography>
                        <Typography variant="body2" sx={{ color: '#546e7a' }}>
                          {ANTUNES_LOADING_STEPS[aiLoadingStep].description}
                        </Typography>
                      </Box>
                    </Box>

                    <Box sx={{ mb: 3 }}>
                      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
                        <Typography variant="body2" sx={{ color: '#0d47a1', fontWeight: 700 }}>
                          Progresso do relatório
                        </Typography>
                        <Typography variant="body2" sx={{ color: '#546e7a', fontFamily: 'monospace' }}>
                          {aiLoadingProgress}%
                        </Typography>
                      </Box>
                      <LinearProgress
                        variant="determinate"
                        value={aiLoadingProgress}
                        sx={{
                          height: 10,
                          borderRadius: '999px',
                          backgroundColor: 'rgba(13, 71, 161, 0.12)',
                          '& .MuiLinearProgress-bar': {
                            borderRadius: '999px',
                            background: 'linear-gradient(90deg, #1b8f3a 0%, #2e7d32 100%)',
                          },
                        }}
                      />
                      <Typography variant="caption" sx={{ color: '#607d8b', display: 'block', mt: 1 }}>
                        Etapa {aiLoadingStep + 1} de {ANTUNES_LOADING_STEPS.length}
                      </Typography>
                    </Box>

                    <Box
                      sx={{
                        display: 'grid',
                        gap: 1.5,
                        gridTemplateColumns: { xs: '1fr', md: 'repeat(2, minmax(0, 1fr))' },
                      }}
                    >
                      {ANTUNES_LOADING_STEPS.map((step, index) => {
                        const isDone = index < aiLoadingStep;
                        const isActive = index === aiLoadingStep;
                        return (
                          <Box
                            key={`${step.agent}-${step.title}`}
                            sx={{
                              display: 'flex',
                              gap: 1.5,
                              alignItems: 'flex-start',
                              p: 1.5,
                              borderRadius: '12px',
                              border: `1px solid ${isActive ? '#64b5f6' : '#d7e6f7'}`,
                              backgroundColor: isActive ? 'rgba(255,255,255,0.58)' : 'rgba(255,255,255,0.38)',
                              boxShadow: isActive ? '0 6px 18px rgba(21, 101, 192, 0.12)' : 'none',
                            }}
                          >
                            <Box
                              sx={{
                                minWidth: 28,
                                width: 28,
                                height: 28,
                                borderRadius: '50%',
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'center',
                                fontSize: '0.9rem',
                                fontWeight: 800,
                                color: isDone ? '#fff' : isActive ? '#1565c0' : '#78909c',
                                backgroundColor: isDone ? '#2e7d32' : isActive ? '#e3f2fd' : '#eef4fb',
                                border: isDone ? 'none' : `1px solid ${isActive ? '#64b5f6' : '#d7e6f7'}`,
                              }}
                            >
                              {isDone ? '✓' : index + 1}
                            </Box>
                            <Box>
                              <Typography variant="body2" sx={{ color: '#0d47a1', fontWeight: 700 }}>
                                {step.agent}: {step.title}
                              </Typography>
                              <Typography variant="caption" sx={{ color: '#607d8b', lineHeight: 1.6 }}>
                                {step.description}
                              </Typography>
                            </Box>
                          </Box>
                        );
                      })}
                    </Box>
                  </Box>
                )}
              </Paper>
            </Box>

            {aiAnalysis && (
              <Box sx={{ mt: 4, mb: 4 }}>
                <Paper sx={{ p: 3, borderRadius: '12px', backgroundColor: '#e3f2fd', border: '1px solid #bbdefb' }}>
                  <Box sx={{
                    color: '#0d47a1',
                    '& h1, & h2, & h3, & h4': { color: brandColors.azul, mt: 3, mb: 1.5, lineHeight: 1.2 },
                    '& p': { mb: 2, lineHeight: 1.8, fontSize: '1.05rem' },
                    '& ul, & ol': { mb: 2, pl: 3 },
                    '& li': { mb: 0.8, lineHeight: 1.7 },
                    '& strong': { color: brandColors.azul, fontWeight: 800 },
                  }}>
                    <ReactMarkdown>{aiAnalysis}</ReactMarkdown>
                  </Box>
                  <Typography variant="caption" sx={{ display: 'block', mt: 2, color: '#666', fontStyle: 'italic' }}>
                    * Relatório territorial gerado a partir dos dados oficiais de votação e dos microterritórios do IBGE materializados no projeto.
                  </Typography>
                </Paper>
              </Box>
            )}
          </>
        )}

        {!loading && !analysisData && !error && (
          <Paper sx={{ p: 6, textAlign: 'center', borderRadius: '12px' }}>
            <Typography variant="h6" sx={{ color: '#666666', mb: 2 }}>
              🗺️ Visualização Eleitoral
            </Typography>
            <Typography variant="body2" sx={{ color: '#999999' }}>
              Selecione um parlamentar para visualizar seus redutos eleitorais
            </Typography>
          </Paper>
        )}
      
      <DataSourceFooter
        sources={[{"label":"TSE — Resultados Eleitorais 2022","href":"https://www.tse.jus.br/eleicoes/resultados","type":"tse"},{"label":"IBGE — Municípios","href":"https://www.ibge.gov.br","type":"receita"}]}
        note="Dados eleitorais das eleições de 2022 (Câmara Federal) do TSE. Dados geográficos municipais do IBGE."
      />
    </Container>
    </Box>
  );
};

export default MapaEleitoral2;
