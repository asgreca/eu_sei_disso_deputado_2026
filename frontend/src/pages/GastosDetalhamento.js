import React, { useState, useEffect, useRef } from 'react';
import {
  Container, Grid, Paper, Typography, Box, CircularProgress,
  Card, CardContent, Chip, Divider, Button, Alert,
  Table, TableBody, TableCell, TableContainer, TableHead, TableRow,
  IconButton, Tooltip, Dialog, DialogTitle, DialogContent, DialogActions,
  Tabs, Tab, Snackbar, FormControl, RadioGroup, FormControlLabel, Radio,
  Avatar, LinearProgress, TextField, InputLabel, Select, MenuItem, Stack
} from '@mui/material';
import {
  LocationOn as LocationOnIcon,
  Search as SearchIcon,
  Email as EmailIcon,
  Assessment as AssessmentIcon,
  Send as SendIcon,
  OpenInNew as OpenInNewIcon,
  ContentCopy as ContentCopyIcon,
  PictureAsPdf as PictureAsPdfIcon,
  Gavel as GavelIcon,
  Close as CloseIcon,
  AutoAwesome as AutoAwesomeIcon,
  GppBad as GppBadIcon,
  VerifiedUser as VerifiedUserIcon
} from '@mui/icons-material';
import ReactECharts from 'echarts-for-react';
import ReactMarkdown from 'react-markdown';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import 'leaflet/dist/leaflet.css';
import badgesData from '../data/badges.json';
import { API_HEADERS, API_BASE_URL } from '../config';
import FilterSelector from '../components/FilterSelector';

// Fix para ícones do Leaflet
delete L.Icon.Default.prototype._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: require('leaflet/dist/images/marker-icon-2x.png'),
  iconUrl: require('leaflet/dist/images/marker-icon.png'),
  shadowUrl: require('leaflet/dist/images/marker-shadow.png'),
});

// Paleta de cores do Manual de Marca
const CORES_MARCA = {
  verde: '#009739',
  amarelo: '#FFF81C',
  azul: '#003366',
  branco: '#FFFFFF',
  cinza: '#666666',
  azulClaro: '#4F81BD',
  verdeClaro: '#66BB6A',
  cinzaClaro: '#E0E0E0',
  laranjaEscuro: '#ED8B00',
  laranjaClaro: '#FFB74D',
};

import { PARTIDO_LOGOS_FALLBACK, ESTADO_LOGOS_FALLBACK } from '../utils/logos';
import DataSourceFooter from '../components/DataSourceFooter';

const normalizeCommonsFileUrl = (value) => {
  const raw = String(value || '').trim();
  if (!raw) return '';
  return raw;
};

// URLs de domínios confiáveis carregam direto (sem proxy) para evitar duplo-encoding
const TRUSTED_DOMAINS = ['upload.wikimedia.org', 'commons.wikimedia.org', 'www.camara.leg.br', 'flagcdn.com', 'i.ibb.co', 'images.seeklogo.com'];
const isTrustedUrl = (url) => TRUSTED_DOMAINS.some(d => String(url || '').includes(d));

const proxyImg = (url) => {
  const normalized = normalizeCommonsFileUrl(url);
  if (!normalized) return '';
  if (isTrustedUrl(normalized)) return normalized; // direto, sem proxy
  return `${API_BASE_URL}/api/proxy/imagem?url=${encodeURIComponent(normalized)}`;
};

const getPartidoLogo = (info) => {
  if (!info) return '';
  const partido = String(info.sgPartido || info.partido || '').toUpperCase().trim();
  const urlOriginal = info.urlPartido || info.partido_logo_url || info.logo_partido;
  return PARTIDO_LOGOS_FALLBACK[partido] || normalizeCommonsFileUrl(urlOriginal) || '';
};

const getEstadoLogo = (info) => {
  if (!info) return '';
  const uf = String(info.sgUF || info.estado || '').toUpperCase().trim();
  if (!uf) return '';
  const urlOriginal = info.urlEstado || info.estado_logo_url || info.bandeira_estado;
  return ESTADO_LOGOS_FALLBACK[uf] || normalizeCommonsFileUrl(urlOriginal) || '';
};

const handlePartidoLogoError = (event, info) => {
  const fallback = PARTIDO_LOGOS_FALLBACK[String(info?.sgPartido || info?.partido || '').toUpperCase().trim()];
  const proxiedFallback = proxyImg(fallback);
  if (proxiedFallback && event.target.src !== proxiedFallback) {
    event.target.src = proxiedFallback;
  } else {
    event.target.style.display = 'none';
  }
};

const handleEstadoLogoError = (event, info) => {
  const fallback = proxyImg(getEstadoLogo({
    estado: String(info?.sgUF || info?.estado || '').toUpperCase().trim()
  }));
  if (fallback && event.target.src !== fallback) {
    event.target.src = fallback;
  } else {
    event.target.style.display = 'none';
  }
};

const ordenarSerieTemporal = (serie = []) => {
  return serie
    .map((item) => {
      if (!item?.periodo) return null;
      const [mes, ano] = item.periodo.split('/');
      const dataOrdenacao = mes && ano ? new Date(parseInt(ano, 10), parseInt(mes, 10) - 1, 1) : null;
      return dataOrdenacao && !Number.isNaN(dataOrdenacao.valueOf())
        ? { ...item, _dataOrdenacao: dataOrdenacao }
        : null;
    })
    .filter(Boolean)
    .sort((a, b) => a._dataOrdenacao - b._dataOrdenacao)
    .map(({ _dataOrdenacao, ...rest }) => rest);
};

const prepararTopFornecedores = (lista = []) => {
  if (!Array.isArray(lista) || lista.length === 0) return [];

  const ordenado = [...lista].sort((a, b) => (b.total || 0) - (a.total || 0));
  if (ordenado.length <= 5) {
    return ordenado;
  }

  const topQuatro = ordenado.slice(0, 4);
  const demais = ordenado.slice(4);

  const agregados = demais.reduce(
    (acc, item) => {
      acc.total += item.total || 0;
      acc.quantidade += item.quantidade || 0;
      acc.medias.push(item.media || 0);
      return acc;
    },
    { total: 0, quantidade: 0, medias: [] }
  );

  const mediaOutros =
    agregados.medias.length > 0
      ? agregados.medias.reduce((soma, valor) => soma + valor, 0) / agregados.medias.length
      : 0;

  const itemOutros = {
    fornecedor: 'Outros fornecedores',
    total: agregados.total,
    quantidade: agregados.quantidade,
    media: mediaOutros,
    atipico: false,
  };

  return [...topQuatro, itemOutros];
};

// Mapeamento de despesas (nome técnico -> nome fantasia com emoji)
const MAPA_DESPESAS = {
  "LOCAÇÃO OU FRETAMENTO DE VEÍCULOS AUTOMOTORES": "🚗 Gasto com veículos",
  "DIVULGAÇÃO DA ATIVIDADE PARLAMENTAR.": "📢 Gasto com divulgação",
  "MANUTENÇÃO DE ESCRITÓRIO DE APOIO À ATIVIDADE PARLAMENTAR": "🏢 Gasto com locação de imóveis",
  "COMBUSTÍVEIS E LUBRIFICANTES.": "⛽ Gasto com Combustível",
  "SERVIÇO DE SEGURANÇA PRESTADO POR EMPRESA ESPECIALIZADA.": "👮‍♂️ Gasto com segurança",
  "TELEFONIA": "📞 Gasto com telefonia",
  "ASSINATURA DE PUBLICAÇÕES": "📖 Gasto com revistas",
  "FORNECIMENTO DE ALIMENTAÇÃO DO PARLAMENTAR": "🍽️ Gasto com Alimentação",
  "HOSPEDAGEM ,EXCETO DO PARLAMENTAR NO DISTRITO FEDERAL.": "🏨 Gasto com hospedagem",
  "AQUISIÇÃO DE TOKENS E CERTIFICADOS DIGITAIS": "🔑 Gasto com tokens",
  "LOCAÇÃO OU FRETAMENTO DE AERONAVES": "🛩️ Gasto com locação de aeronaves",
  "PARTICIPAÇÃO EM CURSO, PALESTRA OU EVENTO SIMILAR": "🎤 Gasto com palestras",
  "PASSAGENS TERRESTRES, MARÍTIMAS OU FLUVIAIS": "🚌 Gasto com passagem terrestre",
  "LOCAÇÃO OU FRETAMENTO DE EMBARCAÇÕES": "🚤 Locação de embarcações",
  "SERVIÇO DE TÁXI, PEDÁGIO E ESTACIONAMENTO": "🚕 Táxi, Pedágio e Estacionamento"
};

const formatarNomeDespesa = (despesaTecnica) => {
  return MAPA_DESPESAS[despesaTecnica] || despesaTecnica;
};

// Componente de Mapa
const MapaFornecedores = ({ fornecedores, formatarMoeda }) => {
  const mapRef = useRef(null);
  const mapInstanceRef = useRef(null);
  const markersGroupRef = useRef(null);

  useEffect(() => {
    if (!mapRef.current || mapInstanceRef.current) return;

    const map = L.map(mapRef.current).setView([-15.7801, -47.9292], 4);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '© OpenStreetMap contributors'
    }).addTo(map);

    markersGroupRef.current = L.layerGroup().addTo(map);
    mapInstanceRef.current = map;

    return () => {
      if (mapInstanceRef.current) {
        mapInstanceRef.current.remove();
        mapInstanceRef.current = null;
      }
    };
  }, []);

  useEffect(() => {
    if (!mapInstanceRef.current || !fornecedores || fornecedores.length === 0) return;

    const map = mapInstanceRef.current;
    const markersLayer = markersGroupRef.current;
    if (!markersLayer) return;

    markersLayer.clearLayers();
    const bounds = [];

    // Coordenadas aproximadas do polígono brasileiro (Simplified Bounding Box)
    const BRAZIL_BOUNDS = { lat: [-34.0, 5.5], lng: [-74.0, -34.5] };

    // Coordenadas de referência para as capitais/principais cidades (Snap points)
    const SnapPoints = {
      'Brasília': [-15.7801, -47.9292],
      'São Paulo': [-23.5505, -46.6333],
      'Rio de Janeiro': [-22.9068, -43.1729],
      'Curitiba': [-25.4290, -49.2671],
      'Belo Horizonte': [-19.9167, -43.9345],
      'Porto Alegre': [-30.0331, -51.2300],
      'Salvador': [-12.9714, -38.5014],
      'Fortaleza': [-3.7172, -38.5433],
      'Manaus': [-3.1190, -60.0217],
      'Recife': [-8.0539, -34.8812],
      'Goiânia': [-16.6869, -49.2648],
      'Belém': [-1.4558, -48.4902],
      'Florianópolis': [-27.5954, -48.5480],
      'Vitória': [-20.3155, -40.3128],
      'São Luís': [-2.5307, -44.3068],
      'Natal': [-5.7945, -35.2110],
      'Cuiabá': [-15.6010, -56.0974],
      'João Pessoa': [-7.1153, -34.8610],
      'Teresina': [-5.0920, -42.8038],
      'Campo Grande': [-20.4435, -54.6478],
      'Aracaju': [-10.9111, -37.0717],
      'Maceió': [-9.6658, -35.7350],
      'Porto Velho': [-8.7619, -63.9039],
      'Macapá': [0.0349, -51.0664],
      'Rio Branco': [-9.9747, -67.8101],
      'Boa Vista': [2.8235, -60.6758],
      'Palmas': [-10.1838, -48.3336]
    };

    fornecedores.forEach(forn => {
      let lat = parseFloat(forn.latitude);
      let lng = parseFloat(forn.longitude);

      // 1. Verificar se está dentro do Brasil
      const isOutsideBrazil = (lat < BRAZIL_BOUNDS.lat[0] || lat > BRAZIL_BOUNDS.lat[1] ||
        lng < BRAZIL_BOUNDS.lng[0] || lng > BRAZIL_BOUNDS.lng[1]);

      // 2. Se estiver fora ou precisar de "snap" por inconsistência
      if (isOutsideBrazil || !lat || !lng) {
        // Tentar snap pela cidade informada
        if (forn.cidade && SnapPoints[forn.cidade]) {
          [lat, lng] = SnapPoints[forn.cidade];
        } else {
          // Se não tiver cidade conhecida, não renderiza (Segurança 1)
          return;
        }
      }

      // 3. Renderização do Marcador (Mesma lógica anterior)
      const nomeFantasia = MAPA_DESPESAS[forn.descricao] || '';
      const emoji = nomeFantasia.split(' ')[0] || '📍';
      const corFundo = forn.atipico ? '#FF9800' : '#4CAF50';
      const corBorda = forn.atipico ? '#F57C00' : '#388E3C';

      const icon = L.divIcon({
        html: `
          <div style="
            background-color: ${corFundo};
            border: 2px solid ${corBorda};
            border-radius: 50%;
            width: 36px;
            height: 36px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 20px;
            box-shadow: 2px 2px 5px rgba(0,0,0,0.3);
          ">
            ${emoji}
          </div>
        `,
        className: 'custom-map-icon',
        iconSize: [40, 40],
        iconAnchor: [20, 40],
        popupAnchor: [0, -40]
      });

      const marker = L.marker([lat, lng], { icon });
      markersLayer.addLayer(marker);
      bounds.push([lat, lng]);

      marker.bindPopup(`
        <div style="min-width: 200px;">
        <strong>${forn.fornecedor}</strong><br />
        <span style="font-size: 12px; color: #666;">${nomeFantasia}</span><br />
          ${(forn.cidade && forn.cidade !== 'Desconhecido' && forn.cidade !== 'Cidade não informada') ? `<span>${forn.cidade}</span>` : ''}
        </div>
        💰 Total: ${formatarMoeda(forn.total)}<br />
        📄 Notas: ${forn.num_notas}<br />
        ${forn.atipico ? '<span style="color: red; font-weight: bold;">⚠️ ATÍPICO</span>' : ''}
      </div>
      `);
    });

    if (bounds.length > 0) {
      const latLngBounds = L.latLngBounds(bounds);
      map.fitBounds(latLngBounds, { padding: [50, 50] });
    }

  }, [fornecedores, formatarMoeda]);

  return <div ref={mapRef} style={{ height: '100%', width: '100%' }} />;
};

const RedeFornecedoresGraph = ({ data, loading, parlamentarNome, loadingProgress = 0, loadingMessage = 'Carregando sociograma...', loadingElapsed = 0 }) => {
  const isFinishing = loadingProgress >= 90;

  // Loading State
  if (loading) return (
    <Box sx={{ p: 4, textAlign: 'center', maxWidth: 640, mx: 'auto' }}>
      <CircularProgress size={30} sx={{ mb: 2 }} />
      <Typography variant="h6" sx={{ color: CORES_MARCA.azul, fontWeight: 'bold', mb: 1 }}>
        Montando sociograma...
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        {loadingMessage}
      </Typography>
      <Box sx={{ textAlign: 'left', bgcolor: '#f8fafc', border: '1px solid #dbe6f3', borderRadius: 2, p: 2 }}>
        <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 1 }}>
          <Typography variant="caption" sx={{ fontFamily: 'monospace', fontWeight: 'bold', color: CORES_MARCA.azul }}>
            tqdm do sociograma
          </Typography>
          <Typography variant="caption" sx={{ fontFamily: 'monospace', color: 'text.secondary' }}>
            {isFinishing ? 'finalizando...' : `${Math.round(loadingProgress)}%`} | {loadingElapsed}s
          </Typography>
        </Box>
        <LinearProgress
          variant={isFinishing ? 'indeterminate' : 'determinate'}
          value={isFinishing ? undefined : Math.max(4, Math.min(loadingProgress, 100))}
          sx={{
            height: 10,
            borderRadius: 999,
            bgcolor: '#e6eef7',
            '& .MuiLinearProgress-bar': {
              borderRadius: 999,
              background: `linear-gradient(90deg, ${CORES_MARCA.verde} 0%, ${CORES_MARCA.azulClaro} 100%)`
            }
          }}
        />
        <Typography variant="caption" sx={{ display: 'block', mt: 1, color: 'text.secondary' }}>
          {isFinishing
            ? 'Aguardando a resposta final do servidor para desenhar os nós e conexões.'
            : 'Buscando fornecedores, cruzando deputados e organizando clusters visuais do grafo.'}
        </Typography>
      </Box>
    </Box>
  );

  const isInitial = !data;
  const isError = Boolean(data?.error);
  const isEmpty = !isInitial && !isError && Array.isArray(data?.nodes) && data.nodes.length === 0;

  // Initial State
  if (isInitial) {
    return (
      <Box sx={{ height: 400, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', textAlign: 'center', color: 'text.secondary', bgcolor: 'rgba(0,0,0,0.02)', borderRadius: 2, border: '1px dashed #ccc', p: 3 }}>
        <SearchIcon sx={{ fontSize: 40, mb: 2, opacity: 0.5 }} />
        <Typography variant="h6" sx={{ color: CORES_MARCA.azul, fontWeight: 'bold' }}>
          Aguardando Análise...
        </Typography>
        <Typography variant="body2">
          Clique em <strong>Executar Análise</strong> para gerar o sociograma.
        </Typography>
      </Box>
    );
  }

  // Empty or Error State
  if (isError || isEmpty) {

    return (
      <Box sx={{ height: 400, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', textAlign: 'center', color: 'text.secondary', bgcolor: 'rgba(0,0,0,0.02)', borderRadius: 2, border: '1px dashed #ccc', p: 3 }}>
        <SearchIcon sx={{ fontSize: 40, mb: 2, opacity: 0.5 }} />
        <Typography variant="h6">
          {isEmpty ? 'Nenhum fornecedor compartilhado encontrado.' : 'Erro ao carregar sociograma.'}
        </Typography>
        <Typography variant="body2" sx={{ mb: 3 }}>
          {isEmpty ? 'Tente outra despesa ou parlamentar com mais gastos compartilhados.' : 'Houve um problema na comunicação com o servidor.'}
        </Typography>

        {isError && (
          <Box sx={{ mt: 2, p: 2, bgcolor: '#fff3e0', border: '1px solid #ffe0b2', borderRadius: 1, textAlign: 'left', minWidth: '300px' }}>
            <Typography variant="caption" sx={{ fontWeight: 'bold', display: 'block', mb: 1, color: '#e65100' }}>
              🛠️ DEBUG DO SERVIDOR
            </Typography>
            <pre style={{ margin: 0, fontSize: '11px', whiteSpace: 'pre-wrap', wordBreak: 'break-all', maxHeight: '200px', overflowY: 'auto' }}>
              {data?.debug ? JSON.stringify(data.debug, null, 2) : JSON.stringify(data, null, 2)}
            </pre>
          </Box>
        )}
      </Box>
    );
  }

  const graphNodes = data.nodes || [];
  const graphLinks = data.links || [];
  const partyNodes = graphNodes.filter((node) => node.category === 'Partido');
  const stateNodes = graphNodes.filter((node) => node.category === 'Estado');

  const partyPositionMap = new Map();
  partyNodes.forEach((node, index) => {
    const angle = (Math.PI * 2 * index) / Math.max(partyNodes.length, 1);
    partyPositionMap.set(node.name, {
      x: Math.cos(angle) * 360,
      y: Math.sin(angle) * 220 - 120,
    });
  });

  const statePositionMap = new Map();
  stateNodes.forEach((node, index) => {
    const angle = (Math.PI * 2 * index) / Math.max(stateNodes.length, 1);
    statePositionMap.set(node.name, {
      x: Math.cos(angle) * 280,
      y: Math.sin(angle) * 180 + 180,
    });
  });

  const getSeededPosition = (node) => {
    if (node.category === 'Parlamentar' && node.id.includes(parlamentarNome?.replace(' ', '_'))) {
      return { x: 0, y: 0 };
    }

    if (node.category === 'Parlamentar') {
      const baseParty = partyPositionMap.get(node.partido) || { x: 0, y: -140 };
      const baseState = statePositionMap.get(node.estado) || { x: 0, y: 140 };
      const seed = (node.name || '').split('').reduce((acc, char) => acc + char.charCodeAt(0), 0);
      const offsetX = ((seed % 7) - 3) * 18;
      const offsetY = ((seed % 11) - 5) * 14;
      return {
        x: (baseParty.x * 0.65) + (baseState.x * 0.35) + offsetX,
        y: (baseParty.y * 0.65) + (baseState.y * 0.35) + offsetY,
      };
    }

    if (node.category === 'Partido') {
      return partyPositionMap.get(node.name) || { x: 0, y: -220 };
    }

    if (node.category === 'Estado') {
      return statePositionMap.get(node.name) || { x: 0, y: 220 };
    }

    if (node.category === 'Fornecedor') {
      const seed = (node.id || '').split('').reduce((acc, char) => acc + char.charCodeAt(0), 0);
      return {
        x: ((seed % 9) - 4) * 55,
        y: ((seed % 13) - 6) * 40,
      };
    }

    if (node.category === 'Sanção') {
      // Nasce perto do fornecedor ligado a ela (mesmo CNPJ no id) e a força do grafo cuida do resto.
      const cnpjSancao = (node.id || '').replace('SANCAO_', '');
      const seedForn = `FORN_${cnpjSancao}`.split('').reduce((acc, char) => acc + char.charCodeAt(0), 0);
      return {
        x: ((seedForn % 9) - 4) * 55 + 45,
        y: ((seedForn % 13) - 6) * 40 + 35,
      };
    }

    return { x: 0, y: 0 };
  };

  // Graph Options
  const option = {
    title: {
      text: '🤝 Sociograma de Conexões Financeiras',
      subtext: 'Deputado ➔ Fornecedores ➔ Outros Deputados',
      left: 'center',
      top: 10,
      textStyle: { color: CORES_MARCA.azul, fontWeight: 'bold', fontSize: 18 }
    },
    tooltip: {
      trigger: 'item',
      backgroundColor: 'rgba(255, 255, 255, 0.98)',
      borderColor: CORES_MARCA.azul,
      borderWidth: 2,
      padding: 10,
      formatter: (params) => {
        if (params.dataType === 'node') {
          const extras = [];
          if (params.data?.cidade_empresa && params.data.cidade_empresa !== 'Desconhecido') {
            extras.push(`Cidade: ${params.data.cidade_empresa}`);
          }
          if (params.data?.estado_empresa && params.data.estado_empresa !== 'Desconhecido') {
            extras.push(`UF: ${params.data.estado_empresa}`);
          }
          if (params.data?.cidade_empresa && params.data?.estado_empresa && params.data.estado_empresa !== 'Desconhecido') {
            extras.unshift(`Local: ${params.data.cidade_empresa}/${params.data.estado_empresa}`);
          }
          const alertaSancao = params.data?.sancionado
            ? `<br/><span style="color:#dc2626;font-weight:bold">⚠️ SANCIONADA (${params.data.sancao_base}${params.data.sancao_categoria ? ' — ' + params.data.sancao_categoria : ''})</span>`
            : '';
          return `<div style="text-align:center">
            <b style="font-size:14px">${params.data?.fullName || params.name}</b><br/>
            <span style="color:#666">${params.data.category}</span>
            ${extras.length ? `<br/><span style="color:#666">${extras.join('<br/>')}</span>` : ''}
            ${alertaSancao}
          </div>`;
        }
        return `<b>${params.data.source}</b> ➔ <b>${params.data.target}</b>`;
      }
    },
    legend: {
      data: ['Parlamentar', 'Fornecedor', 'Estado', 'Partido', 'Sanção'],
      bottom: 10
    },
    series: [
      {
        type: 'graph',
        layout: 'force',
        data: graphNodes.map(node => {
          const isImage = node.symbol && typeof node.symbol === 'string' && node.symbol.startsWith('image://');
          const isMain = node.category === 'Parlamentar' && node.id.includes(parlamentarNome?.replace(' ', '_'));
          const nodeSize = node.category === 'Parlamentar' ? (isMain ? 60 : 45) : (isImage ? 35 : 25);
          const isDecorative = node.category === 'Estado' || node.category === 'Partido';
          const seededPosition = getSeededPosition(node);

          return {
            ...node,
            x: seededPosition.x,
            y: seededPosition.y,
            symbolSize: [nodeSize, nodeSize],
            label: {
              show: true,
              position: 'bottom',
              color: '#333333',
              fontSize: 11,
              fontWeight: 'bold',
              backgroundColor: 'rgba(255, 255, 255, 0.95)',
              borderColor: CORES_MARCA.azul,
              borderWidth: 1,
              borderRadius: 4,
              padding: [4, 8],
              distance: 5
            },
            labelFormatterExtra: node.category === 'Fornecedor' && node.showLabel && node.cidade_empresa && node.estado_empresa
              ? `${String(node.cidade_empresa).toUpperCase()}/${String(node.estado_empresa).toUpperCase()}`
              : null,
            itemStyle: {
              ...node.itemStyle,
              borderRadius: '50%',
              color: isImage || isDecorative ? '#FFFFFF' : (node.itemStyle?.color || undefined),
              borderWidth: isImage ? (node.category === 'Parlamentar' ? 3 : 2) : 0,
              borderColor: isImage ? (node.category === 'Parlamentar' ? '#003366' : '#CCCCCC') : 'transparent',
              shadowBlur: isImage ? 12 : 0,
              shadowColor: isImage ? (node.category === 'Parlamentar' ? 'rgba(0, 51, 102, 0.3)' : 'rgba(0,0,0,0.15)') : 'transparent'
            },
            emphasis: {
              itemStyle: {
                borderRadius: '50%',
                borderWidth: isImage ? 6 : 0,
                shadowBlur: 20
              },
              label: {
                show: true,
                fontSize: 12,
                backgroundColor: '#ffffff'
              }
            }
          };
        }),
        links: graphLinks.map((link) => ({
          ...link,
          lineStyle: {
            ...link.lineStyle,
            opacity:
              link.kind === 'party_affiliation' ? 0.35 :
              link.kind === 'state_affiliation' ? 0.28 :
              link.kind === 'supplier_primary' ? 0.45 :
              link.kind === 'supplier_shared' ? 0.38 :
              (link.lineStyle?.opacity ?? 0.4),
            width:
              link.kind === 'party_affiliation' ? 2.6 :
              link.kind === 'state_affiliation' ? 2.1 :
              link.kind === 'supplier_primary' ? 2.8 :
              link.kind === 'supplier_shared' ? 1.8 :
              (link.lineStyle?.width ?? 1.5),
          }
        })),
        categories: [
          { name: 'Parlamentar', itemStyle: { color: CORES_MARCA.azul } },
          { name: 'Fornecedor', itemStyle: { color: '#FF8C00' } },
          { name: 'Estado', itemStyle: { color: '#ED8B00' } },
          { name: 'Partido', itemStyle: { color: CORES_MARCA.verde } },
          { name: 'Sanção', itemStyle: { color: '#7f1d1d' } }
        ],
        roam: true,
        label: {
          show: false // Individual labels in data take precedence
        },
        lineStyle: {
          color: 'source',
          curveness: 0.2,
          opacity: 0.4
        },
        force: {
          repulsion: 2200,
          gravity: 0.08,
          friction: 0.15,
          edgeLength: [70, 220]
        },
        labelLayout: { hideOverlap: true }
      }
    ]
  };

  option.series[0].label.formatter = (params) => {
    const localExtra = params.data?.labelFormatterExtra;
    return localExtra ? `${params.name}\n${localExtra}` : params.name;
  };

  return (
    <Paper elevation={0} sx={{
      p: 2,
      borderRadius: 2,
      border: '1px solid #E0E0E0',
      backgroundColor: '#FFFFFF',
      overflow: 'hidden',
      '& svg image': {
        clipPath: 'circle(50%)'
      }
    }}>
      <ReactECharts
        option={option}
        style={{ height: '700px', width: '100%' }}
        opts={{ renderer: 'svg' }}
      />
    </Paper>
  );
};


function GastosDetalhamento() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [progress, setProgress] = useState(0);
  const [statusText, setStatusText] = useState('');


  const [filtros, setFiltros] = useState({
    estado: 'Todos',
    partido: 'Todos',
    parlamentar: 'Todos',
    despesa: 'Todos'
  });

  const [dadosParlamentar, setDadosParlamentar] = useState([]);
  const [limiteAtipico, setLimiteAtipico] = useState(null);
  const [metricasBasicas, setMetricasBasicas] = useState({});
  const [metricasComparativas, setMetricasComparativas] = useState({});
  const [dadosTemporais, setDadosTemporais] = useState([]);
  const [dadosFornecedores, setDadosFornecedores] = useState([]);
  const [dadosMapa, setDadosMapa] = useState([]);
  const [dadosGrafo, setDadosGrafo] = useState(null);
  const [loadingGrafo, setLoadingGrafo] = useState(false);
  const [graphProgress, setGraphProgress] = useState(0);
  const [graphLoadingMessage, setGraphLoadingMessage] = useState('Preparando sociograma...');
  const [graphLoadingElapsed, setGraphLoadingElapsed] = useState(0);
  const [filtrosEmpresasGrafo, setFiltrosEmpresasGrafo] = useState({
    estado: 'Todos',
    cidade: 'Todos'
  });

  // Fornecedores da COTA PARLAMENTAR (CEAP) que estão sancionados no CEIS/CEPIM da CGU.
  // Diferente de emendas (que ficam em /gastos/emendas), aqui cruzamos os gastos de
  // gabinete do próprio deputado com as bases de sanções.
  const [ceapSancionadosData, setCeapSancionadosData] = useState({ resumo: { total_fornecedores_sancionados: 0, valor_total: 0 }, fornecedores: [], disclaimer: '' });
  const [ceapSancionadosLoading, setCeapSancionadosLoading] = useState(false);
  const [ceapSancionadosAviso, setCeapSancionadosAviso] = useState(null);

  const carregarFornecedoresSancionadosCeap = async (parlamentar, despesa) => {
    if (!parlamentar || parlamentar === 'Todos') {
      setCeapSancionadosData({ resumo: { total_fornecedores_sancionados: 0, valor_total: 0 }, fornecedores: [], disclaimer: '' });
      return;
    }
    try {
      setCeapSancionadosLoading(true);
      const params = new URLSearchParams({ parlamentar });
      if (despesa && despesa !== 'Todos') params.append('despesa', despesa);
      const response = await fetch(`${API_BASE_URL}/api/gastos/fornecedores-sancionados?${params.toString()}`, { headers: API_HEADERS });
      if (!response.ok) throw new Error(`Erro na API: ${response.status}`);
      const result = await response.json();
      setCeapSancionadosData(result);
      setCeapSancionadosAviso(result.aviso || null);
    } catch (err) {
      console.error('Erro ao buscar fornecedores CEAP sancionados:', err);
    } finally {
      setCeapSancionadosLoading(false);
    }
  };
  const [infoParlamentar, setInfoParlamentar] = useState(null);
  const [mostrarApenasAtipicos, setMostrarApenasAtipicos] = useState(true);

  const [relatorioAuditoria, setRelatorioAuditoria] = useState('');
  const [emailGerado, setEmailGerado] = useState('');
  const [loadingRelatorio, setLoadingRelatorio] = useState(false);
  const [loadingEmail, setLoadingEmail] = useState(false);

  // Estados para Auditor IA (Novo)
  const [llmLoading, setLlmLoading] = useState(false);
  const [llmResult, setLlmResult] = useState(null);

  // Estados Auditor Antunes
  const [antunesModalOpen, setAntunesModalOpen] = useState(false);
  const [antunesLoading, setAntunesLoading] = useState(false);
  const [dadosAntunes, setDadosAntunes] = useState(null);
  const [tabAntunes, setTabAntunes] = useState(0);
  const [orgaoDestino, setOrgaoDestino] = useState('TCU'); // Estado para o seletor de órgão
  const [snackbarOpen, setSnackbarOpen] = useState(false);
  const [snackbarMessage, setSnackbarMessage] = useState('');

  // Estado para barra de progresso simulada
  const [progressValue, setProgressValue] = useState(0);
  const [progressMessage, setProgressMessage] = useState('Iniciando auditoria...');

  const fornecedoresNoGrafo = React.useMemo(() => {
    const nodes = Array.isArray(dadosGrafo?.nodes) ? dadosGrafo.nodes : [];
    const mapa = Array.isArray(dadosMapa) ? dadosMapa : [];

    const fornecedoresGrafo = nodes
      .filter((node) => node.category === 'Fornecedor')
      .map((node) => ({
        id: node.id,
        fornecedor: node.fullName || node.name,
        cidade_empresa: node.cidade_empresa,
        estado_empresa: node.estado_empresa,
      }));

    return fornecedoresGrafo.map((fornecedorNode) => {
      const match = mapa.find((item) => (item.fornecedor || '').trim() === (fornecedorNode.fornecedor || '').trim());
      return {
        ...fornecedorNode,
        cidade: fornecedorNode.cidade_empresa || match?.cidade_cadastral || match?.cidade || 'Desconhecido',
        estado: fornecedorNode.estado_empresa || match?.estado_fornecedor || match?.estado || 'Desconhecido',
      };
    });
  }, [dadosGrafo, dadosMapa]);

  const estadosEmpresasNoGrafo = React.useMemo(() => {
    return [...new Set(
      fornecedoresNoGrafo
        .map((item) => item.estado)
        .filter((estado) => estado && estado !== 'Desconhecido')
    )].sort();
  }, [fornecedoresNoGrafo]);

  const cidadesEmpresasNoGrafo = React.useMemo(() => {
    return [...new Set(
      fornecedoresNoGrafo
        .filter((item) => filtrosEmpresasGrafo.estado === 'Todos' || item.estado === filtrosEmpresasGrafo.estado)
        .map((item) => item.cidade)
        .filter((cidade) => cidade && cidade !== 'Desconhecido')
    )].sort();
  }, [fornecedoresNoGrafo, filtrosEmpresasGrafo.estado]);

  const dadosGrafoFiltrados = React.useMemo(() => {
    if (!dadosGrafo?.nodes || !dadosGrafo?.links) return dadosGrafo;

    const fornecedoresPermitidos = new Set(
      fornecedoresNoGrafo
        .filter((item) => filtrosEmpresasGrafo.estado === 'Todos' || item.estado === filtrosEmpresasGrafo.estado)
        .filter((item) => filtrosEmpresasGrafo.cidade === 'Todos' || item.cidade === filtrosEmpresasGrafo.cidade)
        .map((item) => item.id)
    );

    if (fornecedoresPermitidos.size === 0 && (filtrosEmpresasGrafo.estado !== 'Todos' || filtrosEmpresasGrafo.cidade !== 'Todos')) {
      return { ...dadosGrafo, nodes: [], links: [] };
    }

    const filteredLinks = (dadosGrafo.links || []).filter((link) => {
      const source = typeof link.source === 'object' ? link.source.id : link.source;
      const target = typeof link.target === 'object' ? link.target.id : link.target;
      const involvesSupplier =
        String(source || '').startsWith('FORN_') || String(target || '').startsWith('FORN_');

      if (!involvesSupplier) return true;
      return fornecedoresPermitidos.has(source) || fornecedoresPermitidos.has(target);
    });

    const nodeIds = new Set();
    filteredLinks.forEach((link) => {
      nodeIds.add(typeof link.source === 'object' ? link.source.id : link.source);
      nodeIds.add(typeof link.target === 'object' ? link.target.id : link.target);
    });

    const filteredNodes = (dadosGrafo.nodes || []).filter((node) => {
      if (node.category === 'Fornecedor') {
        return fornecedoresPermitidos.has(node.id);
      }
      return nodeIds.has(node.id);
    });

    return {
      ...dadosGrafo,
      nodes: filteredNodes,
      links: filteredLinks,
    };
  }, [dadosGrafo, fornecedoresNoGrafo, filtrosEmpresasGrafo]);

  useEffect(() => {
    let interval;
    if (antunesLoading) {
      setProgressValue(0);
      const messages = [
        "Conectando à Base da Receita Federal...",
        "Verificando Quadro Societário e Parentesco...",
        "Analisando Volumetria de Abastecimentos...",
        "Cruzando Dados de Geolocalização...",
        "Aplicando Lei de Benford...",
        "Calculando Probabilidade de Fraude...",
        "Redigindo Relatório Final..."
      ];
      let step = 0;
      interval = setInterval(() => {
        step++;
        const progress = Math.min((step / messages.length) * 100, 95);
        setProgressValue(progress);
        if (step < messages.length) {
          setProgressMessage(messages[step]);
        }
      }, 2500); // Muda a cada 2.5 segundos
    } else {
      setProgressValue(100);
    }
    return () => clearInterval(interval);
  }, [antunesLoading]);

  useEffect(() => {
    if (!loadingGrafo) {
      setGraphProgress(0);
      setGraphLoadingElapsed(0);
      setGraphLoadingMessage('Preparando sociograma...');
      return;
    }

    const etapas = [
      { limit: 18, message: 'Consultando fornecedores da despesa selecionada...' },
      { limit: 36, message: 'Encontrando deputados que usaram as mesmas empresas...' },
      { limit: 58, message: 'Relacionando partidos e estados no grafo...' },
      { limit: 78, message: 'Agrupando clusters visuais do sociograma...' },
      { limit: 89, message: 'Finalizando layout e conexões...' },
      { limit: 94, message: 'Aguardando resposta final do servidor...' }
    ];

    setGraphProgress(6);
    setGraphLoadingElapsed(0);
    setGraphLoadingMessage(etapas[0].message);

    const interval = setInterval(() => {
      setGraphLoadingElapsed((prev) => prev + 1);
      setGraphProgress((prev) => {
        const next = Math.min(prev + (prev < 36 ? 8 : prev < 78 ? 5 : 1), 91);
        const etapaAtual = etapas.find((etapa) => next <= etapa.limit) || etapas[etapas.length - 1];
        setGraphLoadingMessage(etapaAtual.message);
        return next;
      });
    }, 700);

    return () => clearInterval(interval);
  }, [loadingGrafo]);

  const handleAuditoriaAntunes = async () => {
    setAntunesLoading(true);
    setAntunesModalOpen(true);
    setDadosAntunes(null);

    try {
      const response = await fetch(`${API_BASE_URL}/api/llm/auditor-antunes`, {
        method: 'POST',
        headers: { ...API_HEADERS, 'Content-Type': 'application/json' },
        body: JSON.stringify({
          parlamentar: filtros.parlamentar,
          partido: filtros.partido,
          estado: filtros.estado,
          despesa: filtros.despesa,
          ano: filtros.ano,
          orgao_destino: orgaoDestino,
          resumo_gastos: metricasBasicas,
          top_fornecedores: dadosFornecedores,
          notas_atipicas: dadosParlamentar.filter(d => d.valor > (limiteAtipico || 0)),
          todas_notas: dadosParlamentar, // Enviando todas as notas para análise comportamental
          metricas_comparativas: metricasComparativas // Enviando métricas comparativas para o relatório
        })
      });

      if (!response.ok) throw new Error('Erro ao consultar Auditor Antunes');

      const data = await response.json();
      setDadosAntunes(data);
    } catch (err) {
      console.error(err);
      setError('Falha ao acionar Auditor Antunes');
      setAntunesModalOpen(false);
    } finally {
      setAntunesLoading(false);
    }
  };

  const copiarTexto = (texto) => {
    navigator.clipboard.writeText(texto);
    setSnackbarMessage('Texto copiado para a área de transferência!');
    setSnackbarOpen(true);
  };

  const gerarPDF = (titulo, conteudo) => {
    // Implementação simples: abrir nova janela para impressão
    const printWindow = window.open('', '_blank');
    printWindow.document.write(`
        < html >
        <head>
          <title>${titulo}</title>
          <style>
            body { font-family: Arial, sans-serif; padding: 40px; line-height: 1.6; }
            h1 { color: #003366; border-bottom: 2px solid #009739; padding-bottom: 10px; }
            .disclaimer { color: #666; font-size: 12px; margin-top: 50px; border-top: 1px solid #ccc; padding-top: 10px; }
          </style>
        </head>
        <body>
          <h1>${titulo}</h1>
          <div style="white-space: pre-wrap;">${conteudo}</div>
          <div class="disclaimer">
            Gerado por Auditor Antunes IA - Acompanhamento Câmara
          </div>
        </body>
      </html >
  `);
    printWindow.document.close();
    printWindow.print();
  };


  // Carregamento de filtros unificado via FilterSelector
  // Carregamento de filtros unificado via FilterSelector

  const executarAnalise = async () => {
    if (filtros.parlamentar === 'Todos' || filtros.despesa === 'Todos') {
      setError('Selecione o deputado e a despesa para executar a análise.');
      return;
    }

    setLoading(true);
    setProgress(0);
    setError(null);
    setRelatorioAuditoria('');
    setEmailGerado('');

    // Resetar todos os dados anteriores
    setDadosParlamentar([]);
    setMetricasBasicas({});
    setMetricasComparativas({});
    setDadosTemporais([]);
    setDadosFornecedores([]);
    setDadosMapa([]);
    setDadosGrafo(null);
    setLoadingGrafo(false);
    setFiltrosEmpresasGrafo({ estado: 'Todos', cidade: 'Todos' });
    // setInfoParlamentar(null); // Mantido para evitar piscar vazio
    setDadosAntunes(null); // Resetar Antunes também
    setTabAntunes(0);

    try {
      setStatusText('📊 Carregando dados do parlamentar...');
      setProgress(30);

      const response = await fetch(`${API_BASE_URL}/api/gastos/dados-parlamentar?parlamentar=${encodeURIComponent(filtros.parlamentar)}&estado=${filtros.estado}&partido=${filtros.partido}&despesa=${encodeURIComponent(filtros.despesa)}`, { headers: API_HEADERS });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      setProgress(60);
      setStatusText('🔄 Processando dados...');

      const data = await response.json();

      if (!data.success) {
        setError(data.message || 'Nenhum dado encontrado.');
        return;
      }

      setDadosParlamentar(data.dados_completos || []);
      setMetricasBasicas(data.metricas_basicas || {});
      setMetricasComparativas(data.metricas_comparativas || {});
      setLimiteAtipico(data.metricas_basicas?.limite_atipico || 0);
      setDadosTemporais(ordenarSerieTemporal(data.dados_temporais || []));
      setDadosFornecedores(prepararTopFornecedores(data.top_fornecedores || []));
      setDadosMapa(data.dados_mapa || []);
      setDadosMapa(data.dados_mapa || []);
      // Garantir que a rubrica atual e outros dados básicos estejam no infoParlamentar
      setInfoParlamentar({
        ...data.info_parlamentar,
        despesa: filtros.despesa,
        nome: data.info_parlamentar?.nome || filtros.parlamentar,
        partido: data.info_parlamentar?.partido || filtros.partido,
        estado: data.info_parlamentar?.estado || filtros.estado
      });

      console.log('📦 Dados recebidos:', {
        total_registros: data.total_registros,
        dados_temporais: data.dados_temporais?.length,
        top_fornecedores: data.top_fornecedores?.length,
        dados_mapa: data.dados_mapa?.length,
        dados_mapa_detalhes: data.dados_mapa
      });

      setProgress(100);
      setStatusText('✅ Análise concluída!');

      // Carregar o sociograma separadamente para não travar a renderização do restante da página.
      carregarGrafoFornecedores(filtros.parlamentar, filtros.despesa);
      carregarFornecedoresSancionadosCeap(filtros.parlamentar);

    } catch (err) {
      console.warn('⚠️ Endpoint principal falhou, tentando fallback...', err);
      await executarAnaliseFallback();
    } finally {
      setLoading(false);
      setTimeout(() => {
        setProgress(0);
        setStatusText('');
      }, 2000);
    }
  };

  const executarAnaliseFallback = async () => {
    try {
      setLoadingGrafo(false);
      setFiltrosEmpresasGrafo({ estado: 'Todos', cidade: 'Todos' });
      setStatusText('🔄 Executando análise alternativa...');
      setProgress(40);

      const [resRanking, resComparacao, resRubrica] = await Promise.all([
        fetch(`${API_BASE_URL}/api/gastos/ranking?parlamentar=${encodeURIComponent(filtros.parlamentar)}&estado=${filtros.estado}&partido=${filtros.partido}&despesa=${encodeURIComponent(filtros.despesa)}`, { headers: API_HEADERS }),
        fetch(`${API_BASE_URL}/api/comparison/averages?parlamentar=${encodeURIComponent(filtros.parlamentar)}&estado=${filtros.estado}&partido=${filtros.partido}&despesa=${encodeURIComponent(filtros.despesa)}`, { headers: API_HEADERS }),
        fetch(`${API_BASE_URL}/api/gastos/estatisticas-rubrica?despesa=${encodeURIComponent(filtros.despesa)}`, { headers: API_HEADERS })
      ]);

      const notas = await resRanking.json();
      const comparacao = await resComparacao.json();
      const rubrica = await resRubrica.json();

      if (!Array.isArray(notas) || notas.length === 0) {
        throw new Error('Nenhum registro encontrado.');
      }

      setProgress(70);
      setStatusText('🧮 Calculando estatísticas...');

      // Calcular métricas básicas
      const totalGasto = notas.reduce((acc, nota) => acc + (nota.vlrLiquido || 0), 0);
      const numNotas = notas.length;
      const mediaGasto = totalGasto / numNotas;
      const limite = rubrica.limite_atipico || 0;

      // Identificar atípicos
      const notasAtipicas = notas.filter(n => (n.vlrLiquido || 0) > limite);
      const numAtipicos = notasAtipicas.length;

      // Preparar dados temporais
      const dadosTemporaisMap = {};
      notas.forEach(nota => {
        if (nota.datEmissao) {
          const [dia, mes, ano] = nota.datEmissao.split('/');
          const chave = `${mes}/${ano}`;
          dadosTemporaisMap[chave] = (dadosTemporaisMap[chave] || 0) + (nota.vlrLiquido || 0);
        }
      });

      const dadosTemporaisArr = Object.entries(dadosTemporaisMap).map(([periodo, valor]) => ({
        periodo,
        valor
      }));

      // Preparar fornecedores
      const fornecedoresMap = {};
      notas.forEach(nota => {
        const nome = nota.txtFornecedor || 'Desconhecido';
        if (!fornecedoresMap[nome]) {
          fornecedoresMap[nome] = { fornecedor: nome, total: 0, quantidade: 0, media: 0, atipico: false };
        }
        fornecedoresMap[nome].total += (nota.vlrLiquido || 0);
        fornecedoresMap[nome].quantidade += 1;
        if (nota.vlrLiquido > limite) fornecedoresMap[nome].atipico = true;
      });

      const topFornecedores = Object.values(fornecedoresMap)
        .map(f => ({ ...f, media: f.total / f.quantidade }))
        .sort((a, b) => b.total - a.total)
        .slice(0, 10);

      // Preparar mapa
      const fornecedoresComLocal = notas
        .filter(n => n.latitude && n.longitude)
        .map(n => ({
          fornecedor: n.txtFornecedor,
          latitude: n.latitude,
          longitude: n.longitude,
          total: n.vlrLiquido,
          num_notas: 1,
          cidade: n.cidade_fornecedor || 'Desconhecido',
          atipico: n.vlrLiquido > limite,
          descricao: n.txtDescricao
        }));

      // Agrupar fornecedores no mapa para não repetir marcadores
      const mapaAgrupado = {};
      fornecedoresComLocal.forEach(f => {
        const key = `${f.latitude},${f.longitude}`;
        if (!mapaAgrupado[key]) {
          mapaAgrupado[key] = { ...f };
        } else {
          mapaAgrupado[key].total += f.total;
          mapaAgrupado[key].num_notas += 1;
          if (f.atipico) mapaAgrupado[key].atipico = true;
        }
      });

      // Atualizar estados
      setDadosParlamentar(notas.map(n => ({
        data: n.datEmissao,
        fornecedor: n.txtFornecedor,
        descricao: n.txtDescricao,
        valor: n.vlrLiquido,
        estado: n.sgUF,
        url_documento: n.urlDocumento,
        latitude: n.latitude,
        longitude: n.longitude
      })));

      setMetricasBasicas({
        total_gasto: totalGasto,
        num_notas: numNotas,
        media_gasto: mediaGasto,
        num_atipicos: numAtipicos,
        limite_atipico: limite
      });

      setMetricasComparativas({
        media_geral: comparacao.media_geral,
        media_estado: comparacao.media_estado,
        media_partido: comparacao.media_partido,
        diff_geral_pct: ((totalGasto - comparacao.media_geral) / comparacao.media_geral) * 100,
        diff_estado_pct: ((totalGasto - comparacao.media_estado) / comparacao.media_estado) * 100,
        diff_partido_pct: ((totalGasto - comparacao.media_partido) / comparacao.media_partido) * 100
      });

      setLimiteAtipico(limite);
      setDadosTemporais(ordenarSerieTemporal(dadosTemporaisArr));
      setDadosFornecedores(prepararTopFornecedores(Object.values(fornecedoresMap)));
      setDadosMapa(Object.values(mapaAgrupado));

      if (notas.length > 0) {
        setInfoParlamentar({
          nome: filtros.parlamentar,
          partido: filtros.partido,
          estado: filtros.estado,
          foto_url: notas[0].ultimoStatus_urlFoto
        });
      }

      setProgress(100);
      setStatusText('✅ Análise concluída (modo alternativo)!');
      carregarGrafoFornecedores(filtros.parlamentar, filtros.despesa);
      carregarFornecedoresSancionadosCeap(filtros.parlamentar);

    } catch (err) {
      console.error('❌ Erro no fallback:', err);
      setError(`Erro ao executar análise: ${err.message}`);
    }
  };

  const carregarGrafoFornecedores = async (parlamentar, despesa) => {
    if (!parlamentar || !despesa || parlamentar === 'Todos' || despesa === 'Todos') return;

    setLoadingGrafo(true);
    setGraphProgress(8);
    setGraphLoadingElapsed(0);
    setGraphLoadingMessage('Solicitando dados do sociograma ao servidor...');
    setDadosGrafo(null);

    try {
      console.log('🕸️ Buscando sociograma de fornecedores para:', parlamentar, despesa);
      const resGraph = await fetch(`${API_BASE_URL}/api/redes/conexoes-gastos?parlamentar=${encodeURIComponent(parlamentar)}&despesa=${encodeURIComponent(despesa)}`, { headers: API_HEADERS });
      setGraphProgress(96);
      setGraphLoadingMessage('Renderizando nós e conexões do sociograma...');
      const graphData = await resGraph.json();
      console.log('🕸️ Dados do sociograma recebidos:', graphData);
      setDadosGrafo(graphData);
    } catch (e) {
      console.error("❌ Erro ao carregar grafo:", e);
      setDadosGrafo({ nodes: [], links: [], error: true, debug: { msg: 'Erro ao carregar sociograma.', detail: String(e) } });
    } finally {
      setGraphProgress(100);
      setLoadingGrafo(false);
    }
  };

  const gerarRelatorioAuditoria = async () => {
    setLoadingRelatorio(true);
    try {
      const response = await fetch(`${API_BASE_URL}/api/gastos/gerar-auditoria`, {
        method: 'POST',
        headers: { ...API_HEADERS, 'Content-Type': 'application/json' },
        body: JSON.stringify({
          parlamentar: filtros.parlamentar,
          despesa: filtros.despesa,
          estado: filtros.estado,
          partido: filtros.partido,
          metricas: metricasBasicas,
          metricas_comparativas: metricasComparativas,
          top_fornecedores: dadosFornecedores
        })
      });

      const data = await response.json();
      setRelatorioAuditoria(data.relatorio || 'Erro ao gerar relatório');
    } catch (err) {
      console.error('❌ Erro ao gerar relatório:', err);
      setError('Erro ao gerar relatório de auditoria');
    } finally {
      setLoadingRelatorio(false);
    }
  };

  const gerarEmailDenuncia = async () => {
    setLoadingEmail(true);
    try {
      const response = await fetch(`${API_BASE_URL}/api/gastos/gerar-email-denuncia`, {
        method: 'POST',
        headers: { ...API_HEADERS, 'Content-Type': 'application/json' },
        body: JSON.stringify({
          parlamentar: filtros.parlamentar,
          despesa: filtros.despesa,
          estado: filtros.estado,
          partido: filtros.partido,
          relatorio_auditoria: relatorioAuditoria,
          notas_atipicas: dadosParlamentar.filter(d => d.valor > limiteAtipico)
        })
      });

      const data = await response.json();
      setEmailGerado(data.email || 'Erro ao gerar email');
    } catch (err) {
      console.error('❌ Erro ao gerar email:', err);
      setError('Erro ao gerar email de denúncia');
    } finally {
      setLoadingEmail(false);
    }
  };

  const formatarMoeda = (valor) => {
    return new Intl.NumberFormat('pt-BR', {
      style: 'currency',
      currency: 'BRL'
    }).format(valor || 0);
  };

  const formatarData = (data) => {
    if (!data) return '-';
    try {
      if (typeof data === 'string' && data.includes('/')) {
        const parts = data.split('/');
        if (parts.length === 3 && parts[0].length <= 2) {
          return data;
        }
      }
      const date = new Date(data);
      if (isNaN(date.getTime())) return '-';
      return date.toLocaleDateString('pt-BR');
    } catch {
      return '-';
    }
  };

  const getTemporalChartOption = () => {
    if (!dadosTemporais || dadosTemporais.length === 0) return {};

    return {
      title: {
        text: 'Evolução Temporal dos Gastos',
        left: 'center',
        textStyle: { color: CORES_MARCA.azul }
      },
      tooltip: {
        trigger: 'axis',
        formatter: (params) => {
          const param = params[0];
          return `${param.name}<br/>Valor: ${formatarMoeda(param.value)}`;
        }
      },
      xAxis: {
        type: 'category',
        data: dadosTemporais.map(d => d.periodo),
        axisLabel: { rotate: 45 }
      },
      yAxis: {
        type: 'value',
        axisLabel: {
          formatter: (value) => `R$ ${(value / 1000).toFixed(0)}k`
        }
      },
      series: [{
        data: dadosTemporais.map(d => d.valor),
        type: 'line',
        smooth: true,
        itemStyle: { color: CORES_MARCA.azul },
        areaStyle: {
          color: {
            type: 'linear',
            x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: CORES_MARCA.azul + '40' },
              { offset: 1, color: CORES_MARCA.azul + '10' }
            ]
          }
        }
      }]
    };
  };

  const getFornecedoresChartOption = () => {
    if (!dadosFornecedores || dadosFornecedores.length === 0) return {};

    const coresFatias = [
      CORES_MARCA.azul,
      CORES_MARCA.verde,
      CORES_MARCA.amarelo,
      CORES_MARCA.laranjaEscuro,
      CORES_MARCA.azulClaro
    ];

    return {
      title: {
        text: 'Top 5 Fornecedores (demais agrupados em "Outros")',
        left: 'center',
        top: 10,
        textStyle: { color: CORES_MARCA.azul, fontWeight: 'bold' }
      },
      tooltip: {
        trigger: 'item',
        formatter: ({ name, value, percent }) =>
          `${name}<br/>Total: ${formatarMoeda(value)}<br/>Participação: ${percent?.toFixed?.(1) ?? percent}%`
      },
      legend: {
        orient: 'horizontal',
        bottom: 0,
        textStyle: { color: CORES_MARCA.cinza }
      },
      series: [
        {
          name: 'Fornecedores',
          type: 'pie',
          radius: ['40%', '70%'],
          center: ['50%', '50%'],
          avoidLabelOverlap: true,
          itemStyle: {
            borderRadius: 8,
            borderColor: CORES_MARCA.branco,
            borderWidth: 2
          },
          label: {
            show: false,
            position: 'center'
          },
          emphasis: {
            label: {
              show: true,
              fontSize: 18,
              fontWeight: 'bold',
              formatter: ({ name, value, percent }) =>
                `${name}\n${formatarMoeda(value)}\n(${percent?.toFixed?.(1) ?? percent}%)`
            }
          },
          labelLine: {
            show: false
          },
          data: dadosFornecedores.map((f, index) => ({
            value: f.total,
            name: f.fornecedor,
            itemStyle: {
              color: coresFatias[index % coresFatias.length]
            }
          }))
        }
      ]
    };
  };

  const handleAnalyzeLLM = async () => {
    if (!filtros.parlamentar || filtros.parlamentar === 'Todos') return;
    setLlmLoading(true);
    setLlmResult(null);
    try {
      const response = await fetch(`${API_BASE_URL}/api/gastos/analise-llm`, {
        method: 'POST',
        headers: { ...API_HEADERS, 'Content-Type': 'application/json' },
        body: JSON.stringify({
          parlamentar: filtros.parlamentar,
          estado: filtros.estado,
          partido: filtros.partido,
          despesa: filtros.despesa
        })
      });
      const data = await response.json();
      if (!response.ok || data.error) {
         setLlmResult(`Erro: ${data.error || 'Falha ao processar análise.'}`);
      } else {
         setLlmResult(data.analise || 'Nenhuma análise gerada.');
      }
    } catch (error) {
      console.error("Erro ao gerar análise IA:", error);
      setLlmResult("Erro ao gerar análise. Tente novamente.");
    } finally {
      setLlmLoading(false);
    }
  };

  const [badges, setBadges] = useState({});

  useEffect(() => {
    // Usar dados locais como fallback para o servidor remoto
    setBadges(badgesData);

    // Tentar buscar do servidor (opcional, se implementado no futuro)
    /*
    fetch(`${API_BASE_URL}/api/badges`)
      .then(res => res.json())
      .then(data => setBadges(data))
      .catch(err => console.error('Erro ao carregar badges:', err));
    */
  }, []);

  const getBadgeForCurrentView = () => {
    if (!infoParlamentar || !badges[infoParlamentar.nome]) return null;

    const userBadges = badges[infoParlamentar.nome];
    // Tenta encontrar um badge para a categoria atual ou o badge TOTAL se estiver vendo "Todos"
    return userBadges.find(b =>
      b.categoria === filtros.despesa ||
      (filtros.despesa === 'Todos' && b.categoria === 'TOTAL')
    );
  };

  const currentBadge = getBadgeForCurrentView();

  const SpinnerIcon = () => (
    <CircularProgress size={18} thickness={4} sx={{ mr: 1, color: 'inherit', opacity: 0.6 }} />
  );

  return (
    <Container maxWidth="xl" sx={{ py: 4 }}>
      <Box sx={{ mb: 4, backgroundColor: 'white', p: 3, borderRadius: '16px', display: 'flex', alignItems: 'center', gap: 4 }}>
        <Box sx={{ flex: 1 }}>
          <Typography variant="h4" sx={{ fontWeight: 'bold', color: CORES_MARCA.azul }}>
            🎯 Detalhamento de Gastos Parlamentares
          </Typography>
          <Typography variant="body1" sx={{ color: CORES_MARCA.cinza }}>
            Análise detalhada por fornecedor, rubrica e geolocalização dos gastos parlamentares.
          </Typography>
        </Box>
        <Box
          component="img"
          src="/detalhamento_gastos.png"
          alt="Ilustração Detalhamento de Gastos"
          sx={{
            maxHeight: '220px',
            width: 'auto',
            borderRadius: '8px',
            display: { xs: 'none', md: 'block' }
          }}
        />
      </Box>
      {/* Filtros Unificados */}
      <FilterSelector
        onFiltersChange={setFiltros}
        fields={['estado', 'partido', 'parlamentar', 'despesa']}
        useCurrentParty={true}
        requireSelection={true}
        requireAll={true}
      />

      <Box sx={{ mb: 4, display: 'flex', justifyContent: 'center' }}>
        <Button
          variant="contained"
          size="large"
          onClick={executarAnalise}
          disabled={loading || (filtros.estado === 'Todos' && filtros.partido === 'Todos' && filtros.parlamentar === 'Todos')}
          startIcon={loading ? <CircularProgress size={20} color="inherit" /> : <SearchIcon />}
          sx={{
            backgroundColor: CORES_MARCA.verde,
            '&:hover': { backgroundColor: '#007a2d' },
            borderRadius: '50px',
            px: 6,
            py: 1.5,
            fontWeight: 'bold',
            fontSize: '1.1rem'
          }}
        >
          {loading ? 'Analisando...' : 'Executar Análise'}
        </Button>
      </Box>

        {/* Snackbar para feedback */}
        <Snackbar
          open={snackbarOpen}
          autoHideDuration={3000}
          onClose={() => setSnackbarOpen(false)}
          message={snackbarMessage}
        />

        {loading && (
          <Box sx={{ mt: 2 }}>
            <LinearProgress variant="determinate" value={progress} />
            <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
              {statusText}
            </Typography>
          </Box>
        )}

        {error && (
          <Alert severity="error" sx={{ mt: 2 }}>{error}</Alert>
        )}

      {/* Resultados */}
      {
        metricasBasicas && Object.keys(metricasBasicas).length > 0 && (
          <>
            {/* Informações do Parlamentar (Modelo Limpo) */}
            {infoParlamentar && (
              <Paper
                sx={{
                  p: { xs: 3, md: 4 },
                  mb: 3,
                  borderRadius: '20px',
                  bgcolor: '#FFFFFF',
                  color: CORES_MARCA.azul,
                  boxShadow: '0 8px 18px rgba(15, 23, 42, 0.12)',
                  border: '1px solid rgba(15, 23, 42, 0.08)'
                }}
              >
                <Grid container spacing={3} alignItems="center">
                  <Grid item xs={12} md={3} sx={{ display: 'flex', justifyContent: 'center' }}>
                    {infoParlamentar.foto_url && (
                      <Box sx={{ bgcolor: 'white', borderRadius: '50%', p: 0.5, width: 180, height: 180, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                        <Avatar
                          src={infoParlamentar.foto_url}
                          sx={{ width: 172, height: 172, border: `4px solid ${CORES_MARCA.verde}` }}
                        />
                      </Box>
                    )}
                  </Grid>

                  <Grid item xs={12} md={6}>
                    <Typography
                      variant="h3"
                      sx={{
                        fontWeight: 900,
                        color: CORES_MARCA.azul,
                        mb: 2,
                        lineHeight: 1.05,
                        letterSpacing: '-0.02em'
                      }}
                    >
                      {infoParlamentar.nome || 'N/A'}
                    </Typography>
                    <Box sx={{ display: 'flex', gap: 1.5, flexWrap: 'wrap' }}>
                      <Chip
                        label={infoParlamentar.partido || 'N/A'}
                        sx={{
                          backgroundColor: '#E8F5E9',
                          color: CORES_MARCA.verde,
                          fontWeight: 800,
                          fontSize: '0.95rem',
                          px: 1
                        }}
                      />
                      <Chip
                        label={infoParlamentar.estado || 'N/A'}
                        sx={{
                          backgroundColor: '#E3F2FD',
                          color: CORES_MARCA.azul,
                          fontWeight: 800,
                          fontSize: '0.95rem',
                          px: 1
                        }}
                      />
                    </Box>
                    <Typography variant="body1" sx={{ mt: 2.5, color: '#4B5563', fontSize: '1.1rem', fontWeight: 500 }}>
                      Análise de Rubrica: {formatarNomeDespesa(infoParlamentar.despesa || filtros.despesa || 'N/A')}
                    </Typography>
                  </Grid>

                  <Grid item xs={12} md={3} sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center' }}>
                    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2, alignItems: 'center' }}>
                      {getPartidoLogo(infoParlamentar) && (
                        <Box sx={{ bgcolor: 'white', borderRadius: '50%', p: 2, width: 132, height: 132, display: 'flex', alignItems: 'center', justifyContent: 'center', border: '1px solid rgba(15,23,42,0.08)' }}>
                          <Box
                            component="img"
                            src={proxyImg(getPartidoLogo(infoParlamentar))}
                            onError={(event) => handlePartidoLogoError(event, infoParlamentar)}
                            sx={{ maxWidth: '100%', maxHeight: '100%', display: 'block', objectFit: 'contain' }}
                          />
                        </Box>
                      )}
                      {getEstadoLogo(infoParlamentar) && (
                        <Box sx={{ bgcolor: 'white', borderRadius: '50%', p: 2, width: 132, height: 132, display: 'flex', alignItems: 'center', justifyContent: 'center', border: '1px solid rgba(15,23,42,0.08)' }}>
                          <Box
                            component="img"
                            src={proxyImg(getEstadoLogo(infoParlamentar))}
                            onError={(event) => handleEstadoLogoError(event, infoParlamentar)}
                            sx={{ maxWidth: '100%', maxHeight: '100%', display: 'block', objectFit: 'contain' }}
                          />
                        </Box>
                      )}
                      {currentBadge && (
                        <Tooltip title={currentBadge.titulo} arrow>
                          <Box
                            sx={{
                              width: 76,
                              height: 76,
                              borderRadius: '50%',
                              backgroundColor: '#FFFFFF',
                              border: '2px solid #FFD700',
                              p: 0.5,
                              '&:hover': { transform: 'scale(1.08)', transition: '0.2s' }
                            }}
                          >
                            <Box
                              component="img"
                              src={`/badges/${currentBadge.icone}.png`}
                              alt={currentBadge.titulo}
                              sx={{ width: '100%', height: '100%', objectFit: 'contain' }}
                            />
                          </Box>
                        </Tooltip>
                      )}
                    </Box>
                  </Grid>
                </Grid>
              </Paper>
            )}

            {/* Métricas Básicas */}
            <Typography variant="h5" gutterBottom sx={{ mb: 2, fontWeight: 'bold', color: CORES_MARCA.azul }}>
              Métricas Básicas
            </Typography>

            <Grid container spacing={3} sx={{ mb: 4 }} alignItems="stretch">
              <Grid item xs={12} sm={6} md={3}>
                <Card sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
                  <CardContent sx={{ flexGrow: 1 }}>
                    <Typography color="text.secondary" gutterBottom>
                      💰 Total Gasto
                    </Typography>
                    <Typography variant="h5" fontWeight="bold">
                      {formatarMoeda(metricasBasicas.total_gasto)}
                    </Typography>
                  </CardContent>
                </Card>
              </Grid>

              <Grid item xs={12} sm={6} md={3}>
                <Card sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
                  <CardContent sx={{ flexGrow: 1 }}>
                    <Typography color="text.secondary" gutterBottom>
                      📄 Total de Despesas
                    </Typography>
                    <Typography variant="h5" fontWeight="bold">
                      {metricasBasicas.num_notas || 0}
                    </Typography>
                  </CardContent>
                </Card>
              </Grid>

              <Grid item xs={12} sm={6} md={3}>
                <Card sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
                  <CardContent sx={{ flexGrow: 1 }}>
                    <Typography color="text.secondary" gutterBottom>
                      📊 Média por Despesa
                    </Typography>
                    <Typography variant="h5" fontWeight="bold">
                      {formatarMoeda(metricasBasicas.media_gasto)}
                    </Typography>
                  </CardContent>
                </Card>
              </Grid>

              <Grid item xs={12} sm={6} md={3}>
                <Card sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
                  <CardContent sx={{ flexGrow: 1 }}>
                    <Typography color="text.secondary" gutterBottom>
                      ⚠️ Despesas Atípicas
                    </Typography>
                    <Typography variant="h5" fontWeight="bold" color="error">
                      {metricasBasicas.num_atipicos || 0}
                    </Typography>
                  </CardContent>
                </Card>
              </Grid>
            </Grid>

            <Typography variant="body2" color="text.secondary" sx={{ mb: 4 }}>
              Limite Atípico: {formatarMoeda(limiteAtipico)}
            </Typography>

            {/* Métricas Comparativas */}
            {metricasComparativas && Object.keys(metricasComparativas).length > 0 && (
              <>
                <Divider sx={{ my: 4 }} />
                <Typography variant="h5" gutterBottom sx={{ mb: 3, fontWeight: 'bold', color: CORES_MARCA.azul }}>
                  📊 Análise Comparativa com Referências
                </Typography>
                <Alert severity="info" sx={{ mb: 3 }}>
                  💡 <strong>O que observar:</strong> Compare os gastos do parlamentar com médias de referência para identificar padrões atípicos.
                </Alert>

                <Grid container spacing={3} sx={{ mb: 4 }} alignItems="stretch">
                  <Grid item xs={12} sm={6} md={3}>
                    <Card sx={{ bgcolor: CORES_MARCA.azulClaro, height: '100%', display: 'flex', flexDirection: 'column' }}>
                      <CardContent sx={{ flexGrow: 1 }}>
                        <Typography sx={{ color: CORES_MARCA.branco }} gutterBottom variant="body2">
                          💰 Gasto do Parlamentar
                        </Typography>
                        <Typography variant="h5" fontWeight="bold" sx={{ color: CORES_MARCA.branco }}>
                          {formatarMoeda(metricasBasicas.total_gasto)}
                        </Typography>
                      </CardContent>
                    </Card>
                  </Grid>

                  <Grid item xs={12} sm={6} md={3}>
                    <Card sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
                      <CardContent sx={{ flexGrow: 1 }}>
                        <Typography color="text.secondary" gutterBottom variant="body2">
                          📊 vs Média Geral
                        </Typography>
                        <Typography
                          variant="h5"
                          fontWeight="bold"
                          color={metricasComparativas.diff_geral_pct > 0 ? 'error' : 'success'}
                        >
                          {metricasComparativas.diff_geral_pct > 0 ? '+' : ''}
                          {metricasComparativas.diff_geral_pct?.toFixed(2)}%
                        </Typography>
                        <Typography variant="caption" color="text.secondary">
                          Média: {formatarMoeda(metricasComparativas.media_geral)}
                        </Typography>
                      </CardContent>
                    </Card>
                  </Grid>

                  <Grid item xs={12} sm={6} md={3}>
                    <Card sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
                      <CardContent sx={{ flexGrow: 1 }}>
                        <Typography color="text.secondary" gutterBottom variant="body2">
                          📍 vs Média do Estado
                        </Typography>
                        <Typography
                          variant="h5"
                          fontWeight="bold"
                          color={metricasComparativas.diff_estado_pct > 0 ? 'error' : 'success'}
                        >
                          {metricasComparativas.diff_estado_pct > 0 ? '+' : ''}
                          {metricasComparativas.diff_estado_pct?.toFixed(2)}%
                        </Typography>
                        <Typography variant="caption" color="text.secondary">
                          Média: {formatarMoeda(metricasComparativas.media_estado)}
                        </Typography>
                      </CardContent>
                    </Card>
                  </Grid>

                  <Grid item xs={12} sm={6} md={3}>
                    <Card sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
                      <CardContent sx={{ flexGrow: 1 }}>
                        <Typography color="text.secondary" gutterBottom variant="body2">
                          🏛️ vs Média do Partido
                        </Typography>
                        <Typography
                          variant="h5"
                          fontWeight="bold"
                          color={metricasComparativas.diff_partido_pct > 0 ? 'error' : 'success'}
                        >
                          {metricasComparativas.diff_partido_pct > 0 ? '+' : ''}
                          {metricasComparativas.diff_partido_pct?.toFixed(2)}%
                        </Typography>
                        <Typography variant="caption" color="text.secondary">
                          Média: {formatarMoeda(metricasComparativas.media_partido)}
                        </Typography>
                      </CardContent>
                    </Card>
                  </Grid>
                </Grid>
              </>
            )}

            <Divider sx={{ my: 4 }} />

            {/* Gráfico Temporal */}
            {dadosTemporais && dadosTemporais.length > 0 && (
              <Paper sx={{ p: 3, mb: 4 }}>
                <ReactECharts
                  option={getTemporalChartOption()}
                  style={{ height: '400px' }}
                />
              </Paper>
            )}

            {/* Gráfico de Fornecedores */}
            {dadosFornecedores && dadosFornecedores.length > 0 && (
              <Paper sx={{ p: 3, mb: 4 }}>
                <ReactECharts
                  option={getFornecedoresChartOption()}
                  style={{ height: '500px' }}
                />
              </Paper>
            )}



            {/* Mapa de Fornecedores */}
            {dadosMapa && dadosMapa.length > 0 && (
              <Paper sx={{ p: 3, mb: 4 }}>
                <Typography variant="h6" gutterBottom sx={{ display: 'flex', alignItems: 'center', gap: 1, color: CORES_MARCA.azul }}>
                  <LocationOnIcon sx={{ color: CORES_MARCA.verde }} />
                  🗺️ Mapa de Fornecedores ({dadosMapa.length} fornecedores)
                </Typography>

                <Grid container spacing={2} sx={{ mb: 2 }}>
                  <Grid item xs={12} sm={4}>
                    <Card>
                      <CardContent>
                        <Typography variant="body2" color="text.secondary">
                          🏢 Total de Fornecedores
                        </Typography>
                        <Typography variant="h6" fontWeight="bold">
                          {dadosMapa.length}
                        </Typography>
                      </CardContent>
                    </Card>
                  </Grid>
                  <Grid item xs={12} sm={4}>
                    <Card>
                      <CardContent>
                        <Typography variant="body2" color="text.secondary">
                          🔵 Fornecedores Normais
                        </Typography>
                        <Typography variant="h6" fontWeight="bold">
                          {dadosMapa.filter(f => !f.atipico).length}
                        </Typography>
                      </CardContent>
                    </Card>
                  </Grid>
                  <Grid item xs={12} sm={4}>
                    <Card>
                      <CardContent>
                        <Typography variant="body2" color="text.secondary">
                          🔴 Fornecedores Atípicos
                        </Typography>
                        <Typography variant="h6" fontWeight="bold" color="error">
                          {dadosMapa.filter(f => f.atipico).length}
                        </Typography>
                      </CardContent>
                    </Card>
                  </Grid>
                </Grid>

                <Alert severity="info" sx={{ mb: 2 }}>
                  🗺️ <strong>Como usar o mapa:</strong> Clique nos marcadores para ver detalhes dos fornecedores. Marcadores verdes = normais, laranjas = atípicos.
                </Alert>

                <Box sx={{ height: 500, width: '100%', borderRadius: 2, overflow: 'hidden' }}>
                  <MapaFornecedores fornecedores={dadosMapa} formatarMoeda={formatarMoeda} />
                </Box>
              </Paper>
            )}

            {/* Grafo de Rede de Fornecedores (Sociograma) */}
            <Paper sx={{ p: 3, mb: 4, bgcolor: '#fcfcfc' }}>
              <Typography variant="h6" gutterBottom sx={{ display: 'flex', alignItems: 'center', gap: 1, color: CORES_MARCA.azul }}>
                <AutoAwesomeIcon sx={{ color: CORES_MARCA.laranjaEscuro }} />
                Rede de Conexões e Influência (Sociograma)
              </Typography>
              <Alert severity="info" sx={{ mb: 2 }}>
                🕸️ <strong>Análise de Rede:</strong> Visualize quais outros parlamentares também contratam os mesmos top fornecedores deste deputado.
              </Alert>
              {(estadosEmpresasNoGrafo.length > 0 || cidadesEmpresasNoGrafo.length > 0) && (
                <Grid container spacing={2} sx={{ mb: 2 }}>
                  <Grid item xs={12} md={6}>
                    <FormControl fullWidth>
                      <InputLabel>🏢 Estado das Empresas no Grafo</InputLabel>
                      <Select
                        value={filtrosEmpresasGrafo.estado}
                        label="🏢 Estado das Empresas no Grafo"
                        disabled={loadingGrafo}
                        IconComponent={loadingGrafo ? SpinnerIcon : undefined}
                        onChange={(e) => {
                          const novoEstado = e.target.value;
                          setFiltrosEmpresasGrafo((prev) => ({
                            ...prev,
                            estado: novoEstado,
                            cidade: 'Todos',
                          }));
                        }}
                      >
                        <MenuItem value="Todos">Todos</MenuItem>
                        {estadosEmpresasNoGrafo.map((estado) => (
                          <MenuItem key={estado} value={estado}>{estado}</MenuItem>
                        ))}
                      </Select>
                    </FormControl>
                  </Grid>
                  <Grid item xs={12} md={6}>
                    <FormControl fullWidth disabled={cidadesEmpresasNoGrafo.length === 0 || loadingGrafo}>
                      <InputLabel>🏙️ Cidade das Empresas no Grafo</InputLabel>
                      <Select
                        value={filtrosEmpresasGrafo.cidade}
                        label="🏙️ Cidade das Empresas no Grafo"
                        disabled={cidadesEmpresasNoGrafo.length === 0 || loadingGrafo}
                        IconComponent={loadingGrafo ? SpinnerIcon : undefined}
                        onChange={(e) => {
                          const novaCidade = e.target.value;
                          setFiltrosEmpresasGrafo((prev) => ({
                            ...prev,
                            cidade: novaCidade,
                          }));
                        }}
                      >
                        <MenuItem value="Todos">Todos</MenuItem>
                        {cidadesEmpresasNoGrafo.map((cidade) => (
                          <MenuItem key={cidade} value={cidade}>{cidade}</MenuItem>
                        ))}
                      </Select>
                    </FormControl>
                  </Grid>
                </Grid>
              )}
              <RedeFornecedoresGraph
                data={dadosGrafoFiltrados}
                loading={loadingGrafo}
                parlamentarNome={filtros.parlamentar}
                loadingProgress={graphProgress}
                loadingMessage={graphLoadingMessage}
                loadingElapsed={graphLoadingElapsed}
              />
            </Paper>

            {/* Fornecedores da Cota Parlamentar (CEAP) sancionados no CEIS/CEPIM */}
            {filtros.parlamentar !== 'Todos' && (
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
                    <GppBadIcon sx={{ fontSize: 32, color: '#B91C1C' }} />
                    <Typography variant="h5" sx={{ fontWeight: 'bold', color: '#003366' }}>
                      Fornecedores da Cota Parlamentar Sancionados (CEIS/CEPIM)
                    </Typography>
                  </Box>
                  <Typography variant="body2" sx={{ color: '#666' }}>
                    Cruzamento entre os fornecedores pagos com a <strong>Cota para Exercício da Atividade Parlamentar (CEAP)</strong> de{' '}
                    {filtros.parlamentar} e as bases de sanções da própria <strong>CGU</strong> — <strong>CEIS</strong> (empresas
                    inidôneas/suspensas) e <strong>CEPIM</strong> (ONGs impedidas de convênio).
                  </Typography>
                  <Alert severity="warning" variant="outlined" sx={{ mt: 2, borderRadius: '12px' }}>
                    <strong>Importante:</strong> gasto de CEAP é ressarcimento, não licitação — não há obrigação legal de o
                    parlamentar consultar o CEIS/CEPIM antes de escolher esse fornecedor (diferente de emendas/convênios, onde
                    a consulta é exigida do órgão público). Isto <strong>não é acusação de irregularidade</strong>, é um alerta
                    de transparência para avaliação pública.
                  </Alert>
                </Box>

                {ceapSancionadosLoading ? (
                  <Box sx={{ display: 'flex', justifyContent: 'center', py: 6 }}>
                    <CircularProgress size={40} thickness={4} />
                  </Box>
                ) : ceapSancionadosAviso ? (
                  <Box sx={{ p: 4, pt: 0 }}>
                    <Alert severity="info" sx={{ borderRadius: '12px' }}>{ceapSancionadosAviso}</Alert>
                  </Box>
                ) : ceapSancionadosData.fornecedores.length === 0 ? (
                  <Box sx={{ px: 4, pb: 4, display: 'flex', alignItems: 'center', gap: 1.5 }}>
                    <VerifiedUserIcon sx={{ color: '#2e7d32' }} />
                    <Typography variant="body1" sx={{ color: '#666' }}>
                      Nenhum fornecedor da cota parlamentar de {filtros.parlamentar} consta no CEIS/CEPIM.
                    </Typography>
                  </Box>
                ) : (
                  <Box sx={{ px: 2, pb: 2 }}>
                    <Stack direction="row" spacing={2} sx={{ px: 2, mb: 2 }}>
                      <Chip label={`${ceapSancionadosData.resumo.total_fornecedores_sancionados} fornecedores sancionados`} sx={{ fontWeight: 'bold' }} />
                      <Chip
                        label={`Total pago: ${(ceapSancionadosData.resumo.valor_total || 0).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })}`}
                        variant="outlined"
                      />
                    </Stack>
                    <TableContainer component={Box}>
                      <Table>
                        <TableHead sx={{ bgcolor: '#FDFDFD' }}>
                          <TableRow>
                            <TableCell sx={{ fontWeight: 'bold', color: '#003366' }}>Base</TableCell>
                            <TableCell sx={{ fontWeight: 'bold', color: '#003366' }}>Fornecedor</TableCell>
                            <TableCell sx={{ fontWeight: 'bold', color: '#003366' }}>CNPJ</TableCell>
                            <TableCell sx={{ fontWeight: 'bold', color: '#003366' }} align="right">Total Pago (CEAP)</TableCell>
                            <TableCell sx={{ fontWeight: 'bold', color: '#003366' }}>Período das Notas</TableCell>
                            <TableCell sx={{ fontWeight: 'bold', color: '#003366' }}>Período da Sanção</TableCell>
                          </TableRow>
                        </TableHead>
                        <TableBody>
                          {ceapSancionadosData.fornecedores.map((f, idx) => (
                            <TableRow key={idx} sx={{ '&:hover': { bgcolor: '#F1F5F9' } }}>
                              <TableCell>
                                <Chip
                                  size="small"
                                  label={f.sancao_base}
                                  sx={{
                                    fontWeight: 'bold',
                                    bgcolor: f.sancao_base === 'CEIS' ? '#FEF2F2' : '#FFFBEB',
                                    color: f.sancao_base === 'CEIS' ? '#B91C1C' : '#92400E'
                                  }}
                                />
                              </TableCell>
                              <TableCell>
                                <Typography variant="body2" sx={{ fontWeight: 'bold' }}>{f.fornecedor}</Typography>
                                <Typography variant="caption" color="text.secondary">{f.sancao_categoria}</Typography>
                              </TableCell>
                              <TableCell><Typography variant="body2">{f.cnpj}</Typography></TableCell>
                              <TableCell align="right">
                                <Typography variant="body2" sx={{ fontWeight: 'bold' }}>
                                  {(f.total_gasto || 0).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })}
                                </Typography>
                                <Typography variant="caption" color="text.secondary">{f.n_notas} nota(s)</Typography>
                              </TableCell>
                              <TableCell>
                                <Typography variant="body2">{f.primeira_nota || '—'} a {f.ultima_nota || '—'}</Typography>
                              </TableCell>
                              <TableCell>
                                <Typography variant="body2">
                                  {f.sancao_inicio || '—'} {f.sancao_fim ? `até ${f.sancao_fim}` : '(vigente)'}
                                </Typography>
                              </TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    </TableContainer>
                    <Typography variant="caption" sx={{ display: 'block', px: 2, pt: 2, color: '#999' }}>
                      {ceapSancionadosData.disclaimer}
                    </Typography>
                  </Box>
                )}
              </Paper>
            )}

            {/* Botão Auditoria Antunes (Entre Mapa e Relatório) */}
            <Box sx={{ my: 4 }}>
              <Button
                variant="contained"
                size="large"
                fullWidth
                onClick={handleAuditoriaAntunes}
                disabled={antunesLoading || !dadosParlamentar.length}
                startIcon={
                  antunesLoading ? (
                    <CircularProgress size={30} color="inherit" />
                  ) : (
                    <Box
                      component="img"
                      src="/expressions/antunes_angry.png"
                      alt="Robô Antunes Bravo"
                      sx={{
                        height: 100,
                        width: 100,
                        borderRadius: '50%',
                        border: '4px solid #FFF',
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
                  bgcolor: CORES_MARCA.azul,
                  '&:hover': { bgcolor: CORES_MARCA.azulClaro },
                  py: 3,
                  px: 4,
                  fontSize: '1.2rem',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'flex-start',
                  textAlign: 'left',
                  borderRadius: 4,
                  boxShadow: 3
                }}
              >
                {antunesLoading
                  ? 'O Robô Antunes está auditando...'
                  : `Acione o Robo Antunes para auditar a prestação de contas do deputado ${infoParlamentar?.nome || filtros.parlamentar || '...'} na rubrica ${infoParlamentar?.despesa ? formatarNomeDespesa(infoParlamentar.despesa) : (filtros.despesa !== 'Todos' ? formatarNomeDespesa(filtros.despesa) : 'todas as rubricas')}`
                }
              </Button>
            </Box>

            {/* Relatório de Auditoria - Auditor Antunes (Estilo Azul) */}
            {(dadosAntunes || antunesLoading) && (
              <Paper
                elevation={3}
                sx={{
                  mt: 4,
                  mb: 4,
                  overflow: 'hidden',
                  border: '1px solid #e0e0e0',
                  borderRadius: 2
                }}
              >
                {/* Cabeçalho do Card */}
                <Box sx={{ bgcolor: '#FFF', p: 2, display: 'flex', alignItems: 'center', gap: 2, borderBottom: '1px solid #e0e0e0' }}>
                  <AutoAwesomeIcon sx={{ color: CORES_MARCA.azul }} />
                  <Typography variant="h6" fontWeight="bold" color="text.primary">
                    Relatório de Auditoria - Auditor Antunes
                  </Typography>
                  {dadosAntunes && (
                    <IconButton onClick={() => setDadosAntunes(null)} sx={{ ml: 'auto' }}>
                      <CloseIcon />
                    </IconButton>
                  )}
                </Box>

                {/* Conteúdo do Card */}
                <CardContent>
                  {antunesLoading ? (
                    <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', py: 8 }}>
                      <Box sx={{ width: '100%', maxWidth: 600, mb: 4 }}>
                        <LinearProgress variant="determinate" value={progressValue} sx={{ height: 10, borderRadius: 5, bgcolor: '#e0e0e0', '& .MuiLinearProgress-bar': { bgcolor: CORES_MARCA.azul } }} />
                      </Box>
                      <Typography variant="h6" color="text.secondary" gutterBottom>
                        O Auditor Antunes está analisando as contas...
                      </Typography>
                      <Typography variant="body2" color="text.secondary" sx={{ fontStyle: 'italic', animation: 'fadeIn 1s infinite alternate', minHeight: '24px' }}>
                        "{progressMessage}"
                      </Typography>
                    </Box>
                  ) : (
                    <Box sx={{ width: '100%', mt: -2 }}>
                      <Tabs
                        value={tabAntunes}
                        onChange={(e, v) => setTabAntunes(v)}
                        variant="fullWidth"
                        sx={{ mb: 3, borderBottom: 1, borderColor: 'divider' }}
                      >
                        <Tab label="✉️ E-mail de Cobrança (Deputado)" />
                        <Tab label="⚖️ E-mail de Denúncia (Órgãos)" />
                      </Tabs>

                      <Box sx={{
                        p: 3,
                        bgcolor: '#f8f9fa',
                        borderRadius: 2,
                        minHeight: '400px',
                        border: '1px solid #e0e0e0',
                        fontFamily: '"Roboto Mono", monospace',
                        fontSize: '0.9rem',
                        whiteSpace: 'pre-wrap',
                        color: '#333',
                        textAlign: 'left'
                      }}>
                        {tabAntunes === 0 ? (
                          <>
                            <Typography variant="subtitle2" gutterBottom sx={{ fontWeight: 'bold', color: '#003366' }}>
                              Assunto: {dadosAntunes.email_corpo && typeof dadosAntunes.email_corpo === 'object' ? dadosAntunes.email_corpo.assunto : (dadosAntunes.email_assunto || 'Solicitação de Esclarecimentos')}
                            </Typography>
                            <Divider sx={{ mb: 2 }} />
                            {dadosAntunes.email_corpo && typeof dadosAntunes.email_corpo === 'object' ? dadosAntunes.email_corpo.texto : dadosAntunes.email_corpo}
                          </>
                        ) : (
                          <>
                            {!dadosAntunes.email_corpo ? (
                              <Box sx={{ p: 4, textAlign: 'center', color: '#666' }}>
                                <Typography variant="h6" gutterBottom>
                                  ✅ Nenhuma pendência encontrada
                                </Typography>
                                <Typography variant="body2">
                                  O Protocolo Antunes não identificou irregularidades graves que justifiquem o envio de ofício neste momento.
                                </Typography>
                              </Box>
                            ) : (
                              <>
                                <Box sx={{ mb: 2, p: 2, bgcolor: '#e3f2fd', borderRadius: 1 }}>
                                  <FormControl component="fieldset">
                                    <Typography variant="caption" sx={{ color: '#666', mb: 1, display: 'block' }}>
                                      Selecione o órgão de destino:
                                    </Typography>
                                    <RadioGroup
                                      row
                                      value={orgaoDestino}
                                      onChange={(e) => setOrgaoDestino(e.target.value)}
                                    >
                                      <FormControlLabel value="TCU" control={<Radio size="small" />} label="TCU" />
                                      <FormControlLabel value="MPF" control={<Radio size="small" />} label="MPF" />
                                      <FormControlLabel value="Corregedoria" control={<Radio size="small" />} label="Corregedoria" />
                                    </RadioGroup>
                                  </FormControl>
                                </Box>
                                <Typography variant="body2" sx={{ fontWeight: 'bold', mb: 2 }}>
                                  {orgaoDestino === 'TCU' && "À Ouvidoria do Tribunal de Contas da União (TCU),"}
                                  {orgaoDestino === 'MPF' && "Ao Ministério Público Federal (MPF),"}
                                  {orgaoDestino === 'Corregedoria' && "À Corregedoria Parlamentar da Câmara dos Deputados,"}
                                </Typography>
                                <ReactMarkdown>
                                  {dadosAntunes.relatorio_tecnico && typeof dadosAntunes.relatorio_tecnico === 'object'
                                    ? JSON.stringify(dadosAntunes.relatorio_tecnico, null, 2)
                                    : (dadosAntunes.relatorio_tecnico || '')}
                                </ReactMarkdown>
                              </>
                            )}
                          </>
                        )}
                      </Box>

                      {/* Ações e Contatos */}
                      <Grid container spacing={3} sx={{ mt: 2 }}>
                        <Grid item xs={12} md={8}>
                          <Box sx={{ p: 2, border: '1px solid #e0e0e0', borderRadius: 2, bgcolor: '#fff', textAlign: 'left' }}>
                            <Typography variant="subtitle2" gutterBottom sx={{ fontWeight: 'bold', color: '#003366', display: 'flex', alignItems: 'center', gap: 1 }}>
                              <EmailIcon fontSize="small" /> Contatos para Envio
                            </Typography>
                            <Grid container spacing={2}>
                              <Grid item xs={6}>
                                <Typography variant="caption" display="block"><strong>Deputado:</strong> {dadosAntunes?.contatos?.deputado || 'Não informado'}</Typography>
                                <Typography variant="caption" display="block"><strong>Corregedoria:</strong> {dadosAntunes?.contatos?.corregedoria_camara || 'corregedoria@camara.leg.br'}</Typography>
                              </Grid>
                              <Grid item xs={6}>
                                <Typography variant="caption" display="block"><strong>TCU:</strong> {dadosAntunes?.contatos?.tcu || 'ouvidoria@tcu.gov.br'}</Typography>
                                <Typography variant="caption" display="block"><strong>MPF:</strong> {dadosAntunes?.contatos?.mpf || 'pgr.mpf.mp.br'}</Typography>
                              </Grid>
                            </Grid>
                          </Box>
                        </Grid>
                        <Grid item xs={12} md={4} sx={{ display: 'flex', flexDirection: 'column', gap: 2, justifyContent: 'center' }}>
                          <Button
                            variant="outlined"
                            startIcon={<ContentCopyIcon />}
                            fullWidth
                            onClick={() => {
                              const texto = tabAntunes === 0
                                ? (dadosAntunes.email_corpo && typeof dadosAntunes.email_corpo === 'object'
                                  ? `Assunto: ${dadosAntunes.email_corpo.assunto}\n\n${dadosAntunes.email_corpo.texto}`
                                  : dadosAntunes.email_corpo)
                                : dadosAntunes.relatorio_tecnico;
                              copiarTexto(texto);
                            }}
                          >
                            Copiar Texto
                          </Button>
                          <Button
                            variant="contained"
                            startIcon={<PictureAsPdfIcon />}
                            fullWidth
                            color="primary"
                            onClick={() => gerarPDF(
                              tabAntunes === 0 ? "E-mail de Cobrança" : "Relatório Técnico de Auditoria",
                              tabAntunes === 0 ? dadosAntunes.email_corpo : dadosAntunes.relatorio_tecnico
                            )}
                          >
                            Gerar PDF
                          </Button>
                        </Grid>
                      </Grid>

                      <Alert severity="warning" sx={{ mt: 3, fontSize: '0.8rem', textAlign: 'left' }}>
                        ⚠️ <strong>Disclaimer:</strong> {dadosAntunes.disclaimer}
                      </Alert>
                    </Box>
                  )}
                </CardContent>
              </Paper>
            )}



            {/* Tabela Detalhada */}
            <Paper sx={{ p: 3, mb: 4 }}>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
                <Typography variant="h6" sx={{ color: CORES_MARCA.azul }}>
                  Despesas Detalhadas
                </Typography>
                <FormControl sx={{ minWidth: 200 }}>
                  <InputLabel>Filtrar</InputLabel>
                  <Select
                    value={mostrarApenasAtipicos ? 'atipicos' : 'todas'}
                    label="Filtrar"
                    onChange={(e) => setMostrarApenasAtipicos(e.target.value === 'atipicos')}
                    size="small"
                  >
                    <MenuItem value="todas">📋 Todas as Despesas</MenuItem>
                    <MenuItem value="atipicos">⚠️ Apenas Atípicas</MenuItem>
                  </Select>
                </FormControl>
              
      <DataSourceFooter
        sources={[{"label":"CEAP — Câmara dos Deputados","href":"https://dadosabertos.camara.leg.br/swagger/api.html#api-Despesas","type":"camara"},{"label":"Dados Abertos da Câmara","href":"https://dadosabertos.camara.leg.br","type":"camara"}]}
        note="Cota para Exercício da Atividade Parlamentar (CEAP): verba mensal declarada pelos próprios deputados. Os valores podem ser verificados na fonte primária."
      />
    </Box>

              <TableContainer>
                <Table>
                  <TableHead>
                    <TableRow>
                      <TableCell>Data</TableCell>
                      <TableCell>Fornecedor</TableCell>
                      <TableCell>Descrição</TableCell>
                      <TableCell align="right">Valor</TableCell>
                      <TableCell>Local</TableCell>
                      <TableCell>Status</TableCell>
                      <TableCell>Nota Fiscal</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {dadosParlamentar
                      .filter(despesa => !mostrarApenasAtipicos || (mostrarApenasAtipicos && despesa.valor > limiteAtipico))
                      .map((despesa, index) => (
                        <TableRow key={index}>
                          <TableCell>{formatarData(despesa.data)}</TableCell>
                          <TableCell>{despesa.fornecedor}</TableCell>
                          <TableCell>
                            <Typography variant="body2" sx={{
                              maxWidth: 200,
                              overflow: 'hidden',
                              textOverflow: 'ellipsis',
                              whiteSpace: 'nowrap'
                            }}>
                              {despesa.descricao}
                            </Typography>
                          </TableCell>
                          <TableCell align="right">
                            <Typography variant="body2" fontWeight="bold">
                              {formatarMoeda(despesa.valor)}
                            </Typography>
                          </TableCell>
                          <TableCell>{despesa.estado}</TableCell>
                          <TableCell>
                            {despesa.valor > limiteAtipico ? (
                              <Chip label="Atípico" color="error" size="small" />
                            ) : (
                              <Chip label="Normal" color="success" size="small" />
                            )}
                          </TableCell>
                          <TableCell>
                            {despesa.url_documento && (
                              <Button
                                size="small"
                                variant="outlined"
                                href={despesa.url_documento}
                                target="_blank"
                                startIcon={<OpenInNewIcon />}
                                sx={{ fontSize: '11px' }}
                              >
                                Ver Nota
                              </Button>
                            )}
                          </TableCell>
                        </TableRow>
                      ))}
                  </TableBody>
                </Table>
              </TableContainer>
            </Paper>
          </>
        )
      }
    </Container >
  );
}

export default GastosDetalhamento;
