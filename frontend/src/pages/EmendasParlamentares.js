import React, { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import {
  Box,
  Container,
  Typography,
  Paper,
  Grid,
  Button,
  CircularProgress,
  Alert,
  Card,
  CardContent,
  Avatar,
  Chip,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Stack,
  Divider,
  Tooltip,
  Dialog,
  DialogTitle,
  DialogContent,
  TextField,
  MenuItem,
  Select,
  FormControl,
  InputLabel,
  Autocomplete,
  Slider,
  InputAdornment
} from '@mui/material';
import { Assessment, Map as MapIcon, LocalOffer, Groups, Assignment, AutoAwesome, Warning, Gavel, Security, Info, AttachMoney as AttachMoneyIcon, Search, PictureAsPdf as PictureAsPdfIcon, GppBad, VerifiedUser } from '@mui/icons-material';
import ReactMarkdown from 'react-markdown';
import axios from '../config/axios';
import { API_HEADERS, API_BASE_URL } from '../config';
import FilterSelector from '../components/FilterSelector';
import EChartWrapper from '../components/EChartWrapper';
import { brandColors, createBarChartOption, createLineChartOption, createTreeMapOption } from '../utils/chartOptions';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { PARTIDO_LOGOS_FALLBACK } from '../utils/logos';
import DataSourceFooter from '../components/DataSourceFooter';

delete L.Icon.Default.prototype._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: require('leaflet/dist/images/marker-icon-2x.png'),
  iconUrl: require('leaflet/dist/images/marker-icon.png'),
  shadowUrl: require('leaflet/dist/images/marker-shadow.png'),
});

const formatCurrency = (value = 0) => {
  const num = Number(value);
  return (isNaN(num) ? 0 : num).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL', minimumFractionDigits: 2 });
};

const formatNumber = (value = 0) => Number(value || 0).toLocaleString('pt-BR');

const escapeHtml = (value = '') =>
  String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');

// Proxy de imagens: evita bloqueio de hotlink do Wikimedia
const proxyImg = (url) => url ? `/api/proxy/imagem?url=${encodeURIComponent(url)}` : null;

// PARTIDO_LOGOS vêm do arquivo partido.csv, mas nós usamos os hashes Special:FilePath garantidos anti-bloqueios.
const normalizeWikiUrl = (url) => {
  if (!url || typeof url !== 'string') return url;
  if (url.includes('flagcdn.com') || url.includes('Special:FilePath')) return url;
  
  const match = url.match(/wikipedia\/(?:commons|pt)\/(?:thumb\/)?(?:[a-f0-9]\/[a-f0-9]{2}\/)?([^\/]+)(?:\/\d+px-[^\/]+)?$/i);
  if (match && match[1]) {
    return `https://commons.wikimedia.org/wiki/Special:FilePath/${match[1]}?width=150`;
  }
  return url;
};

const getPartidoLogo = (info) => {
  if (!info) return '';
  const partido = (info.sgPartido || info.partido || "").toUpperCase();
  if (info.urlPartido || info.logo_partido) return normalizeWikiUrl(info.urlPartido || info.logo_partido);
  return PARTIDO_LOGOS_FALLBACK[partido] || '';
};

const getEstadoLogo = (info) => {
  if (!info) return '';
  if (info.urlEstado || info.bandeira_estado) return normalizeWikiUrl(info.urlEstado || info.bandeira_estado);
  const uf = (info.sgUF || info.estado || "").toUpperCase();
  
  // Tratamento especial para RN que falha no FlagCDN ou links quebrados
  if (uf === 'RN') return 'https://upload.wikimedia.org/wikipedia/commons/thumb/3/30/Bandeira_do_Rio_Grande_do_Norte.svg/300px-Bandeira_do_Rio_Grande_do_Norte.svg.png';
  
  return uf ? `https://flagcdn.com/w160/br-${uf.toLowerCase()}.png` : '';
};

const handleImgError = (event, info, type) => {
  if (type === 'partido') {
    const partido = (info.sgPartido || info.partido || "").toUpperCase();
    const fallback = PARTIDO_LOGOS_FALLBACK[partido];
    if (fallback && event.target.src !== fallback) {
      event.target.src = fallback;
    } else {
      event.target.style.display = 'none';
    }
  } else {
    event.target.style.display = 'none';
  }
};

const EmendasParlamentares = () => {
  const [filters, setFilters] = useState({
    estado: '',
    partido: '',
    parlamentar: '',
  });

  const [extraFilters, setExtraFilters] = useState({
    tipo_beneficiario: 'Todos',
    cidade: '',
  });
  const [cityInputValue, setCityInputValue] = useState('');

  const [analysisData, setAnalysisData] = useState(null);
  const [availableCities, setAvailableCities] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [llmLoading, setLlmLoading] = useState(false);
  const [llmResult, setLlmResult] = useState(null);
  const [llmStatus, setLlmStatus] = useState('');
  const [llmError, setLlmError] = useState(null);

  // Alertas de integridade — sanções CGU (CEIS/CEPIM) cruzadas com as emendas/contratos do parlamentar
  const [sancoesData, setSancoesData] = useState({ resumo: { total_alertas: 0, total_ceis: 0, total_cepim: 0 }, alertas: [] });
  const [sancoesLoading, setSancoesLoading] = useState(false);
  const [sancoesAviso, setSancoesAviso] = useState(null);

  const carregarAlertasSancoes = async (parlamentar) => {
    if (!parlamentar || parlamentar === 'Todos') {
      setSancoesData({ resumo: { total_alertas: 0, total_ceis: 0, total_cepim: 0 }, alertas: [] });
      return;
    }
    try {
      setSancoesLoading(true);
      const params = new URLSearchParams({ nome: parlamentar });
      const response = await fetch(`${API_BASE_URL}/api/integridade/alertas-sancoes?${params.toString()}`, { headers: API_HEADERS });
      if (!response.ok) throw new Error(`Erro na API: ${response.status}`);
      const result = await response.json();
      setSancoesData(result);
      setSancoesAviso(result.aviso || null);
    } catch (err) {
      console.error('Erro ao buscar alertas de sanções CEIS/CEPIM:', err);
    } finally {
      setSancoesLoading(false);
    }
  };

  const [loadingCities, setLoadingCities] = useState(false);

  const [selectedCity, setSelectedCity] = useState(null);
  const [openModal, setOpenModal] = useState(false);
  const [mapFilters, setMapFilters] = useState({
    Prefeitura: true,
    ONG: true,
    Empresa: true
  });

  const [sankeyFilters, setSankeyFilters] = useState({
    area: 'Todas',
    emenda: 'Todas',
    convenio: 'Todos',
    busca: ''
  });

  const [appliedSankeyFilters, setAppliedSankeyFilters] = useState({
    area: 'Todas',
    emenda: 'Todas',
    convenio: 'Todos',
    busca: ''
  });

  const handleApplySankeyFilters = () => {
    setAppliedSankeyFilters({ ...sankeyFilters });
  };

  // Função utilitária para calcular caminhos válidos dado um conjunto de filtros
  const computeValidSankeyLinks = useCallback((linksArray, filters) => {
    const isFilterActive = filters.area !== 'Todas' || 
                           filters.emenda !== 'Todas' ||
                           filters.convenio !== 'Todos' || 
                           filters.busca !== '';

    if (!isFilterActive) return linksArray;

    const adj = new Map();
    const inDegree = new Map();
    linksArray.forEach(link => {
      if (!adj.has(link.source)) adj.set(link.source, []);
      adj.get(link.source).push(link);
      
      inDegree.set(link.target, (inDegree.get(link.target) || 0) + 1);
      if (!inDegree.has(link.source)) inDegree.set(link.source, 0);
    });

    const roots = [];
    inDegree.forEach((degree, node) => {
      if (degree === 0) roots.push(node);
    });

    const validLinks = new Set();
    const searchTerms = filters.busca ? filters.busca.toLowerCase().split(' ') : [];

    const dfs = (node, currentPath) => {
      const edges = adj.get(node) || [];
      
      if (edges.length === 0) {
        let hasArea = filters.area === 'Todas';
        let hasEmenda = filters.emenda === 'Todas';
        let hasConv = filters.convenio === 'Todos';
        let hasBusca = filters.busca === '';

        const pathNodes = new Set();
        if (currentPath.length > 0) {
           pathNodes.add(currentPath[0].source);
           currentPath.forEach(edge => pathNodes.add(edge.target));
        } else {
           pathNodes.add(node);
        }

        if (!hasArea) {
           pathNodes.forEach(n => {
              if (n.startsWith('Área') && n.includes(filters.area)) hasArea = true;
           });
        }

        if (!hasEmenda) {
           pathNodes.forEach(n => {
              if (n.startsWith('Emenda') && n.includes(filters.emenda)) hasEmenda = true;
           });
        }
        
        if (!hasConv) {
           pathNodes.forEach(n => {
              if (n.startsWith('Convênio') && n.includes(filters.convenio)) hasConv = true;
           });
        }
        
        if (!hasBusca) {
           pathNodes.forEach(n => {
              const lowerN = n.toLowerCase();
              if (searchTerms.every(term => lowerN.includes(term))) hasBusca = true;
           });
        }

        if (hasArea && hasEmenda && hasConv && hasBusca) {
           currentPath.forEach(edge => validLinks.add(edge));
        }
        return;
      }

      edges.forEach(edge => {
        currentPath.push(edge);
        dfs(edge.target, currentPath);
        currentPath.pop();
      });
    };

    roots.forEach(root => dfs(root, []));
    return Array.from(validLinks);
  }, []);

  // Listas extraídas para os filtros do Sankey (Cascading Filters)
  const sankeyOptions = useMemo(() => {
    if (!analysisData?.fluxo_dinheiro) return { areas: ['Todas'], emendas: ['Todas'], convenios: ['Todos'] };
    
    // Para as Áreas, aplicar os outros filtros apenas
    const linksForAreas = computeValidSankeyLinks(analysisData.fluxo_dinheiro, { ...sankeyFilters, area: 'Todas' });
    const areas = new Set(['Todas']);
    linksForAreas.forEach(link => {
      if (link.source.startsWith('Área (Função):')) areas.add(link.source.replace('Área (Função): ', ''));
    });

    // Para as Emendas, aplicar os outros filtros apenas
    const linksForEmendas = computeValidSankeyLinks(analysisData.fluxo_dinheiro, { ...sankeyFilters, emenda: 'Todas' });
    const emendas = new Set(['Todas']);
    linksForEmendas.forEach(link => {
      if (link.source.startsWith('Emenda:')) emendas.add(link.source.replace('Emenda: ', ''));
      if (link.target.startsWith('Emenda:')) emendas.add(link.target.replace('Emenda: ', ''));
    });

    // Para os Convênios, aplicar os outros filtros apenas
    const linksForConvenios = computeValidSankeyLinks(analysisData.fluxo_dinheiro, { ...sankeyFilters, convenio: 'Todos' });
    const convenios = new Set(['Todos']);
    linksForConvenios.forEach(link => {
      if (link.source.startsWith('Convênio:')) convenios.add(link.source.replace('Convênio: ', ''));
      if (link.target.startsWith('Convênio:')) convenios.add(link.target.replace('Convênio: ', ''));
    });
    
    return {
      areas: Array.from(areas).sort(),
      emendas: Array.from(emendas).sort(),
      convenios: Array.from(convenios).sort()
    };
  }, [analysisData, sankeyFilters.convenio, sankeyFilters.emenda, sankeyFilters.area, sankeyFilters.busca, computeValidSankeyLinks]);

  const mapContainerRef = useRef(null);
  const mapInstanceRef = useRef(null);

  // ... (existing handlers)

  const handleFilterChange = (newFilters) => {
    setFilters(newFilters);
  };

  const handleTreeMapClick = (params) => {
    if (params.data) {
      setSelectedCity(params.data);
      setOpenModal(true);
    }
  };

  const handleCloseModal = () => {
    setOpenModal(false);
    setSelectedCity(null);
  };

  // ... (map effect)

  const buildParams = () => {
    const params = {};
    const cidadeValida =
      extraFilters.cidade && availableCities.includes(extraFilters.cidade)
        ? extraFilters.cidade
        : '';

    if (filters.estado && filters.estado !== 'Todos') params.estado = filters.estado;
    if (filters.partido && filters.partido !== 'Todos') params.partido = filters.partido;
    if (filters.parlamentar && filters.parlamentar !== 'Todos') params.parlamentar = filters.parlamentar;
    if (extraFilters.tipo_beneficiario && extraFilters.tipo_beneficiario !== 'Todos') params.tipo_beneficiario = extraFilters.tipo_beneficiario;
    if (cidadeValida) params.cidade = cidadeValida;
    return params;
  };

  const handleAnalyze = async () => {
    if (!filters.parlamentar || filters.parlamentar === 'Todos') {
      setError('Selecione um parlamentar para executar a análise.');
      return;
    }

    setLoading(true);
    setError(null);
    setAnalysisData(null);
    setLlmResult(null);

    try {
      const queryParams = new URLSearchParams(buildParams()).toString();
      const url = `${API_BASE_URL}/api/emendas/analise?${queryParams}`;
      
      console.log('--- EXECUTANDO ANÁLISE DE EMENDAS ---');
      console.log('URL:', url);

      const response = await fetch(url, {
        headers: {
          ...API_HEADERS,
          'Cache-Control': 'no-cache',
        },
      });

      if (!response.ok) {
        throw new Error(`Erro na API: ${response.status}`);
      }

      const data = await response.json();
      console.log('✅ API EMENDAS DATA:', data);
      setAnalysisData(data);
      setLoading(false);
      carregarAlertasSancoes(filters.parlamentar);
    } catch (err) {
      console.error('Erro ao analisar emendas:', err);
      setError('Erro ao carregar dados. Por favor, tente novamente.');
      setAnalysisData(null);
      setLoading(false);
    }
  };

  const handleAnalyzeLLM = async () => {
    if (!filters.parlamentar || filters.parlamentar === 'Todos') {
      setLlmError('Selecione um parlamentar para executar a análise de inteligência.');
      return;
    }

    setLlmLoading(true);
    setLlmError(null);
    setLlmResult(null);
    setLlmStatus('Iniciando análise...');

    try {
      const bodyParams = buildParams();
      const url = `${API_BASE_URL}/api/emendas/analise-llm`;

      const response = await fetch(url, {
        method: 'POST',
        headers: {
          ...API_HEADERS,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(bodyParams),
      });

      if (!response.ok) {
        try {
          const errData = await response.json();
          setLlmError(errData.error || 'Erro na requisição da análise');
        } catch {
          setLlmError(`Erro no servidor: ${response.status}`);
        }
        return;
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n\n');
        buffer = lines.pop();

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const data = JSON.parse(line.slice(6));

            if (data.status) {
              setLlmStatus(data.status);
            } else if (data.analise) {
              setLlmResult(data.analise);
            } else if (data.error) {
              setLlmError(data.error);
            }
          }
        }
      }
    } catch (err) {
      console.error('Erro na análise LLM:', err);
      setLlmError('Não foi possível gerar a análise de inteligência. Tente novamente.');
    } finally {
      setLlmLoading(false);
      setLlmStatus('');
    }
  };

  const infoParlamentar = analysisData?.info_parlamentar || {};
  const resumo = analysisData?.resumo || {};
  const reportTitle = `Relatório de análise de emendas frente ao reduto eleitoral do deputado ${infoParlamentar?.nome || filters.parlamentar || ''}`;

  const handleDownloadPdf = () => {
    try {
      if (!llmResult) return;

      const win = window.open('', '_blank');
      if (!win) return;

      const deputadoNome = infoParlamentar?.nome || filters.parlamentar || 'Deputado não identificado';
      const partidoNome = infoParlamentar?.partido || filters.partido || 'N/D';
      const estadoNome = infoParlamentar?.estado || filters.estado || 'N/D';
      const fotoDeputado = infoParlamentar?.foto || '';
      const logoPartido = getPartidoLogo(infoParlamentar) || '';
      const bandeiraEstado = getEstadoLogo(infoParlamentar) || '';
      const fotoAntunes = '/expressions/antunes_angry.png';

      const relatorioHtml = llmResult
        .split('\n')
        .map((line) => {
          const trimmed = line.trim();
          if (!trimmed) return '<div style="height:10px;"></div>';
          if (trimmed.startsWith('## ')) {
            return `<h2>${escapeHtml(trimmed.replace(/^##\s*/, ''))}</h2>`;
          }
          return `<p>${escapeHtml(trimmed)}</p>`;
        })
        .join('');

      win.document.write(`<!doctype html>
        <html>
          <head>
            <meta charset="utf-8" />
            <title>${escapeHtml(reportTitle)}</title>
            <style>
              body {
                font-family: Arial, sans-serif;
                color: #0f2f57;
                margin: 28px;
                line-height: 1.55;
              }
              .header {
                display: flex;
                justify-content: space-between;
                align-items: flex-start;
                gap: 20px;
                border-bottom: 3px solid #0b8f3d;
                padding-bottom: 18px;
                margin-bottom: 20px;
              }
              .header-left {
                display: flex;
                gap: 16px;
                align-items: center;
                flex: 1;
              }
              .header-right {
                display: flex;
                gap: 12px;
                align-items: center;
              }
              .avatar {
                width: 92px;
                height: 92px;
                border-radius: 50%;
                object-fit: cover;
                border: 3px solid #0b8f3d;
                background: #fff;
              }
              .logo {
                max-height: 56px;
                max-width: 90px;
                object-fit: contain;
              }
              h1 {
                font-size: 26px;
                margin: 0 0 8px 0;
                color: #0f3d73;
              }
              h2 {
                font-size: 18px;
                margin: 24px 0 10px;
                color: #0f3d73;
                border-left: 5px solid #0b8f3d;
                padding-left: 10px;
              }
              p {
                margin: 0 0 12px 0;
                white-space: pre-wrap;
              }
              .meta {
                color: #4b5d73;
                font-size: 13px;
                margin-top: 4px;
              }
              .footer {
                margin-top: 28px;
                padding-top: 12px;
                border-top: 1px solid #cfd8e3;
                font-size: 12px;
                color: #5e6d7e;
              }
            </style>
          </head>
          <body>
            <div class="header">
              <div class="header-left">
                ${fotoDeputado ? `<img class="avatar" src="${escapeHtml(fotoDeputado)}" alt="Foto do parlamentar" />` : ''}
                <div>
                  <h1>${escapeHtml(reportTitle)}</h1>
                  <div class="meta">Parlamentar: ${escapeHtml(deputadoNome)}</div>
                  <div class="meta">Partido: ${escapeHtml(partidoNome)} | Estado: ${escapeHtml(estadoNome)}</div>
                  <div class="meta">Gerado em: ${escapeHtml(new Date().toLocaleString('pt-BR'))}</div>
                </div>
              </div>
              <div class="header-right">
                ${fotoAntunes ? `<img class="avatar" src="${escapeHtml(fotoAntunes)}" alt="Antunes" />` : ''}
                ${logoPartido ? `<img class="logo" src="${escapeHtml(logoPartido)}" alt="Logo do partido" />` : ''}
                ${bandeiraEstado ? `<img class="logo" src="${escapeHtml(bandeiraEstado)}" alt="Bandeira do estado" />` : ''}
              </div>
            </div>
            <div>${relatorioHtml}</div>
            <div class="footer">
              Relatório emitido pelo Robô Antunes com base no recorte filtrado da análise de emendas.
            </div>
          </body>
        </html>`);
      win.document.close();
      win.focus();
      win.print();
    } catch (error) {
      console.error('Erro ao gerar PDF do relatório de emendas:', error);
    }
  };

  const tipoOption = analysisData?.distribuicao_por_tipo?.length
    ? createBarChartOption(
      {
        xAxis: analysisData.distribuicao_por_tipo.map((item) => item.tipo || 'N/A'),
        values: analysisData.distribuicao_por_tipo.map((item) => Number(item.valor || 0)),
        showLabels: true,
        valueFormatter: (value) => formatCurrency(value),
      },
      'Distribuição por Tipo de Emenda',
      'Valor'
    )
    : null;

  const anoOption = analysisData?.distribuicao_por_ano?.length
    ? createLineChartOption({
      xAxis: analysisData.distribuicao_por_ano.map((item) => item.ano),
      series: [
        {
          name: 'Valor Pago',
          data: analysisData.distribuicao_por_ano.map((item) => Number(item.valor || 0)),
        },
      ],
    }, 'Evolução do Valor Pago por Ano')
    : null;

  const temaTreeMapOption = analysisData?.hierarquia_tematica?.length
    ? createTreeMapOption(
      analysisData.hierarquia_tematica,
      'Distribuição por Área e Subtema (Função/Subfunção)'
    )
    : null;

  // Removido useEffect que disparava handleAnalyze automaticamente ao mudar filtros
  // Agora só executa ao clicar no botão, conforme pedido do usuário

  // Limpar filtros extras e recarregar cidades quando o parlamentar mudar
  useEffect(() => {
    setExtraFilters({
      tipo_beneficiario: 'Todos',
      cidade: '',
    });
    setCityInputValue('');

    const loadAvailableCities = async () => {
      if (!filters.parlamentar || filters.parlamentar === 'Todos') {
        setAvailableCities([]);
        return;
      }

      setLoadingCities(true);
      try {
        const params = new URLSearchParams();
        params.set('parlamentar', filters.parlamentar);
        if (filters.estado && filters.estado !== 'Todos') params.set('estado', filters.estado);
        if (filters.partido && filters.partido !== 'Todos') params.set('partido', filters.partido);

        const response = await fetch(`${API_BASE_URL}/api/emendas/analise-basica?${params.toString()}`, {
          headers: {
            ...API_HEADERS,
            'Cache-Control': 'no-cache',
          },
        });

        if (!response.ok) {
          throw new Error(`Erro ao carregar cidades: ${response.status}`);
        }

        const data = await response.json();
        const cidades = Array.isArray(data?.municipios)
          ? [...new Set(
              data.municipios
                .map((item) => item?.municipio)
                .filter(Boolean)
            )].sort()
          : [];

        setAvailableCities(cidades);
      } catch (err) {
        console.error('Erro ao carregar cidades do parlamentar:', err);
        setAvailableCities([]);
      } finally {
        setLoadingCities(false);
      }
    };

    loadAvailableCities();
  }, [filters.parlamentar, filters.estado, filters.partido]);

  useEffect(() => {
    if (extraFilters.cidade && !availableCities.includes(extraFilters.cidade)) {
      setExtraFilters((prev) => ({
        ...prev,
        cidade: '',
      }));
      setCityInputValue('');
    }
  }, [availableCities, extraFilters.cidade]);

  // Map Effect
  useEffect(() => {
    if (!analysisData || !analysisData.municipios || !mapContainerRef.current) return;

    // Limpar mapa anterior se existir
    if (mapInstanceRef.current) {
      mapInstanceRef.current.remove();
      mapInstanceRef.current = null;
    }

    const map = L.map(mapContainerRef.current).setView([-15.7801, -47.9292], 4);
    mapInstanceRef.current = map;

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '&copy; OpenStreetMap contributors'
    }).addTo(map);

    const markers = L.layerGroup();
    const bounds = L.latLngBounds();
    let hasPoints = false;

    // Calcular valor máximo para escala
    const maxValor = Math.max(...analysisData.municipios.map(m => m.valor_total || 0));

    analysisData.municipios.forEach(mun => {
      if (mun.latitude && mun.longitude) {
        const tipo = mun.tipo_beneficiario || 'Outros';

        // Ícone Dinâmico (Bolinhas Proporcionais)
        const valor = mun.valor_total || 0;
        // Escala para o raio (pixels)
        const radius = 8 + (Math.sqrt(valor) / Math.sqrt(maxValor)) * 22;

        // COR dinâmica por tipo de beneficiário
        let color = '#009739'; // Verde padrão (Cidades/Prefeitura)
        if (tipo === 'Empresa') color = '#FFD700'; // Amarelo
        if (tipo === 'ONG') color = '#007bff';     // Azul

        const marker = L.circleMarker([mun.latitude, mun.longitude], {
          radius: radius,
          fillColor: color,
          color: '#FFFFFF', // Borda branca
          weight: 2,
          opacity: 1,
          fillOpacity: 0.8
        });

        marker.bindPopup(`
          <div class="p-2">
            <h3 class="font-bold text-lg">${mun.municipio}</h3>
            <p class="text-sm text-gray-600">${mun.beneficiario || 'Beneficiário não informado'}</p>
            <p class="text-sm font-semibold mt-1">Tipo: ${tipo}</p>
            <p class="font-mono text-blue-600 mt-1">${formatCurrency(mun.valor_total)}</p>
            ${mun.qtde_pagamentos ? `<p class="text-xs text-gray-600 mt-1">📑 ${mun.qtde_pagamentos} pagamentos</p>` : ''}
            ${mun.votos_recebidos ? `<p class="text-xs text-gray-500 mt-1">🗳️ ${mun.votos_recebidos} votos</p>` : ''}
          </div>
        `);
        markers.addLayer(marker);
        bounds.extend([mun.latitude, mun.longitude]);
        hasPoints = true;
      }
    });

    map.addLayer(markers);

    if (hasPoints) {
      map.fitBounds(bounds, { padding: [50, 50], maxZoom: 10 });
    }

  }, [analysisData, mapFilters]);

  // Opção para o TreeMap de Cidades (Agregado por Cidade)
  const cityTreeMapOption = (() => {
    if (!analysisData?.municipios?.length) return null;

    // Agrupar por nome do município para evitar duplicatas visuais
    const groupedCities = {};

    analysisData.municipios.forEach(mun => {
      const name = mun.municipio;
      if (!groupedCities[name]) {
        groupedCities[name] = {
          name: name,
          value: 0,
          details: {
            prefeitura: 0,
            ong: 0,
            empresa: 0,
            valor_prefeitura: 0,
            valor_ong: 0,
            valor_empresa: 0,
            convenios: []
          }
        };
      }

      const city = groupedCities[name];
      city.value += (mun.valor_total || 0);

      const val = mun.valor_total || 0;
      city.details.valor_prefeitura += (val * (mun.percentual_prefeitura || 0) / 100);
      city.details.valor_ong += (val * (mun.percentual_ong || 0) / 100);
      city.details.valor_empresa += (val * (mun.percentual_empresa || 0) / 100);

      if (mun.convenios && Array.isArray(mun.convenios)) {
        city.details.convenios.push(...mun.convenios);
      }
    });

    // Converter detalhe de valores de volta para percentuais médios (ponderados)
    const chartData = Object.values(groupedCities).map(city => ({
      name: city.name,
      value: city.value,
      details: {
        prefeitura: (city.details.valor_prefeitura / city.value) * 100,
        ong: (city.details.valor_ong / city.value) * 100,
        empresa: (city.details.valor_empresa / city.value) * 100,
        convenios: [...new Set(city.details.convenios)] // Deduplicar convênios
      },
      itemStyle: {
        color: '#003366' // Azul padrão da marca
      }
    })).sort((a, b) => b.value - a.value);

    return {
      tooltip: {
        formatter: (info) => {
          const value = info.value;
          return [
            '<div class="tooltip-title" style="font-weight:bold">' + info.name + '</div>',
            'Total: ' + formatCurrency(value)
          ].join('');
        }
      },
      series: [
        {
          type: 'treemap',
          visibleMin: 300,
          label: {
            show: true,
            formatter: '{b}',
            fontSize: 14,
            fontWeight: 'bold',
            color: '#FFFFFF'
          },
          itemStyle: {
            borderColor: '#fff',
            borderWidth: 1
          },
          levels: [
            {
              itemStyle: {
                normal: {
                  borderColor: '#FFFFFF',
                  borderWidth: 2,
                  gapWidth: 2
                }
              }
            }
          ],
          data: chartData
        }
      ]
    };
  })();

  // Fluxo do Dinheiro (Sankey Relacional)
  const moneyFlowOption = useMemo(() => {
    if (!analysisData?.fluxo_dinheiro?.length) return null;

    const nodesMap = new Map();
    const links = [];

    const filteredLinks = computeValidSankeyLinks(analysisData.fluxo_dinheiro, appliedSankeyFilters);

    if (filteredLinks.length === 0) return null;

    filteredLinks.forEach(link => {
      // Adicionar Nodes
      [link.source, link.target].forEach(name => {
        if (!nodesMap.has(name)) {
          let color = brandColors.azul;
          if (name.startsWith('Deputado:')) color = brandColors.azul;
          if (name.startsWith('Área (Função):')) color = brandColors.azulClaro;
          if (name.startsWith('Emenda:')) color = brandColors.verde;
          if (name.startsWith('Convênio:')) color = brandColors.verdeClaro;
          if (name.startsWith('Beneficiário')) color = brandColors.laranjaEscuro;
          if (name.startsWith('Sócio')) color = brandColors.laranjaClaro;

          nodesMap.set(name, {
            name,
            itemStyle: { color }
          });
        }
      });

      // Adicionar Link
      links.push({
        source: link.source,
        target: link.target,
        value: link.value
      });
    });

    const totalNodes = nodesMap.size;
    let dynamicFontSize = 9;
    if (totalNodes < 15) dynamicFontSize = 14;
    else if (totalNodes < 30) dynamicFontSize = 12;
    else if (totalNodes < 60) dynamicFontSize = 10;

    return {
      title: {
        text: 'Fluxo Forense Detalhado (Rastro do Orçamento)',
        left: 'center',
        textStyle: { color: brandColors.azul, fontSize: 16, fontWeight: 'bold' }
      },
      tooltip: {
        trigger: 'item',
        backgroundColor: 'rgba(255, 255, 255, 0.95)',
        borderColor: '#e2e8f0',
        borderWidth: 1,
        padding: 0,
        textStyle: { color: brandColors.azul },
        shadowBlur: 20,
        shadowColor: 'rgba(0, 0, 0, 0.1)',
        formatter: (params) => {
          if (params.dataType === 'node') {
            const valFormated = params.value ? formatCurrency(params.value) : 'Consolidação de Rota';
            // Box grandão para o valor do Node
            return `
              <div style="padding: 16px; min-width: 280px; max-width: 350px;">
                <div style="font-size: 11px; color: #64748b; margin-bottom: 8px; font-weight: bold; letter-spacing: 0.5px;">
                  MÓDULO DE RASTREAMENTO FORENSE
                </div>
                <div style="font-size: 13px; font-weight: bold; color: ${brandColors.azul}; margin-bottom: 16px; white-space: normal; line-height: 1.5; border-left: 3px solid ${brandColors.verde}; padding-left: 8px;">
                  ${params.name}
                </div>
                <div style="background: linear-gradient(135deg, ${brandColors.verde} 0%, #007a2d 100%); padding: 20px 16px; border-radius: 12px; text-align: center; box-shadow: 0 4px 16px rgba(0,151,57,0.2);">
                  <div style="font-size: 12px; color: rgba(255,255,255,0.9); margin-bottom: 6px; font-weight: 500; text-transform: uppercase; letter-spacing: 1px;">
                    Volume Identificado no Nó
                  </div>
                  <div style="font-size: 26px; font-weight: 900; color: #ffffff; text-shadow: 0 2px 4px rgba(0,0,0,0.2);">
                    ${valFormated}
                  </div>
                </div>
              </div>
            `;
          }
          
          // Box para o Link
          return `
            <div style="padding: 16px; min-width: 250px; max-width: 350px;">
              <div style="font-size: 11px; color: #64748b; margin-bottom: 8px; font-weight: bold; letter-spacing: 0.5px;">
                CADEIA DE REPASSE (LINK)
              </div>
              <div style="font-size: 13px; color: ${brandColors.azul}; line-height: 1.5; margin-bottom: 12px; white-space: normal;">
                <strong style="color: #334155;">Origem:</strong> ${params.data.source}
                <div style="margin: 8px 0; text-align: center; color: ${brandColors.verde};">
                   <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"></line><polyline points="19 12 12 19 5 12"></polyline></svg>
                </div>
                <strong style="color: #334155;">Destino:</strong> ${params.data.target}
              </div>
              <div style="background: #e8f5e9; border: 1px solid #c8e6c9; border-radius: 8px; padding: 12px; text-align: center;">
                <div style="font-size: 11px; color: #2e7d32; margin-bottom: 4px; font-weight: bold; text-transform: uppercase;">Valor do Repasse</div>
                <div style="font-size: 20px; font-weight: 900; color: ${brandColors.verde};">
                  ${formatCurrency(params.data.value)}
                </div>
              </div>
            </div>
          `;
        }
      },
      series: [{
        type: 'sankey',
        layout: 'none',
        emphasis: { focus: 'adjacency' },
        nodeAlign: 'justify',
        nodeWidth: 15,
        nodeGap: 8,
        draggable: true,
        data: Array.from(nodesMap.values()),
        links: links,
        lineStyle: { color: 'gradient', curveness: 0.5, opacity: 0.3 },
        label: {
          position: 'right',
          fontSize: dynamicFontSize,
          color: brandColors.azul,
          fontWeight: 500,
          formatter: (p) => {
            const name = p.name;
            const val = p.value;
            const formattedVal = val >= 1000000 
              ? `R$ ${(val/1000000).toFixed(1)}M` 
              : val >= 1000 
                ? `R$ ${(val/1000).toFixed(0)}k`
                : formatCurrency(val);
            
            const displayName = name.length > 25 ? name.substring(0, 25) + '...' : name;
            return `${displayName} (${formattedVal})`;
          }
        }
      }]
    };
  }, [analysisData, appliedSankeyFilters, brandColors]);

  return (
    <Box sx={{ backgroundColor: '#F5F7FB', minHeight: '100vh', py: 3 }}>
      <Container maxWidth="xl">
        <Box sx={{ mb: 4, backgroundColor: 'white', p: 3, borderRadius: '16px', display: 'flex', alignItems: 'center', gap: 4 }}>
          <Box sx={{ flex: 1 }}>
            <Typography variant="h3" sx={{ color: brandColors.azul, mb: 1, fontWeight: 'bold' }}>
              💼 Emendas Parlamentares
            </Typography>
            <Typography variant="body1" sx={{ color: brandColors.cinza }}>
              Explore como cada parlamentar direciona recursos de emendas e quais municípios recebem investimentos prioritários.
            </Typography>
          </Box>
          <Box
            component="img"
            src="/Emendas_Parlamentares.png"
            alt="Ilustração Emendas Parlamentares"
            sx={{
              maxHeight: '220px',
              width: 'auto',
              borderRadius: '8px',
              display: { xs: 'none', md: 'block' }
            }}
          />
        </Box>

        <Alert
          severity="info"
          sx={{
            mb: 2.5,
            borderRadius: '12px',
            alignItems: 'center'
          }}
        >
          Nesta tela, exibimos apenas <strong>parlamentares com emendas registradas</strong> na base, e a lista de cidades é carregada a partir dessas emendas.
        </Alert>

        <FilterSelector
          onFiltersChange={handleFilterChange}
          fields={['estado', 'partido', 'parlamentar']}
          useCurrentParty={true}
          sourceType="emendas"
          requireSelection={true}
        requireAll={true}
        />

        <Grid container spacing={2.5} sx={{ mt: 2.5, mb: 1.5, alignItems: 'flex-end' }}>
          <Grid item xs={12} md={4}>
            <FormControl fullWidth variant="outlined" size="small">
              <InputLabel>Tipo de Beneficiário</InputLabel>
              <Select
                value={extraFilters.tipo_beneficiario}
                label="Tipo de Beneficiário"
                onChange={(e) => setExtraFilters({ ...extraFilters, tipo_beneficiario: e.target.value })}
                sx={{ backgroundColor: '#FFFFFF', borderRadius: '8px' }}
              >
                <MenuItem value="Todos">Todos os Tipos</MenuItem>
                <MenuItem value="Prefeitura">Prefeituras / Cidades</MenuItem>
                <MenuItem value="ONG">ONGs / Associações</MenuItem>
                <MenuItem value="Empresa">Empresas</MenuItem>
              </Select>
            </FormControl>
          </Grid>
          <Grid item xs={12} md={8}>
            <Autocomplete
              fullWidth
              size="small"
              options={availableCities}
              value={extraFilters.cidade || null}
              inputValue={cityInputValue}
              loading={loadingCities}
              loadingText="Carregando..."
              onChange={(event, newValue) => {
                setExtraFilters((prev) => ({ ...prev, cidade: newValue || '' }));
                setCityInputValue(newValue || '');
              }}
              onInputChange={(event, newInputValue, reason) => {
                setCityInputValue(newInputValue || '');
                if (reason === 'clear' || newInputValue === '') {
                  setExtraFilters((prev) => ({ ...prev, cidade: '' }));
                }
              }}
              renderInput={(params) => (
                <TextField
                  {...params}
                  label="Filtrar por Cidade"
                  placeholder="Selecione uma cidade..."
                  sx={{ backgroundColor: '#FFFFFF', borderRadius: '8px' }}
                />
              )}
            />
          </Grid>
        </Grid>

        <Box
          sx={{
            mt: 3,
            mb: 4,
            display: 'flex',
            gap: 2.5,
            flexWrap: 'wrap',
            alignItems: 'stretch'
          }}
        >
          <Button
            variant="contained"
            onClick={handleAnalyze}
            disabled={loading || llmLoading || (filters.estado === 'Todos' && filters.partido === 'Todos' && filters.parlamentar === 'Todos')}
            sx={{
              backgroundColor: brandColors.verde,
              borderRadius: '12px',
              px: 4,
              py: 1.5,
              fontSize: '1.05rem',
              fontWeight: 'bold',
              minHeight: 58,
            }}
          >
            {loading ? <CircularProgress size={24} color="inherit" /> : '📊 Executar Análise de Emendas'}
          </Button>
        </Box>

        {error && (
          <Alert severity="error" sx={{ mb: 3, borderRadius: '12px' }}>
            {error}
          </Alert>
        )}

        {loading && (
          <Box sx={{ display: 'flex', justifyContent: 'center', my: 8 }}>
            <CircularProgress size={60} thickness={4} sx={{ color: brandColors.verde }} />
          </Box>
        )}

        {analysisData && !loading && (
          <>
            <Paper sx={{ p: 4, borderRadius: '16px', mb: 4 }}>
              <Grid container spacing={3} alignItems="center">
                <Grid item xs={12} md={3} textAlign="center">
                  {infoParlamentar?.foto ? (
                    <Avatar
                      src={infoParlamentar.foto}
                      alt={infoParlamentar.nome}
                      sx={{ width: 160, height: 160, mx: 'auto', border: `5px solid ${brandColors.verde}` }}
                    />
                  ) : (
                    <Avatar
                      sx={{
                        width: 160,
                        height: 160,
                        mx: 'auto',
                        fontSize: '3rem',
                        backgroundColor: brandColors.verde,
                      }}
                    >
                      {infoParlamentar?.nome?.[0] || '?'}
                    </Avatar>
                  )}
                </Grid>
                <Grid item xs={12} md={6}>
                  <Typography variant="h4" sx={{ fontWeight: 'bold', color: brandColors.azul, mb: 1 }}>
                    {infoParlamentar?.nome || filters.parlamentar}
                  </Typography>
                  <Stack direction="row" spacing={1}>
                    <Stack direction="row" spacing={1} alignItems="center">
                      <Typography variant="body2" sx={{ color: brandColors.cinza, fontWeight: 'bold' }}>
                        {infoParlamentar?.partido || filters.partido}
                      </Typography>
                      <Divider orientation="vertical" flexItem sx={{ mx: 0.5, height: 15, alignSelf: 'center' }} />
                      <Typography variant="body2" sx={{ color: brandColors.cinza, fontWeight: 'bold' }}>
                        {infoParlamentar?.estado || filters.estado}
                      </Typography>
                    </Stack>
                  </Stack>
                </Grid>
                <Grid item xs={12} md={3}>
                  <Stack direction="column" spacing={2} alignItems="flex-end">
                    <Tooltip title={infoParlamentar?.partido || filters.partido || ''}>
                      <Box
                        component="img"
                        src={getPartidoLogo(infoParlamentar)}
                        onError={(e) => handleImgError(e, infoParlamentar, 'partido')}
                        alt="Logo partido"
                        sx={{ maxHeight: 60, maxWidth: 100, objectFit: 'contain' }}
                      />
                    </Tooltip>
                    <Tooltip title={infoParlamentar?.estado || filters.estado || ''}>
                      <Box
                        component="img"
                        src={getEstadoLogo(infoParlamentar)}
                        onError={(e) => handleImgError(e, infoParlamentar, 'estado')}
                        alt="Bandeira estado"
                        sx={{ maxHeight: 40, maxWidth: 60, objectFit: 'contain', boxShadow: '0 2px 4px rgba(0,0,0,0.1)', borderRadius: '4px' }}
                      />
                    </Tooltip>
                  </Stack>
                </Grid>
              </Grid>
            </Paper>


            <Grid container spacing={3} sx={{ mb: 4 }}>
              <Grid item xs={12} sm={6} md={3}>
                <Card sx={{ borderRadius: '16px', backgroundColor: '#FFFFFF' }}>
                  <CardContent>
                    <Stack direction="row" spacing={2} alignItems="center">
                      <Assessment sx={{ fontSize: 42, color: brandColors.verde }} />
                      <Box>
                        <Typography variant="subtitle2" sx={{ color: brandColors.cinza }}>
                          Total de Emendas
                        </Typography>
                        <Typography variant="h5" sx={{ fontWeight: 'bold', color: brandColors.azul }}>
                          {formatNumber(resumo.total_emendas || 0)}
                        </Typography>
                      </Box>
                    </Stack>
                  </CardContent>
                </Card>
              </Grid>
              <Grid item xs={12} sm={6} md={3}>
                <Card sx={{ borderRadius: '16px', backgroundColor: '#FFFFFF' }}>
                  <CardContent>
                    <Stack direction="row" spacing={2} alignItems="center">
                      <LocalOffer sx={{ fontSize: 42, color: brandColors.azulClaro }} />
                      <Box>
                        <Typography variant="subtitle2" sx={{ color: brandColors.cinza }}>
                          Valor Pago
                        </Typography>
                        <Typography variant="h5" sx={{ fontWeight: 'bold', color: brandColors.azul }}>
                          {formatCurrency(extraFilters.cidade ? (resumo.valor_total_pago_cidade || 0) : (resumo.valor_total_pago || 0))}
                        </Typography>
                      </Box>
                    </Stack>
                  </CardContent>
                </Card>
              </Grid>
              <Grid item xs={12} sm={6} md={3}>
                <Card sx={{ borderRadius: '16px', backgroundColor: '#FFFFFF' }}>
                  <CardContent>
                    <Stack direction="row" spacing={2} alignItems="center">
                      <Assignment sx={{ fontSize: 42, color: brandColors.laranjaEscuro }} />
                      <Box>
                        <Typography variant="subtitle2" sx={{ color: brandColors.cinza }}>
                          Valor Empenhado (Pedidos)
                        </Typography>
                        <Typography variant="h5" sx={{ fontWeight: 'bold', color: brandColors.azul }}>
                          {formatCurrency(extraFilters.cidade ? (resumo.valor_total_empenhado_cidade || 0) : (resumo.valor_total_empenhado || 0))}
                        </Typography>
                      </Box>
                    </Stack>
                  </CardContent>
                </Card>
              </Grid>
              <Grid item xs={12} sm={6} md={3}>
                <Card sx={{ borderRadius: '16px', backgroundColor: '#FFFFFF' }}>
                  <CardContent>
                    <Stack direction="row" spacing={2} alignItems="center">
                      <MapIcon sx={{ fontSize: 42, color: brandColors.verdeClaro }} />
                      <Box>
                        <Typography variant="subtitle2" sx={{ color: brandColors.cinza }}>
                          Cidades Atendidas
                        </Typography>
                        <Typography variant="h5" sx={{ fontWeight: 'bold', color: brandColors.azul }}>
                          {formatNumber(resumo.total_cidades || 0)}
                        </Typography>
                      </Box>
                    </Stack>
                  </CardContent>
                </Card>
              </Grid>
            </Grid>

            {/* Explicação sobre os dados do mapa */}
            <Alert severity="info" sx={{ mb: 4, borderRadius: '12px', backgroundColor: '#e3f2fd', color: '#0d47a1', '& .MuiAlert-icon': { color: '#1976d2' } }}>
              <Typography variant="body2">
                <strong>Nota sobre os dados:</strong> O mapa e a contagem de cidades exibem o <strong>destino efetivo</strong> dos recursos (Prefeituras, ONGs, Empresas), identificados via CNPJ. Quando a cidade é filtrada, a análise mostra apenas a parcela associada ao município selecionado.
              </Typography>
            </Alert>



            {resumo?.data_atualizacao && (
              <Typography variant="caption" sx={{ color: brandColors.cinza, display: 'block', mt: 1.5 }}>
                Dados coletados em {resumo.data_atualizacao}
              </Typography>
            )}

            <Grid container spacing={3} sx={{ mb: 4 }}>
              {temaTreeMapOption && (
                <Grid item xs={12}>
                  <Paper sx={{ p: 4, borderRadius: '24px', minHeight: '500px', boxShadow: '0 4px 20px rgba(0,0,0,0.05)' }}>
                    <Typography variant="h6" sx={{ fontWeight: 'bold', color: brandColors.azul, mb: 3 }}>
                      🧩 Distribuição por Área e Subtema (Função/Subfunção)
                    </Typography>
                    <EChartWrapper option={temaTreeMapOption} height="420px" />
                  </Paper>
                </Grid>
              )}
              {tipoOption && (
                <Grid item xs={12} md={6}>
                  <Paper sx={{ p: 4, borderRadius: '24px', height: '100%', boxShadow: '0 4px 20px rgba(0,0,0,0.05)' }}>
                    <Typography variant="h6" sx={{ fontWeight: 'bold', color: brandColors.azul, mb: 3, textAlign: 'center' }}>
                      Distribuição por Tipo de Emenda
                    </Typography>
                    <EChartWrapper option={tipoOption} height="380px" />
                  </Paper>
                </Grid>
              )}
              {anoOption && (
                <Grid item xs={12} md={6}>
                  <Paper sx={{ p: 4, borderRadius: '24px', height: '100%', boxShadow: '0 4px 20px rgba(0,0,0,0.05)' }}>
                    <Typography variant="h6" sx={{ fontWeight: 'bold', color: brandColors.azul, mb: 3, textAlign: 'center' }}>
                      Evolução do Valor Pago por Ano
                    </Typography>
                    <EChartWrapper option={anoOption} height="380px" />
                  </Paper>
                </Grid>
              )}
            </Grid>

            <Paper sx={{ p: 3, borderRadius: '16px', mb: 4 }}>
              <Typography variant="h6" sx={{ fontWeight: 'bold', color: brandColors.azul, mb: 2 }}>
                📍 Municípios beneficiados por emendas
              </Typography>
              <Typography variant="body2" sx={{ color: brandColors.cinza, mb: 2 }}>
                Cruzamos os fornecedores das emendas com os dados de geocodificação e votação para indicar possíveis redutos eleitorais.
              </Typography>
              <Box
                sx={{
                  width: '100%',
                  height: 420,
                  borderRadius: '12px',
                  overflow: 'hidden',
                  mb: 1,
                  border: `1px solid ${brandColors.cinzaClaro}`,
                  position: 'relative'
                }}
              >
                <Box ref={mapContainerRef} sx={{ width: '100%', height: '100%' }} />
              </Box>

              <Stack direction="row" spacing={3} justifyContent="center" sx={{ mb: 1, flexWrap: 'wrap' }}>
                <Stack direction="row" spacing={1} alignItems="center">
                  <Box sx={{ width: 12, height: 12, borderRadius: '50%', backgroundColor: '#009739' }} />
                  <Typography variant="caption" sx={{ fontWeight: 'bold', color: brandColors.cinza }}>Prefeituras / Cidades</Typography>
                </Stack>
                <Stack direction="row" spacing={1} alignItems="center">
                  <Box sx={{ width: 12, height: 12, borderRadius: '50%', backgroundColor: '#FFD700' }} />
                  <Typography variant="caption" sx={{ fontWeight: 'bold', color: brandColors.cinza }}>Empresas</Typography>
                </Stack>
                <Stack direction="row" spacing={1} alignItems="center">
                  <Box sx={{ width: 12, height: 12, borderRadius: '50%', backgroundColor: '#007bff' }} />
                  <Typography variant="caption" sx={{ fontWeight: 'bold', color: brandColors.cinza }}>ONGs / Associações</Typography>
                </Stack>
              </Stack>

              <Typography variant="caption" display="block" textAlign="center" sx={{ color: brandColors.cinza, fontStyle: 'italic', mb: 3 }}>
                * O tamanho do círculo é proporcional ao volume de recursos destinados.
              </Typography>

              {/* Substituição da Tabela por TreeMap */}
              {cityTreeMapOption && (
                <Box sx={{ mt: 4, height: 600 }}>
                  <Typography variant="h6" sx={{ fontWeight: 'bold', color: brandColors.azul, mb: 2 }}>
                    🧩 Distribuição Detalhada por Cidade e Beneficiário
                  </Typography>
                  <EChartWrapper option={cityTreeMapOption} height="100%" />
                </Box>
              )}
            </Paper>

            {/* Novo: Fluxo do Dinheiro - Sankey Relacional */}
            {analysisData?.fluxo_dinheiro?.length > 0 && (
              <Box sx={{ mt: 4 }}>
                <Paper sx={{ p: 3, mb: 3, borderRadius: '16px', border: `1px solid ${brandColors.azulClaro}40` }}>
                  <Typography variant="h6" sx={{ color: brandColors.azul, fontWeight: 'bold', mb: 2, display: 'flex', alignItems: 'center', gap: 1 }}>
                    🔍 Filtros de Análise Forense (Siga o Dinheiro)
                  </Typography>
                  <Grid container spacing={2} alignItems="center">
                    <Grid item xs={12} md={3}>
                      <Autocomplete
                        options={sankeyOptions.areas}
                        value={sankeyFilters.area}
                        onChange={(e, val) => setSankeyFilters({ ...sankeyFilters, area: val || 'Todas', emenda: 'Todas', convenio: 'Todos' })}
                        renderInput={(params) => <TextField {...params} label="Escolher Tipo de Verba" size="small" />}
                      />
                    </Grid>
                    <Grid item xs={12} md={2}>
                      <Autocomplete
                        options={sankeyOptions.emendas}
                        value={sankeyFilters.emenda}
                        onChange={(e, val) => setSankeyFilters({ ...sankeyFilters, emenda: val || 'Todas', convenio: 'Todos' })}
                        renderInput={(params) => <TextField {...params} label="Emenda" size="small" />}
                      />
                    </Grid>
                    <Grid item xs={12} md={2}>
                      <Autocomplete
                        options={sankeyOptions.convenios}
                        value={sankeyFilters.convenio}
                        onChange={(e, val) => setSankeyFilters({ ...sankeyFilters, convenio: val || 'Todos' })}
                        renderInput={(params) => <TextField {...params} label="Convênio" size="small" />}
                      />
                    </Grid>
                    <Grid item xs={12} md={3}>
                      <TextField
                        fullWidth
                        size="small"
                        label="Buscar Empresa ou CNPJ"
                        placeholder="Nome ou CNPJ..."
                        value={sankeyFilters.busca}
                        onChange={(e) => setSankeyFilters({ ...sankeyFilters, busca: e.target.value })}
                        InputProps={{
                          startAdornment: (
                            <InputAdornment position="start">
                              <Search sx={{ color: brandColors.azul }} />
                            </InputAdornment>
                          ),
                        }}
                      />
                    </Grid>
                    <Grid item xs={12} md={2}>
                      <Button
                        fullWidth
                        variant="contained"
                        onClick={handleApplySankeyFilters}
                        startIcon={<Search />}
                        sx={{ 
                          bgcolor: brandColors.verde, 
                          '&:hover': { bgcolor: '#007a2d' },
                          fontWeight: 'bold',
                          height: '40px'
                        }}
                      >
                        Aplicar
                      </Button>
                    </Grid>
                  </Grid>
                </Paper>

                {moneyFlowOption ? (
                  <Paper sx={{ p: 4, borderRadius: '24px', mb: 4, boxShadow: '0 8px 32px rgba(0,0,0,0.08)' }}>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, mb: 3 }}>
                      <AttachMoneyIcon sx={{ fontSize: 32, color: brandColors.verde }} />
                      <Box>
                        <Typography variant="h5" sx={{ fontWeight: 'bold', color: brandColors.azul }}>
                          Rastro Forense: Origem e Destinação (6 Níveis)
                        </Typography>
                        <Typography variant="body2" sx={{ color: brandColors.cinza }}>
                          Rastreabilidade ponta a ponta: Deputado ➔ Emenda ➔ Convênio ➔ Documento ➔ Empresa ➔ Sócio
                        </Typography>
                      </Box>
                    </Box>
                    <Box sx={{ height: 750, width: '100%', mt: 2 }}>
                       <EChartWrapper option={moneyFlowOption} height="100%" />
                    </Box>
                  </Paper>
                ) : (
                  <Alert severity="info" sx={{ borderRadius: '16px', mb: 4 }}>
                    Nenhum elo do fluxo financeiro corresponde aos filtros selecionados. Tente diminuir o valor mínimo ou limpar a busca.
                  </Alert>
                )}
              </Box>
            )}

            <Grid container spacing={3} sx={{ mb: 4 }}>
              <Grid item xs={12} md={6}>
                <Paper sx={{ p: 3, borderRadius: '16px', height: '100%' }}>
                  <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 2 }}>
                    <Groups color="primary" />
                    <Typography variant="h6" sx={{ color: brandColors.azul, fontWeight: 'bold' }}>
                      Principais beneficiários
                    </Typography>
                  </Stack>
                  <Table size="small">
                    <TableHead>
                      <TableRow>
                        <TableCell sx={{ fontWeight: 'bold', color: brandColors.azul }}>Fornecedor</TableCell>
                        <TableCell sx={{ fontWeight: 'bold', color: brandColors.azul }}>Cidade/UF</TableCell>
                        <TableCell sx={{ fontWeight: 'bold', color: brandColors.azul }} align="right">
                          Valor
                        </TableCell>
                        <TableCell sx={{ fontWeight: 'bold', color: brandColors.azul }} align="right">
                          %
                        </TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {analysisData?.fornecedores?.slice(0, 10).map((forn) => (
                        <TableRow key={`${forn.fornecedor}-${forn.cnpj}`}>
                          <TableCell>
                            <Tooltip title={`CNPJ: ${forn.cnpj || 'N/A'}`}>
                              <span>{forn.fornecedor}</span>
                            </Tooltip>
                          </TableCell>
                          <TableCell>{[forn.cidade, forn.estado].filter(Boolean).join('/') || 'N/A'}</TableCell>
                          <TableCell align="right">{formatCurrency(forn.valor_total)}</TableCell>
                          <TableCell align="right">{`${(forn.percentual || 0).toFixed(2)}%`}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </Paper>
              </Grid>

              <Grid item xs={12} md={6}>
                <Paper sx={{ p: 3, borderRadius: '16px', height: '100%' }}>
                  <Typography variant="h6" sx={{ color: brandColors.azul, fontWeight: 'bold', mb: 2 }}>
                    Convênios relacionados às emendas
                  </Typography>
                  <Table size="small">
                    <TableHead>
                      <TableRow>
                        <TableCell sx={{ fontWeight: 'bold', color: brandColors.azul }}>Emenda</TableCell>
                        <TableCell sx={{ fontWeight: 'bold', color: brandColors.azul }}>Convênio</TableCell>
                        <TableCell sx={{ fontWeight: 'bold', color: brandColors.azul }}>Objeto</TableCell>
                        <TableCell sx={{ fontWeight: 'bold', color: brandColors.azul }}>Cidade</TableCell>
                        <TableCell sx={{ fontWeight: 'bold', color: brandColors.azul }} align="right">
                          Valor
                        </TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {analysisData?.convenios?.length ? (
                        analysisData.convenios.slice(0, 10).map((conv) => (
                          <TableRow key={`${conv.codigo_emenda}-${conv.numero}`}>
                            <TableCell>
                              <Typography variant="body2" sx={{ fontWeight: 'bold', color: brandColors.azul }}>
                                {conv.codigo_emenda}
                              </Typography>
                            </TableCell>
                            <TableCell>
                              <Typography variant="body2">
                                {conv.numero || 'N/A'}
                              </Typography>
                            </TableCell>
                            <TableCell>{conv.objeto || 'N/A'}</TableCell>
                            <TableCell>{conv.cidade || 'N/A'}</TableCell>
                            <TableCell align="right">{formatCurrency(conv.valor)}</TableCell>
                          </TableRow>
                        ))
                      ) : (
                        <TableRow>
                          <TableCell colSpan={5} align="center" sx={{ py: 6, color: brandColors.cinza }}>
                            Nenhum convênio encontrado para o recorte filtrado.
                          </TableCell>
                        </TableRow>
                      )}
                    </TableBody>
                  </Table>
                </Paper>
              </Grid>
            </Grid>

            <Paper sx={{ p: 3, borderRadius: '16px', mb: 6 }}>
              <Typography variant="h6" sx={{ color: brandColors.azul, fontWeight: 'bold', mb: 2 }}>
                Documentos associados às emendas (top 50 maiores valores)
              </Typography>
              <TableContainer sx={{ maxHeight: 420 }}>
                <Table stickyHeader size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell sx={{ fontWeight: 'bold', color: brandColors.azul }}>Emenda</TableCell>
                      <TableCell sx={{ fontWeight: 'bold', color: brandColors.azul }}>Documento</TableCell>
                      <TableCell sx={{ fontWeight: 'bold', color: brandColors.azul }}>Fornecedor</TableCell>
                      <TableCell sx={{ fontWeight: 'bold', color: brandColors.azul }}>Município</TableCell>
                      <TableCell sx={{ fontWeight: 'bold', color: brandColors.azul }}>Data</TableCell>
                      <TableCell sx={{ fontWeight: 'bold', color: brandColors.azul }} align="right">
                        Valor
                      </TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {analysisData?.documentos?.length ? (
                      analysisData.documentos.slice(0, 50).map((doc) => (
                        <TableRow key={`${doc.codigo_emenda}-${doc.numero}`}>
                          <TableCell>
                            <Typography variant="body2" sx={{ fontWeight: 'bold', color: brandColors.azul }}>
                              {doc.codigo_emenda}
                            </Typography>
                          </TableCell>
                          <TableCell>
                            <Typography variant="body2">
                              {doc.numero || doc.fase || 'N/A'}
                            </Typography>
                          </TableCell>
                          <TableCell>{doc.fornecedor || 'N/A'}</TableCell>
                          <TableCell>{[doc.cidade, doc.estado].filter(Boolean).join('/') || 'N/A'}</TableCell>
                          <TableCell>{doc.data || 'N/A'}</TableCell>
                          <TableCell align="right">{formatCurrency(doc.valor)}</TableCell>
                        </TableRow>
                      ))
                    ) : (
                      <TableRow>
                        <TableCell colSpan={6} align="center" sx={{ py: 6, color: brandColors.cinza }}>
                          Nenhum documento encontrado para o recorte filtrado.
                        </TableCell>
                      </TableRow>
                    )}
                  </TableBody>
                </Table>
              </TableContainer>
            </Paper>

            {analysisData && (
              <Box sx={{ mb: 4, display: 'flex', justifyContent: 'flex-start' }}>
                <Button
                  variant="contained"
                  onClick={handleAnalyzeLLM}
                  disabled={llmLoading || !filters.parlamentar || filters.parlamentar === 'Todos'}
                  startIcon={
                    llmLoading ? (
                      <CircularProgress size={30} color="inherit" />
                    ) : (
                      <Box
                        component="img"
                        src="/expressions/antunes_angry.png"
                        alt="Robô Antunes Bravo"
                        sx={{
                          height: 80,
                          width: 80,
                          borderRadius: '50%',
                          border: '3px solid #FFF',
                          objectFit: 'cover',
                          objectPosition: 'center 15%',
                          marginRight: 2,
                          boxShadow: '0 4px 8px rgba(0,0,0,0.3)',
                          bgcolor: '#FFF'
                        }}
                      />
                    )
                  }
                  sx={{
                    backgroundColor: brandColors.azul,
                    '&:hover': { backgroundColor: brandColors.azulClaro },
                    borderRadius: '16px',
                    px: 4,
                    py: 1.5,
                    fontSize: '1.05rem',
                    fontWeight: 'bold',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    minHeight: 60,
                    maxWidth: '100%',
                  }}
                >
                  {llmLoading ? 'Em Análise' : 'Acione o Robô Antunes para auditar as emendas'}
                </Button>
              </Box>
            )}

            {llmError && (
              <Alert severity="error" sx={{ mb: 4, borderRadius: '12px' }} onClose={() => setLlmError(null)}>
                <Typography variant="body2" sx={{ fontWeight: 'bold', mb: 0.5 }}>
                  Não foi possível concluir a análise do Robô Antunes.
                </Typography>
                <Typography variant="caption" sx={{ display: 'block', wordBreak: 'break-word' }}>
                  {llmError}
                </Typography>
              </Alert>
            )}

            {llmResult && (
              <Paper sx={{ p: 4, borderRadius: '24px', mb: 4, border: `2px solid ${brandColors.azul}`, backgroundColor: '#F0F7FF' }}>
                <Stack
                  direction={{ xs: 'column', md: 'row' }}
                  spacing={2}
                  alignItems={{ xs: 'flex-start', md: 'center' }}
                  justifyContent="space-between"
                  sx={{ mb: 2 }}
                >
                  <Stack direction="row" spacing={2} alignItems="center">
                    <AutoAwesome sx={{ fontSize: 32, color: brandColors.azul }} />
                    <Typography variant="h5" sx={{ fontWeight: 'bold', color: brandColors.azul }}>
                      {reportTitle}
                    </Typography>
                  </Stack>
                  <Button
                    variant="contained"
                    startIcon={<PictureAsPdfIcon />}
                    onClick={handleDownloadPdf}
                    sx={{
                      backgroundColor: '#c62828',
                      '&:hover': { backgroundColor: '#8e0000' },
                      borderRadius: '12px',
                      fontWeight: 'bold'
                    }}
                  >
                    Gerar PDF
                  </Button>
                </Stack>
                <Box sx={{ '& p': { mb: 2 }, '& ul': { pl: 3, mb: 2 }, '& li': { mb: 1 } }}>
                  <ReactMarkdown>{llmResult}</ReactMarkdown>
                </Box>
                <Typography variant="caption" sx={{ display: 'block', mt: 2, color: brandColors.cinza }}>
                  * Este relatório foi gerado por inteligência artificial e deve ser verificado.
                </Typography>
              </Paper>
            )}



            <Paper sx={{ p: 3, borderRadius: '24px', mb: 4, backgroundColor: '#EEF4FB' }}>
              <Typography variant="body2" sx={{ color: brandColors.cinza }}>
                ⚠️ As informações são extraídas automaticamente do Portal da Transparência e podem conter divergências.
                Os vínculos entre CNPJ e localização utilizam a mesma base geocodificada do detalhamento de gastos e
                podem apresentar imprecisões pontuais.
              </Typography>
            </Paper>
          </>
        )}

        {/* Modal de Detalhes da Cidade */}
        <Dialog open={openModal} onClose={handleCloseModal} maxWidth="sm" fullWidth>
          {selectedCity && (
            <>
              <DialogTitle sx={{ fontWeight: 'bold', color: brandColors.azul, pb: 1 }}>
                {selectedCity.name}
              </DialogTitle>
              <DialogContent dividers>
                <Typography variant="h6" sx={{ color: brandColors.verde, mb: 3, fontWeight: 'bold' }}>
                  Total: {formatCurrency(selectedCity.value)}
                </Typography>

                <Stack spacing={3}>
                  {/* Prefeitura */}
                  <Box>
                    <div className="flex justify-between mb-1">
                      <span className="font-bold text-gray-700 flex items-center gap-2">
                        🏛️ Prefeitura
                      </span>
                      <span className="font-mono text-blue-800 font-bold">
                        {formatCurrency(selectedCity.details.valor_prefeitura)} ({selectedCity.details.prefeitura.toFixed(1)}%)
                      </span>
                    </div>
                    <div className="w-full h-3 bg-gray-200 rounded-full overflow-hidden">
                      <div className="h-full bg-[#003366]" style={{ width: `${selectedCity.details.prefeitura}%` }}></div>
                    </div>
                  </Box>

                  {/* ONG */}
                  <Box>
                    <div className="flex justify-between mb-1">
                      <span className="font-bold text-gray-700 flex items-center gap-2">
                        🤝 ONG / Entidades
                      </span>
                      <span className="font-mono text-green-700 font-bold">
                        {formatCurrency(selectedCity.details.valor_ong)} ({selectedCity.details.ong.toFixed(1)}%)
                      </span>
                    </div>
                    <div className="w-full h-3 bg-gray-200 rounded-full overflow-hidden">
                      <div className="h-full bg-[#009739]" style={{ width: `${selectedCity.details.ong}%` }}></div>
                    </div>
                  </Box>

                  {/* Empresa */}
                  <Box>
                    <div className="flex justify-between mb-1">
                      <span className="font-bold text-gray-700 flex items-center gap-2">
                        🏢 Empresas Privadas
                      </span>
                      <span className="font-mono text-orange-700 font-bold">
                        {formatCurrency(selectedCity.details.valor_empresa)} ({selectedCity.details.empresa.toFixed(1)}%)
                      </span>
                    </div>
                    <div className="w-full h-3 bg-gray-200 rounded-full overflow-hidden">
                      <div className="h-full bg-[#ED8B00]" style={{ width: `${selectedCity.details.empresa}%` }}></div>
                    </div>
                  </Box>
                </Stack>

                <Box sx={{ mt: 4, display: 'flex', justifyContent: 'flex-end' }}>
                  <Button onClick={handleCloseModal} variant="contained" sx={{ bgcolor: brandColors.azul }}>
                    Fechar
                  </Button>
                </Box>
              </DialogContent>
            </>
          )}
        </Dialog>

        {/* Alertas de Integridade — Sanções CGU (CEIS/CEPIM) cruzadas com emendas/contratos */}
        {analysisData && filters.parlamentar !== 'Todos' && (
          <Paper
            sx={{
              mt: 4,
              mb: 4,
              p: 0,
              borderRadius: '24px',
              overflow: 'hidden',
              border: '1px solid #E0E0E0',
              boxShadow: '0 4px 20px rgba(0,0,0,0.05)'
            }}
          >
            <Box sx={{ p: 4, pb: 2 }}>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, mb: 1 }}>
                <GppBad sx={{ fontSize: 32, color: '#B91C1C' }} />
                <Typography variant="h5" sx={{ fontWeight: 'bold', color: brandColors.azul }}>
                  Alertas de Integridade — Sanções CGU (CEIS/CEPIM)
                </Typography>
              </Box>
              <Typography variant="body2" sx={{ color: brandColors.cinza }}>
                Cruzamento entre o <strong>CEIS</strong> (empresas inidôneas/suspensas) e o <strong>CEPIM</strong> (ONGs impedidas de convênio) —
                bases de dados abertos publicadas pela própria <strong>CGU</strong> no Portal da Transparência — com as emendas e contratos
                ligados a {filters.parlamentar}.
              </Typography>
            </Box>

            {sancoesLoading ? (
              <Box sx={{ display: 'flex', justifyContent: 'center', py: 6 }}>
                <CircularProgress size={40} thickness={4} />
              </Box>
            ) : sancoesAviso ? (
              <Box sx={{ p: 4, pt: 0 }}>
                <Alert severity="info" sx={{ borderRadius: '12px' }}>{sancoesAviso}</Alert>
              </Box>
            ) : sancoesData.alertas.length === 0 ? (
              <Box sx={{ px: 4, pb: 4, display: 'flex', alignItems: 'center', gap: 1.5 }}>
                <VerifiedUser sx={{ color: '#2e7d32' }} />
                <Typography variant="body1" sx={{ color: brandColors.cinza }}>
                  Nenhum alerta de sanção encontrado para {filters.parlamentar}.
                </Typography>
              </Box>
            ) : (
              <Box sx={{ px: 2, pb: 2 }}>
                <Stack direction="row" spacing={2} sx={{ px: 2, mb: 2 }}>
                  <Chip label={`${sancoesData.resumo.total_alertas} alertas no total`} sx={{ fontWeight: 'bold' }} />
                  <Chip label={`${sancoesData.resumo.total_ceis} via CEIS`} variant="outlined" />
                  <Chip label={`${sancoesData.resumo.total_cepim} via CEPIM`} variant="outlined" />
                </Stack>
                <TableContainer component={Box}>
                  <Table>
                    <TableHead sx={{ bgcolor: '#FDFDFD' }}>
                      <TableRow>
                        <TableCell sx={{ fontWeight: 'bold', color: brandColors.azul }}>Base</TableCell>
                        <TableCell sx={{ fontWeight: 'bold', color: brandColors.azul }}>Entidade Sancionada</TableCell>
                        <TableCell sx={{ fontWeight: 'bold', color: brandColors.azul }}>CNPJ</TableCell>
                        <TableCell sx={{ fontWeight: 'bold', color: brandColors.azul }}>Data do Repasse</TableCell>
                        <TableCell sx={{ fontWeight: 'bold', color: brandColors.azul }}>Período da Sanção</TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {sancoesData.alertas.map((alerta, idx) => (
                        <TableRow key={idx} sx={{ '&:hover': { bgcolor: '#F1F5F9' } }}>
                          <TableCell>
                            <Chip
                              size="small"
                              label={alerta.tipo}
                              sx={{
                                fontWeight: 'bold',
                                bgcolor: alerta.tipo?.startsWith('CEIS') ? '#FEF2F2' : '#FFFBEB',
                                color: alerta.tipo?.startsWith('CEIS') ? '#B91C1C' : '#92400E'
                              }}
                            />
                          </TableCell>
                          <TableCell>
                            <Typography variant="body2" sx={{ fontWeight: 'bold' }}>{alerta.nome_entidade}</Typography>
                            <Typography variant="caption" color="text.secondary">{alerta.detalhes}</Typography>
                          </TableCell>
                          <TableCell><Typography variant="body2">{alerta.cnpj}</Typography></TableCell>
                          <TableCell><Typography variant="body2">{alerta.data_evento || '—'}</Typography></TableCell>
                          <TableCell>
                            <Typography variant="body2">
                              {alerta.sancao_inicio || '—'} {alerta.sancao_fim ? `até ${alerta.sancao_fim}` : '(vigente)'}
                            </Typography>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </TableContainer>
              </Box>
            )}
          </Paper>
        )}

      <DataSourceFooter
        sources={[{"label":"Emendas — Portal da Câmara","href":"https://dadosabertos.camara.leg.br","type":"camara"},{"label":"Siga Brasil — Senado Federal","href":"https://www12.senado.leg.br/orcamento/sigabrasil","type":"camara"},{"label":"SIOP — Ministério da Fazenda","href":"https://siop.planejamento.gov.br","type":"receita"},{"label":"CEIS/CEPIM — CGU","href":"https://portaldatransparencia.gov.br/sancoes","type":"cgu"}]}
        note="Emendas parlamentares individuais e de bancada extraídas do SIOP e do Portal de Dados Abertos da Câmara dos Deputados. Cruzamento com sanções CEIS/CEPIM publicadas pela CGU."
      />
    </Container>
    </Box >
  );
};

export default EmendasParlamentares;
