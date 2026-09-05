import React, { useEffect, useMemo, useState } from 'react';
import {
  Box, Container, Typography, Paper, Grid, Button, CircularProgress, Alert, Stack, FormControl, InputLabel, Select, MenuItem, Chip, Tooltip, Divider, Avatar, TextField, LinearProgress
} from '@mui/material';
import {
  Newspaper as NewspaperIcon, Search as SearchIcon, ContentCopy as ContentCopyIcon
} from '@mui/icons-material';
import ReactMarkdown from 'react-markdown';
import axios from '../config/axios';
import { API_BASE_URL } from '../config';
import ReactECharts from 'echarts-for-react';
import 'echarts-wordcloud';

const brandPalette = {
  azul: '#003366',
  verde: '#009739',
  azulClaro: '#4F81BD',
  amarelo: '#FFF81C',
  laranja: '#ED8B00',
  laranjaClaro: '#FFB74D',
  verdeClaro: '#66BB6A',
  cinza: '#666666',
  cinzaClaro: '#E0E0E0',
  branco: '#FFFFFF'
};

// Paleta de comunidades usando apenas cores do manual de marca
const COMMUNITY_PALETTE_IMPRENSA = [
  '#003366', '#009739', '#4F81BD', '#ED8B00', '#66BB6A',
  '#FFB74D', '#E0E0E0', '#0891B2', '#003366', '#4F81BD',
  '#009739', '#ED8B00', '#66BB6A', '#003366', '#4F81BD', '#009739',
];

const proxyImg = (url) =>
  url ? `${API_BASE_URL}/api/proxy/imagem?url=${encodeURIComponent(url)}` : '';

const formatDateBR = (date) => {
  if (!date) return 'N/A';
  const [year, month, day] = String(date).split('-');
  return year && month && day ? `${day}/${month}/${year}` : date;
};

const TEMA_EMOJIS = {
  'Saúde': '🩺', 'Educação': '📚', 'Justiça/Corrupção': '⚖️',
  'Economia': '💰', 'Segurança Pública': '🛡️', 'Meio Ambiente': '🌿',
  'Infraestrutura': '🏗️', 'Política': '🏛️', 'Internacional': '🌍',
  'Tecnologia': '💻', 'Transporte': '🚌', 'Habitação': '🏠',
  'Esporte': '⚽', 'Cultura': '🎭', 'Agricultura': '🌾',
  'Previdência': '👴', 'Trabalho': '⚒️', 'Ciência': '🔬',
  'Defesa': '🎖️', 'Energia': '⚡', 'Direitos Humanos': '✊',
  'Comunicação': '📡', 'Finanças': '📈', 'Indústria': '🏭',
  'Turismo': '✈️', 'Reforma': '📜', 'Diplomacia': '🤝',
};

const createEmojiSymbol = (emoji, bgColor = '#EAF0FB', borderColor = '#4F81BD', size = 80) =>
  new Promise((resolve) => {
    const canvas = document.createElement('canvas');
    canvas.width = size; canvas.height = size;
    const ctx = canvas.getContext('2d');
    const r = size / 2;
    ctx.fillStyle = bgColor;
    ctx.beginPath(); ctx.arc(r, r, r - 2, 0, Math.PI * 2); ctx.fill();
    ctx.strokeStyle = borderColor;
    ctx.lineWidth = 3;
    ctx.beginPath(); ctx.arc(r, r, r - 3, 0, Math.PI * 2); ctx.stroke();
    ctx.font = `${Math.floor(size * 0.42)}px serif`;
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.fillText(emoji, r, r + 1);
    resolve(`image://${canvas.toDataURL('image/png')}`);
  });

const FP = (f) => `https://commons.wikimedia.org/wiki/Special:FilePath/${f}?width=250`;
const ESTADO_BANDEIRAS = {
  AC: FP('Bandeira_do_Acre.svg'),
  AL: FP('Bandeira_de_Alagoas.svg'),
  AM: FP('Bandeira_do_Amazonas.svg'),
  AP: FP('Bandeira_do_Amap%C3%A1.svg'),
  BA: FP('Bandeira_da_Bahia.svg'),
  CE: FP('Bandeira_do_Cear%C3%A1.svg'),
  DF: FP('Bandeira_do_Distrito_Federal_%28Brasil%29.svg'),
  ES: FP('Bandeira_do_Esp%C3%ADrito_Santo.svg'),
  GO: FP('Flag_of_Goi%C3%A1s.svg'),
  MA: FP('Bandeira_do_Maranh%C3%A3o.svg'),
  MG: FP('Bandeira_de_Minas_Gerais.svg'),
  MS: FP('Bandeira_de_Mato_Grosso_do_Sul.svg'),
  MT: FP('Bandeira_de_Mato_Grosso.svg'),
  PA: FP('Bandeira_do_Par%C3%A1.svg'),
  PB: FP('Bandeira_da_Para%C3%ADba.svg'),
  PE: FP('Bandeira_de_Pernambuco.svg'),
  PI: FP('Bandeira_do_Piau%C3%AD.svg'),
  PR: FP('Bandeira_do_Paran%C3%A1.svg'),
  RJ: FP('Bandeira_do_estado_do_Rio_de_Janeiro.svg'),
  RN: FP('Bandeira_do_Rio_Grande_do_Norte_%28original%29.png'),
  RO: FP('Bandeira_de_Rond%C3%B4nia.svg'),
  RR: FP('Bandeira_de_Roraima.svg'),
  RS: FP('Bandeira_do_Rio_Grande_do_Sul.svg'),
  SC: FP('Bandeira_de_Santa_Catarina.svg'),
  SE: FP('Bandeira_de_Sergipe.svg'),
  SP: FP('Bandeira_do_estado_de_S%C3%A3o_Paulo.svg'),
  TO: FP('Bandeira_do_Tocantins.svg'),
};

const createCircularImageSymbol = (url, borderColor = '#009739', size = 120) => new Promise((resolve) => {
  if (!url) return resolve(null);
  const img = new Image();
  img.crossOrigin = 'anonymous';
  img.onload = () => {
    try {
      const canvas = document.createElement('canvas');
      canvas.width = size;
      canvas.height = size;
      const ctx = canvas.getContext('2d');
      const radius = size / 2;
      ctx.fillStyle = '#FFFFFF';
      ctx.beginPath();
      ctx.arc(radius, radius, radius - 2, 0, Math.PI * 2);
      ctx.fill();
      ctx.save();
      ctx.beginPath();
      ctx.arc(radius, radius, radius - 9, 0, Math.PI * 2);
      ctx.clip();
      const scale = Math.max(size / img.width, size / img.height);
      const sw = img.width * scale;
      const sh = img.height * scale;
      ctx.drawImage(img, (size - sw) / 2, (size - sh) / 2, sw, sh);
      ctx.restore();
      ctx.strokeStyle = borderColor;
      ctx.lineWidth = 7;
      ctx.beginPath();
      ctx.arc(radius, radius, radius - 5, 0, Math.PI * 2);
      ctx.stroke();
      resolve(`image://${canvas.toDataURL('image/png')}`);
    } catch (error) {
      resolve(`image://${url}`);
    }
  };
  img.onerror = () => resolve(null);
  img.src = url;
});

const AuditoriaImprensaV2 = () => {
  const [estados, setEstados] = useState([]);
  const [partidos, setPartidos] = useState([]);
  const [parlamentares, setParlamentares] = useState([]);

  const [estadoSelecionado, setEstadoSelecionado] = useState('Selecione...');
  const [partidoSelecionado, setPartidoSelecionado] = useState('Selecione...');
  const [parlamentoSelecionado, setParlamentoSelecionado] = useState('Selecione...');
  
  const [filtrosBase, setFiltrosBase] = useState({ temas: [] });
  const [temasDisponiveis, setTemasDisponiveis] = useState([]);
  const [temaSelecionado, setTemaSelecionado] = useState('Todos');
  const [apenasEscandalo, setApenasEscandalo] = useState(false);
  const [grafoCategorias, setGrafoCategorias] = useState({ alvo: true, parlamentares: true, fontes: true, temas: true, partidos: true });
  const [grafoPivotTema, setGrafoPivotTema] = useState('');
  const [grafoPivotVeiculo, setGrafoPivotVeiculo] = useState('');
  const [dataInicio, setDataInicio] = useState('2023-01-01');
  const [dataFim, setDataFim] = useState(new Date().toISOString().split('T')[0]);
  const [periodoEfetivo, setPeriodoEfetivo] = useState(null);
  const [loadingDatas, setLoadingDatas] = useState(false);
  
  const [loadingEstados, setLoadingEstados] = useState(false);
  const [loadingPartidos, setLoadingPartidos] = useState(false);
  const [loadingParlamentares, setLoadingParlamentares] = useState(false);
  const [loadingTemas, setLoadingTemas] = useState(false);
  const [loadingFiltros, setLoadingFiltros] = useState(false);
  const [loadingAnalise, setLoadingAnalise] = useState(false);
  const [dadosAnalise, setDadosAnalise] = useState(null);
  const [graphImageSymbols, setGraphImageSymbols] = useState({});
  
  const [loadingRelatorio, setLoadingRelatorio] = useState(false);
  const [relatorioIA, setRelatorioIA] = useState(null);
  const [erro, setErro] = useState(null);
  const [mostrarComunidades, setMostrarComunidades] = useState(false);

  useEffect(() => {
    const fetchFiltros = async () => {
      setLoadingFiltros(true);
      setLoadingEstados(true);
      setLoadingPartidos(true);
      setLoadingParlamentares(true);
      try {
        const { data } = await axios.get('/api/imprensa-v2/filtros');
        if (!data.error) {
          setFiltrosBase(data);
          setEstados(data.ufs || []);
          if (data.periodo_noticias?.data_min) setDataInicio(data.periodo_noticias.data_min < '2023-01-01' ? '2023-01-01' : data.periodo_noticias.data_min);
          if (data.periodo_noticias?.data_max) setDataFim(data.periodo_noticias.data_max);
          if (data.periodo_noticias) setPeriodoEfetivo({ ...data.periodo_noticias, total: null });
        }
      } catch (err) {
        console.error("Erro ao carregar filtros:", err);
      } finally {
        setLoadingFiltros(false);
        setLoadingEstados(false);
        setLoadingPartidos(false);
        setLoadingParlamentares(false);
      }
    };
    fetchFiltros();
  }, []);

  useEffect(() => {
    if (!parlamentoSelecionado || parlamentoSelecionado === 'Selecione...') return;
    setLoadingDatas(true);
    axios.get('/api/imprensa-v2/date-range', {
      params: {
        parlamentar: parlamentoSelecionado,
        tema: temaSelecionado !== 'Todos' ? temaSelecionado : undefined,
        apenas_escandalo: apenasEscandalo
      }
    }).then(({ data }) => {
      if (!data?.error) {
        setPeriodoEfetivo(data);
        if (data.data_min) setDataInicio(data.data_min < '2023-01-01' ? '2023-01-01' : data.data_min);
        if (data.data_max) setDataFim(data.data_max);
      }
    }).catch(() => {}).finally(() => setLoadingDatas(false));
  }, [parlamentoSelecionado, temaSelecionado, apenasEscandalo]);

  useEffect(() => {
    let cancelled = false;
    const buildSymbols = async () => {
      const nodes = dadosAnalise?.graph?.nodes || [];
      const entries = [];
      for (const node of nodes) {
        if (node.category === 0 || node.category === 1) {
          const rawImage = node.category === 0 && dadosAnalise.profile?.foto
            ? dadosAnalise.profile.foto
            : node.symbol?.startsWith('image://')
              ? node.symbol.replace(/^image:\/\//, '')
              : null;
          if (!rawImage) continue;
          const border = node.category === 0 ? brandPalette.verde : (node.itemStyle?.borderColor || brandPalette.azulClaro);
          entries.push([node.id, createCircularImageSymbol(proxyImg(rawImage), border, 120)]);
        } else if (node.category === 2) {
          const domain = node.details?.dominio;
          if (!domain) continue;
          const faviconUrl = `https://t1.gstatic.com/faviconV2?client=SOCIAL&type=FAVICON&fallback_opts=TYPE,SIZE,URL&url=https://${domain}&size=128`;
          entries.push([node.id, createCircularImageSymbol(proxyImg(faviconUrl), '#C9A500', 100)]);
        } else if (node.category === 3) {
          const emoji = TEMA_EMOJIS[node.name] || '📋';
          entries.push([node.id, createEmojiSymbol(emoji)]);
        }
      }
      const resolved = await Promise.all(entries.map(async ([id, promise]) => [id, await promise]));
      if (!cancelled) {
        setGraphImageSymbols(Object.fromEntries(resolved.filter(([, symbol]) => symbol)));
      }
    };
    if (dadosAnalise?.graph?.nodes?.length) buildSymbols();
    return () => { cancelled = true; };
  }, [dadosAnalise]);

  useEffect(() => {
    if (!parlamentoSelecionado || parlamentoSelecionado === 'Selecione...') {
      setTemasDisponiveis([]);
      setTemaSelecionado('Todos');
      return;
    }

    setLoadingTemas(true);
    axios.get('/api/imprensa-v2/temas-parlamentar', {
      params: {
        parlamentar: parlamentoSelecionado,
        apenas_escandalo: apenasEscandalo
      }
    }).then(({ data }) => {
      const temas = data?.temas || [];
      setTemasDisponiveis(temas);
      if (temaSelecionado !== 'Todos' && !temas.includes(temaSelecionado)) {
        setTemaSelecionado('Todos');
        setDadosAnalise(null);
        setErro(null);
      }
    }).catch(() => {
      setTemasDisponiveis([]);
      if (temaSelecionado !== 'Todos') setTemaSelecionado('Todos');
    }).finally(() => {
      setLoadingTemas(false);
    });
  }, [parlamentoSelecionado, apenasEscandalo]);

  // Lógica de Filtragem em Cascata (Local)
  useEffect(() => {
    if (!filtrosBase.parlamentares) return;

    let filtrados = [...filtrosBase.parlamentares];

    // Se UF selecionada, filtrar partidos e parlamentares
    if (estadoSelecionado !== 'Selecione...') {
      filtrados = filtrados.filter(p => p.uf === estadoSelecionado);
      const partidosDaUf = [...new Set(filtrados.map(p => p.partido))].sort();
      setPartidos(partidosDaUf);
    } else {
      setPartidos(filtrosBase.partidos || []);
    }

    // Se Partido selecionado, filtrar parlamentares
    if (partidoSelecionado !== 'Selecione...') {
      filtrados = filtrados.filter(p => p.partido === partidoSelecionado);
    }

    // Mapear apenas para os nomes para o dropdown (removendo duplicatas)
    setParlamentares([...new Set(filtrados.map(p => p.nome))].sort());
    
    // Resetar seleção de parlamentar se o anterior não estiver no novo filtro
    if (!filtrados.find(p => p.nome === parlamentoSelecionado)) {
      setParlamentoSelecionado('Selecione...');
    }
  }, [estadoSelecionado, partidoSelecionado, filtrosBase]);

  const executarCruzamento = async () => {
    if (parlamentoSelecionado === 'Selecione...') return setErro("Selecione um parlamentar obrigatoriamente.");
    setLoadingAnalise(true); setErro(null); setDadosAnalise(null); setRelatorioIA(null);
    try {
      const params = {
        parlamentar: parlamentoSelecionado,
        tema: temaSelecionado !== 'Todos' ? temaSelecionado : undefined,
        apenas_escandalo: apenasEscandalo,
        data_inicio: dataInicio || undefined,
        data_fim: dataFim || undefined
      };
      const { data } = await axios.get('/api/imprensa-v2/analise', { params });
      if (data.error) setErro(data.error);
      else setDadosAnalise(data);
    } catch (err) {
      setErro("Falha ao cruzar dados.");
    } finally {
      setLoadingAnalise(false);
    }
  };

  const gerarDossie = async () => {
    setLoadingRelatorio(true);
    try {
      const payload = {
        parlamentar: parlamentoSelecionado,
        amostra_noticias: dadosAnalise.amostra_noticias,
        temas_ranking: dadosAnalise?.temas_chart?.categories
          ? dadosAnalise.temas_chart.categories.map((cat, i) => ({
              tema: cat,
              total: dadosAnalise.temas_chart.series?.reduce((sum, s) => sum + (s.data?.[i] || 0), 0) || 0
            })).sort((a, b) => b.total - a.total).slice(0, 8)
          : [],
        veiculos_sentimento: (dadosAnalise?.veiculos_stats || []).map(v => ({
          veiculo: v.veiculo_nome,
          media_sentimento: v.media_sentimento,
          total_noticias: v.total_noticias
        })).sort((a, b) => a.media_sentimento - b.media_sentimento)
      };
      const { data } = await axios.post('/api/llm/imprensa-v2-report', payload);
      if (data.error) setErro(data.error);
      else setRelatorioIA(data.report);
    } catch (err) {
      setErro("Erro na comunicação com OpenAI.");
    } finally {
      setLoadingRelatorio(false);
    }
  };

  const chartTemasBar = useMemo(() => {
    if (!dadosAnalise?.temas_chart) return {};
    const { categories, series } = dadosAnalise.temas_chart;
    return {
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
      legend: { bottom: 0, textStyle: { color: brandPalette.azul } },
      grid: { left: '3%', right: '4%', bottom: '15%', containLabel: true },
      xAxis: { 
        type: 'value', 
        splitLine: { show: false } 
      },
      yAxis: { 
        type: 'category', 
        data: categories,
        axisLabel: { fontWeight: 'bold', fontSize: 11 }
      },
      series: series.map(s => {
        // Mapear cores para o manual de marca (NUNCA vermelho)
        const brandColor = s.name === 'Positivo' ? '#009739'   // Verde
          : s.name === 'Negativo'  ? '#ED8B00'   // Laranja escuro (substitui vermelho)
          : s.name === 'Neutro'    ? '#4F81BD'   // Azul claro
          : '#003366';
        return {
          name: s.name,
          type: 'bar',
          stack: 'total',
          emphasis: { focus: 'series' },
          data: s.data,
          itemStyle: { color: brandColor, borderRadius: 4 }
        };
      })
    };
  }, [dadosAnalise]);

  const chartGraphM = useMemo(() => {
    if (!dadosAnalise?.graph || !dadosAnalise.graph.nodes) return {};
    const { nodes: allNodes, links: allLinks, categories, communities: graphCommunities = {} } = dadosAnalise.graph;

    // catVisible: suporta até categoria 4 (partidos)
    const catVisible = [
      grafoCategorias.alvo,
      grafoCategorias.parlamentares,
      grafoCategorias.fontes,
      grafoCategorias.temas,
      grafoCategorias.partidos !== false, // categoria 4 = partidos
    ];
    let seenIds = new Set();
    let nodes = allNodes.filter(n => {
      if (catVisible[n.category] === false) return false;
      if (seenIds.has(n.id)) return false;
      seenIds.add(n.id);
      return true;
    });
    let visibleIds = new Set(nodes.map(n => n.id));
    let links = allLinks.filter(l => visibleIds.has(l.source) && visibleIds.has(l.target));

    // Pivot filter: if a tema or veiculo is selected, keep only those nodes + direct neighbors
    const pivotIds = new Set();
    if (grafoPivotTema) pivotIds.add(`T_${grafoPivotTema}`);
    if (grafoPivotVeiculo) pivotIds.add(`V_${grafoPivotVeiculo}`);
    if (pivotIds.size > 0) {
      const neighborIds = new Set(pivotIds);
      links.forEach(l => {
        if (pivotIds.has(l.source)) neighborIds.add(l.target);
        if (pivotIds.has(l.target)) neighborIds.add(l.source);
      });
      nodes = nodes.filter(n => neighborIds.has(n.id));
      links = links.filter(l => neighborIds.has(l.source) && neighborIds.has(l.target));
    }

    // Cores do manual de marca: Azul #003366, Verde #009739, Laranja #ED8B00, Azul Claro #4F81BD
    const labelByCategory = {
      0: { borderColor: '#009739', textColor: '#003366' },   // Alvo: borda verde
      1: { borderColor: '#009739', textColor: '#003366' },   // Deputados: borda verde
      2: { borderColor: '#ED8B00', textColor: '#5a3000' },   // Veículos: borda laranja
      3: { borderColor: '#4F81BD', textColor: '#003366' },   // Temas: borda azul claro
      4: { borderColor: '#003366', textColor: '#003366' },   // Partidos: borda azul escuro
    };

    return {
      backgroundColor: '#F8FAFD',
      color: ['#003366', '#009739', '#ED8B00', '#4F81BD'],
      tooltip: {
        trigger: 'item',
        formatter: (params) => {
          const d = params.data || {};
          if (params.dataType === 'edge') {
            return `
              <strong>${String(params.data.source || '').replace(/^V_|^T_|^P_/, '')} → ${String(params.data.target || '').replace(/^V_|^T_|^P_/, '')}</strong><br/>
              Conexões: ${params.data.value || 0}<br/>
              Sentimento predominante: <strong>${params.data.sentimento || 'Neutro'}</strong>
            `;
          }
          const details = d.details || {};
          const linhas = [
            `<strong>${d.name}</strong>`,
            details.tipo ? `Tipo: ${details.tipo}` : null,
            details.dominio ? `Domínio: ${details.dominio}` : null,
            details.total !== undefined ? `Matérias: ${details.total}` : null,
            details.sentimento_dominante ? `Sentimento predominante: <strong>${details.sentimento_dominante}</strong>` : null,
            details.sentimento_medio !== undefined && details.sentimento_medio !== null ? `Sentimento médio: ${Number(details.sentimento_medio).toFixed(1)}` : null,
            details.partido ? `Partido: ${details.partido}` : null,
            details.uf ? `UF: ${details.uf}` : null,
          ].filter(Boolean);
          return linhas.join('<br/>');
        }
      },
      legend: [{ data: categories?.map(a => a.name) || [], top: 10, left: 10, textStyle: { color: '#333', fontFamily: 'Inter' }, backgroundColor: 'rgba(255,255,255,0.9)', borderColor: '#E0E0E0', borderWidth: 1, padding: 10 }],
      series: [{
        name: 'Rede de Difusão',
        type: 'graph',
        layout: 'force',
        data: (nodes || []).map((node) => {
          const lbl = labelByCategory[node.category] || labelByCategory[3];
          const communityId = mostrarComunidades ? graphCommunities[node.id] : undefined;
          const communityColor = communityId !== undefined
            ? COMMUNITY_PALETTE_IMPRENSA[communityId % COMMUNITY_PALETTE_IMPRENSA.length]
            : null;
          return {
            ...node,
            symbol: graphImageSymbols[node.id] || node.symbol,
            symbolSize: node.category === 0 ? 78 : node.category === 3 ? (graphImageSymbols[node.id] ? 40 : node.symbolSize) : node.symbolSize,
            itemStyle: {
              ...(node.itemStyle || {}),
              color: node.category === 0 ? brandPalette.azul : node.itemStyle?.color,
              borderColor: communityColor || (node.category === 0 ? brandPalette.verde : node.itemStyle?.borderColor),
              borderWidth: communityColor ? 4 : (node.category === 0 ? 4 : (node.itemStyle?.borderWidth || 2)),
              shadowBlur: communityColor ? 8 : (node.category <= 1 ? 10 : 0),
              shadowColor: communityColor ? `${communityColor}55` : (node.category <= 1 ? 'rgba(0,51,102,0.2)' : 'transparent'),
            },
            label: {
              show: true,
              position: 'bottom',
              formatter: '{b}',
              color: lbl.textColor,
              fontFamily: 'Inter',
              fontWeight: 'bold',
              fontSize: node.category === 0 ? 13 : 11,
              backgroundColor: 'rgba(255,255,255,0.92)',
              borderColor: lbl.borderColor,
              borderWidth: 1,
              borderRadius: 4,
              padding: [4, 8],
            }
          };
        }),
        links: (links || []).map(lk => ({
          ...lk,
          lineStyle: {
            ...(lk.lineStyle || {}),
            curveness: lk.lineStyle?.type === 'dashed' ? 0.15 : 0.3,
          }
        })),
        categories: categories || [],
        roam: true,
        labelLayout: { hideOverlap: true },
        scaleLimit: { min: 0.3, max: 2.5 },
        edgeSymbol: ['none', 'arrow'],
        edgeSymbolSize: [0, 10],
        edgeLabel: { show: false },
        lineStyle: { color: '#C8D8EC', curveness: 0.3, width: 2 },
        force: { repulsion: 1100, edgeLength: 220, gravity: 0.05 },
        emphasis: {
          focus: 'adjacency',
          lineStyle: { width: 6 },
          itemStyle: { shadowBlur: 20, shadowColor: 'rgba(0,51,102,0.4)', borderWidth: 4 },
          label: { show: true }
        }
      }]
    };
  }, [dadosAnalise, graphImageSymbols, grafoCategorias, grafoPivotTema, grafoPivotVeiculo, mostrarComunidades]);

  const chartWordCloud = useMemo(() => {
    if (!dadosAnalise?.bigrams?.length) return {};
    // Wordcloud: apenas cores do manual de marca
    const colors = [brandPalette.azul, brandPalette.verde, brandPalette.azulClaro, brandPalette.laranja, brandPalette.verdeClaro, brandPalette.laranjaClaro];
    return {
      tooltip: {
        show: true,
        formatter: (params) => `<b>${params.name}</b>: ${params.value} ocorrências`
      },
      series: [{
        type: 'wordCloud',
        shape: 'circle',
        left: 'center',
        top: 'center',
        width: '95%',
        height: '95%',
        right: null,
        bottom: null,
        sizeRange: [11, 28],
        rotationRange: [0, 0],
        rotationStep: 0,
        gridSize: 10,
        drawOutOfBound: false,
        layoutAnimation: true,
        textStyle: {
          fontFamily: 'Inter, sans-serif',
          fontWeight: 'bold',
          color: () => colors[Math.floor(Math.random() * colors.length)],
        },
        emphasis: {
          textStyle: { shadowBlur: 10, shadowColor: 'rgba(0,51,102,0.3)' }
        },
        data: (dadosAnalise.bigrams || []).map(b => ({
          name: b.text,
          value: b.value,
        }))
      }]
    };
  }, [dadosAnalise]);

  const SpinnerIcon = () => (
    <CircularProgress size={18} thickness={4} sx={{ mr: 1, color: 'inherit', opacity: 0.6 }} />
  );

  const ScaleBar = ({ label, value, color }) => (
    <Box sx={{ mb: 2 }}>
      <Stack direction="row" justifyContent="space-between" sx={{ mb: 0.5 }}>
        <Typography variant="body2" sx={{ fontFamily: 'Montserrat', fontWeight: 700, color: '#666' }}>{label}</Typography>
        <Typography variant="body2" sx={{ fontFamily: 'Roboto Mono', fontWeight: 700 }}>{value?.toFixed(1)}/10</Typography>
      </Stack>
      <Box sx={{ width: '100%', height: 12, bgcolor: brandPalette.cinzaClaro, borderRadius: 6, overflow: 'hidden' }}>
        <Box sx={{ width: `${Math.min(value * 10, 100)}%`, height: '100%', bgcolor: color, transition: 'width 1.5s cubic-bezier(0.4, 0, 0.2, 1)' }} />
      </Box>
    </Box>
  );

  return (
    <Container maxWidth="xl" sx={{ py: 4, bgcolor: '#F5F7FA', minHeight: '100vh' }}>
      <Box sx={{ 
        mb: 4, bgcolor: brandPalette.branco, p: 4, 
        borderRadius: '32px 32px 8px 8px', 
        borderBottom: `6px solid ${brandPalette.verde}`,
        boxShadow: '0 10px 40px rgba(0,51,102,0.05)',
        display: 'flex', alignItems: 'center', gap: 4 
      }}>
        <Box sx={{ flex: 1 }}>
          <Typography variant="h3" component="h1" sx={{ color: brandPalette.azul, fontWeight: 800, mb: 1, fontFamily: 'Montserrat', letterSpacing: '-1.5px' }}>
            Análise de Imprensa - Auditoria Forense
          </Typography>
          <Typography variant="h6" sx={{ color: brandPalette.cinza, fontFamily: 'Inter', fontWeight: 400 }}>
            Monitoramento investigativo profundo do comportamento midiático.
          </Typography>
        </Box>
        <Box component="img" src="/Analise_de_Imprensa.png" alt="Ilustração Antunes" sx={{ maxHeight: '180px', width: 'auto', filter: 'drop-shadow(0 10px 20px rgba(0,51,102,0.1))' }} />
      </Box>

      {/* FILTROS */}
      <Paper sx={{ p: 4, mb: 4, borderRadius: 2 }}>
        <Typography variant="h5" sx={{ mb: 3, fontWeight: 'bold' }}>Parâmetros de Auditoria Forense</Typography>
        <Grid container spacing={3}>
          <Grid item xs={12} md={3}>
            <FormControl fullWidth>
              <InputLabel>Estado</InputLabel>
              <Select
                value={estadoSelecionado}
                onChange={(e) => setEstadoSelecionado(e.target.value)}
                disabled={loadingEstados}
                IconComponent={loadingEstados ? SpinnerIcon : undefined}
              >
                <MenuItem value="Selecione...">Todos</MenuItem>
                {estados.map(est => <MenuItem key={est} value={est}>{est}</MenuItem>)}
              </Select>
            </FormControl>
          </Grid>
          <Grid item xs={12} md={3}>
            <FormControl fullWidth>
              <InputLabel>Partido</InputLabel>
              <Select
                value={partidoSelecionado}
                onChange={(e) => setPartidoSelecionado(e.target.value)}
                disabled={loadingPartidos}
                IconComponent={loadingPartidos ? SpinnerIcon : undefined}
              >
                <MenuItem value="Selecione...">Todos</MenuItem>
                {partidos.map(p => <MenuItem key={p} value={p}>{p}</MenuItem>)}
              </Select>
            </FormControl>
          </Grid>
          <Grid item xs={12} md={3}>
            <FormControl fullWidth>
              <InputLabel>Parlamentar Alvo</InputLabel>
              <Select
                value={parlamentoSelecionado}
                onChange={(e) => setParlamentoSelecionado(e.target.value)}
                disabled={loadingParlamentares}
                IconComponent={loadingParlamentares ? SpinnerIcon : undefined}
              >
                <MenuItem value="Selecione...">Selecione...</MenuItem>
                {parlamentares.map(p => <MenuItem key={p.nome || p} value={p.nome || p}>{p.nome || p}</MenuItem>)}
              </Select>
            </FormControl>
          </Grid>
          <Grid item xs={12} md={3}>
            <FormControl fullWidth>
              <InputLabel>Tema Pautado</InputLabel>
              <Select
                value={temaSelecionado}
                onChange={(e) => setTemaSelecionado(e.target.value)}
                disabled={parlamentoSelecionado === 'Selecione...' || loadingTemas}
                IconComponent={loadingTemas ? SpinnerIcon : undefined}
              >
                <MenuItem value="Todos">Todos</MenuItem>
                {temasDisponiveis.map(t => <MenuItem key={t} value={t}>{t}</MenuItem>)}
              </Select>
            </FormControl>
          </Grid>
          <Grid item xs={12} md={6}>
            <Button
              variant={apenasEscandalo ? "contained" : "outlined"}
              fullWidth
              onClick={() => setApenasEscandalo(!apenasEscandalo)}
              sx={{
                borderColor: '#ED8B00',
                color: apenasEscandalo ? '#FFFFFF' : '#ED8B00',
                bgcolor: apenasEscandalo ? '#ED8B00' : 'transparent',
                fontWeight: 700,
                '&:hover': { bgcolor: apenasEscandalo ? '#c97a00' : 'rgba(237,139,0,0.08)', borderColor: '#c97a00' }
              }}
            >
              {apenasEscandalo ? "⚠️ FILTRAR APENAS POLÊMICAS" : "Padrão: Tolerante (Com e Sem Polêmicas)"}
            </Button>
          </Grid>
          <Grid item xs={12} md={3}>
            <TextField
              fullWidth
              size="small"
              label="📅 Data Início"
              type="date"
              value={dataInicio}
              onChange={(e) => setDataInicio(e.target.value < '2023-01-01' ? '2023-01-01' : e.target.value)}
              disabled={loadingDatas}
              InputLabelProps={{ shrink: true }}
              inputProps={{ min: '2023-01-01' }}
              InputProps={loadingDatas ? {
                endAdornment: <CircularProgress size={14} thickness={5} sx={{ color: brandPalette.azul, mr: 0.5 }} />
              } : undefined}
            />
          </Grid>
          <Grid item xs={12} md={3}>
            <TextField
              fullWidth
              size="small"
              label="📅 Data Fim"
              type="date"
              value={dataFim}
              onChange={(e) => setDataFim(e.target.value)}
              disabled={loadingDatas}
              InputLabelProps={{ shrink: true }}
              InputProps={loadingDatas ? {
                endAdornment: <CircularProgress size={14} thickness={5} sx={{ color: brandPalette.azul, mr: 0.5 }} />
              } : undefined}
            />
          </Grid>
          {loadingDatas && (
            <Grid item xs={12}>
              <Box sx={{
                display: 'flex', alignItems: 'center', gap: 1.5,
                px: 1.5, py: 0.75, borderRadius: '8px',
                backgroundColor: 'rgba(0,55,102,0.04)',
                border: '1px solid rgba(0,55,102,0.1)',
              }}>
                <CircularProgress size={14} thickness={5} sx={{ color: brandPalette.azul, flexShrink: 0 }} />
                <Box sx={{ flex: 1 }}>
                  <LinearProgress
                    variant="indeterminate"
                    sx={{
                      height: 3, borderRadius: 2,
                      backgroundColor: 'rgba(0,55,102,0.1)',
                      '& .MuiLinearProgress-bar': { backgroundColor: brandPalette.azul },
                    }}
                  />
                </Box>
                <Typography sx={{ fontSize: '12px', color: '#546e7a', whiteSpace: 'nowrap' }}>
                  Buscando período efetivo das notícias...
                </Typography>
              </Box>
            </Grid>
          )}
          {periodoEfetivo?.data_min && periodoEfetivo?.data_max && (
            <Grid item xs={12}>
              <Box sx={{
                display: 'flex',
                alignItems: 'center',
                gap: 1,
                px: 1.5,
                py: 1,
                borderRadius: '8px',
                backgroundColor: 'rgba(0, 55, 102, 0.06)',
                border: '1px solid rgba(0, 55, 102, 0.12)',
              }}>
                <Typography sx={{ fontSize: '13px', lineHeight: 1.4, color: '#546e7a' }}>
                  📅 <strong>Período efetivo das notícias</strong> — {formatDateBR(periodoEfetivo.data_min)} a {formatDateBR(periodoEfetivo.data_max)}
                  {typeof periodoEfetivo.total === 'number' ? ` (${periodoEfetivo.total.toLocaleString('pt-BR')} registros antes do filtro manual de datas)` : ''}.
                  Você pode ajustar manualmente para um subperíodo.
                </Typography>
              </Box>
            </Grid>
          )}
        </Grid>
        <Button variant="contained" sx={{ mt: 3, bgcolor: brandPalette.verde, '&:hover': { bgcolor: '#007a30' }, fontWeight: 700, borderRadius: 2 }} startIcon={loadingAnalise ? <CircularProgress size={20}/> : <SearchIcon />} onClick={executarCruzamento}>
          Executar Mapeamento
        </Button>
      </Paper>

      {erro && <Alert severity="warning" sx={{ mb: 4, bgcolor: '#FFF3E0', color: '#5a3000', border: '1px solid #ED8B00', '& .MuiAlert-icon': { color: '#ED8B00' } }}>{erro}</Alert>}

      {dadosAnalise && (
        <Box>
            {/* CABEÇALHO DE PERFIL */}
            <Paper elevation={3} sx={{ p: 4, mb: 4, bgcolor: '#FFFFFF', borderRadius: 4, border: '1px solid #e0e0e0' }}>
                <Grid container spacing={3} alignItems="center">
                    {/* Foto */}
                    <Grid item xs={12} md={2} sx={{ display: 'flex', justifyContent: 'center' }}>
                        <Avatar
                            src={dadosAnalise.profile?.foto}
                            referrerPolicy="no-referrer"
                            alt={dadosAnalise.profile?.nome || parlamentoSelecionado}
                            sx={{ width: 140, height: 140, border: `4px solid ${brandPalette.verde}`, boxShadow: '0 4px 12px rgba(0,0,0,0.1)' }}
                        >
                            {(dadosAnalise.profile?.nome || parlamentoSelecionado)?.[0] || '?'}
                        </Avatar>
                    </Grid>

                    {/* Info central */}
                    <Grid item xs={12} md={6}>
                        <Typography variant="h3" fontWeight="bold" sx={{ color: brandPalette.azul, letterSpacing: '-0.5px', fontFamily: 'Montserrat' }}>
                            {dadosAnalise.profile?.nome || parlamentoSelecionado}
                        </Typography>
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, mt: 2, flexWrap: 'wrap' }}>
                            <Chip
                                avatar={<Avatar src={proxyImg(dadosAnalise.profile?.partido_logo)} />}
                                label={dadosAnalise.profile?.partido || partidoSelecionado}
                                sx={{ bgcolor: 'rgba(0,151,57,0.1)', color: brandPalette.azul, fontWeight: 'bold', fontFamily: 'Montserrat', px: 0.5, fontSize: '0.9rem', border: `1px solid ${brandPalette.verde}` }}
                            />
                            <Chip
                                avatar={<Avatar src={proxyImg(ESTADO_BANDEIRAS[dadosAnalise.profile?.uf])} />}
                                label={dadosAnalise.profile?.uf || estadoSelecionado}
                                sx={{ bgcolor: 'rgba(0,51,102,0.08)', color: brandPalette.azul, fontWeight: 'bold', fontFamily: 'Montserrat', px: 0.5, fontSize: '0.9rem', border: `1px solid ${brandPalette.azulClaro}` }}
                            />
                        </Box>
                        <Typography variant="body1" sx={{ mt: 1.5, color: '#444', fontWeight: 600, fontFamily: 'Montserrat' }}>
                            Análise de Imprensa Parlamentar
                        </Typography>
                        {dadosAnalise.metrics?.periodo?.inicio && dadosAnalise.metrics?.periodo?.fim && (
                            <Typography variant="caption" sx={{ display: 'block', mt: 0.75, color: brandPalette.cinza, fontWeight: 600, fontFamily: 'Inter' }}>
                                Período analisado: {formatDateBR(dadosAnalise.metrics.periodo.inicio)} a {formatDateBR(dadosAnalise.metrics.periodo.fim)}
                            </Typography>
                        )}
                    </Grid>

                    {/* Logos partido + estado */}
                    <Grid item xs={12} md={1} sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2 }}>
                        {dadosAnalise.profile?.partido_logo && (
                            <Box
                                component="img"
                                src={proxyImg(dadosAnalise.profile.partido_logo)}
                                alt="Logo Partido"
                                onError={(e) => { e.currentTarget.style.display = 'none'; }}
                                sx={{ height: 60, width: 'auto', maxWidth: 100, objectFit: 'contain' }}
                            />
                        )}
                        {dadosAnalise.profile?.uf && ESTADO_BANDEIRAS[dadosAnalise.profile.uf] && (
                            <Box
                                component="img"
                                src={proxyImg(ESTADO_BANDEIRAS[dadosAnalise.profile.uf])}
                                alt={`Bandeira ${dadosAnalise.profile.uf}`}
                                onError={(e) => { e.currentTarget.style.display = 'none'; }}
                                sx={{ height: 38, width: 'auto', maxWidth: 70, objectFit: 'contain', borderRadius: '4px', border: '1px solid #e0e0e0', boxShadow: 1 }}
                            />
                        )}
                    </Grid>

                    {/* Stat boxes — mesma altura fixa */}
                    <Grid item xs={12} md={3}>
                        <Grid container spacing={1.5}>
                            {[
                                { label: 'Total\nNotícias', value: dadosAnalise.metrics.total, hint: null },
                                { label: 'Média\nMensal', value: dadosAnalise.metrics.avg_month?.toFixed(1), hint: 'notícias/mês no período' },
                                { label: 'Polêmicas', value: dadosAnalise.metrics.escand, hint: null },
                            ].map(({ label, value, hint }) => (
                                <Grid item xs={4} key={label}>
                                    <Tooltip title={hint || ''} arrow placement="top" disableHoverListener={!hint}>
                                        <Box sx={{
                                            height: 90,
                                            display: 'flex', flexDirection: 'column', justifyContent: 'center', alignItems: 'center',
                                            bgcolor: '#F5F7FA', borderRadius: 2, border: '1px solid #E0E0E0',
                                            px: 1, textAlign: 'center', cursor: hint ? 'help' : 'default'
                                        }}>
                                            <Typography sx={{ color: brandPalette.azul, fontWeight: 700, fontFamily: 'Montserrat', fontSize: '0.68rem', lineHeight: 1.3, whiteSpace: 'pre-line' }}>{label}</Typography>
                                            <Typography variant="h5" fontWeight="bold" sx={{ color: brandPalette.azul, mt: 0.5, fontFamily: 'Montserrat' }}>{value}</Typography>
                                            {hint && <Typography sx={{ fontSize: '0.58rem', color: '#999', fontFamily: 'Inter', mt: 0.25, lineHeight: 1.2 }}>{hint}</Typography>}
                                        </Box>
                                    </Tooltip>
                                </Grid>
                            ))}
                        </Grid>
                    </Grid>

                    {/* Indicadores — double-ring gauge */}
                    <Grid item xs={12}>
                        <Divider sx={{ mb: 1 }} />
                        <Grid container spacing={0}>
                            {[
                                { label: 'SENTIMENTO', value: dadosAnalise.metrics.sent, accentColor: dadosAnalise.metrics.sent >= 7 ? brandPalette.verde : dadosAnalise.metrics.sent <= 4 ? brandPalette.laranja : brandPalette.azulClaro, scaleHint: '0 = Negativo · 5 = Neutro · 10 = Positivo' },
                                { label: 'PROTAGONISMO', value: dadosAnalise.metrics.prot, accentColor: brandPalette.laranja, scaleHint: '0 = Ignorado · 5 = Presente · 10 = Protagonista' },
                            ].map(({ label, value, accentColor, scaleHint }) => {
                                const v = parseFloat(value?.toFixed(1) || 0);
                                return (
                                    <Grid item xs={12} md={6} key={label}>
                                        <ReactECharts option={{
                                            series: [
                                                {
                                                    type: 'gauge', center: ['50%', '70%'],
                                                    startAngle: 200, endAngle: -20, min: 0, max: 10, splitNumber: 5,
                                                    itemStyle: { color: accentColor },
                                                    progress: { show: true, width: 18 },
                                                    pointer: { show: false },
                                                    axisLine: { lineStyle: { width: 18, color: [[1, '#EAEEF2']] } },
                                                    axisTick: { distance: -28, splitNumber: 4, lineStyle: { width: 1, color: '#CCC' } },
                                                    splitLine: { distance: -34, length: 10, lineStyle: { width: 2, color: '#CCC' } },
                                                    axisLabel: { distance: -14, color: '#999', fontSize: 11, fontFamily: 'Inter', formatter: (v) => v % 5 === 0 ? v : '' },
                                                    anchor: { show: false },
                                                    title: { show: false },
                                                    detail: {
                                                        valueAnimation: true, offsetCenter: [0, '-5%'],
                                                        fontSize: 36, fontWeight: 'bolder', fontFamily: 'Montserrat',
                                                        color: brandPalette.azul,
                                                        formatter: '{value}'
                                                    },
                                                    data: [{ value: v, name: label }]
                                                },
                                                {
                                                    type: 'gauge', center: ['50%', '70%'],
                                                    startAngle: 200, endAngle: -20, min: 0, max: 10,
                                                    itemStyle: { color: accentColor },
                                                    progress: { show: true, width: 6 },
                                                    pointer: { show: false },
                                                    axisLine: { show: false }, axisTick: { show: false },
                                                    splitLine: { show: false }, axisLabel: { show: false },
                                                    detail: { show: false },
                                                    title: { show: true, offsetCenter: [0, '30%'], fontSize: 11, fontWeight: 700, fontFamily: 'Montserrat', color: '#999', formatter: label },
                                                    data: [{ value: v, name: label }]
                                                }
                                            ]
                                        }} style={{ height: '180px' }} />
                                        <Typography sx={{ textAlign: 'center', fontSize: '0.7rem', color: '#AAA', fontFamily: 'Inter', mt: -1, mb: 1 }}>
                                            {scaleHint}
                                        </Typography>
                                    </Grid>
                                );
                            })}
                        </Grid>
                    </Grid>
                </Grid>
            </Paper>

          <Grid container spacing={3}>
            {/* BARRAS EMPILHADAS DE TEMAS E SENTIMENTO */}
            <Grid item xs={12} md={8}>
              <Paper sx={{ p: 3, height: '450px', borderRadius: '24px', border: `1px solid ${brandPalette.cinzaClaro}` }}>
                <Typography variant="h6" sx={{ mb: 2, fontWeight: 700, fontFamily: 'Montserrat', color: brandPalette.azul }}>Principais Temas por Sentimento</Typography>
                {chartTemasBar?.series?.length > 0 ? (
                  <ReactECharts option={chartTemasBar} style={{ height: '380px', width: '100%' }} />
                ) : (
                  <Box sx={{ height: '380px', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#999' }}>
                    <Typography>Sem dados de temas disponíveis.</Typography>
                  </Box>
                )}
              </Paper>
            </Grid>
            <Grid item xs={12} md={4}>
              <Paper sx={{ p: 4, height: '450px', borderRadius: '24px', border: `1px solid ${brandPalette.cinzaClaro}` }}>
                <Typography variant="h6" sx={{ mb: 2, fontWeight: 700, fontFamily: 'Montserrat', color: brandPalette.azul }}>Expressões Associadas (Nuvem)</Typography>
                {chartWordCloud?.series?.length > 0 ? (
                  <ReactECharts option={chartWordCloud} style={{ height: '360px', width: '100%' }} />
                ) : (
                  <Box sx={{ height: '360px', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#999' }}>
                    <Typography>Sem dados de expressões disponíveis.</Typography>
                  </Box>
                )}
              </Paper>
            </Grid>

            {/* GRAFO MULTIMODAL */}
            <Grid item xs={12}>
                <Paper sx={{ p: 3 }}>
                    {/* Linha 1: título + chips de categoria */}
                    <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 1.5, flexWrap: 'wrap', gap: 1 }}>
                        <Typography variant="h6" sx={{ fontWeight: 700, fontFamily: 'Montserrat', color: brandPalette.azul }}>
                            Rede de Difusão: Parlamentar, Fontes e Sentimento
                        </Typography>
                        <Stack direction="row" spacing={0.75} flexWrap="wrap">
                            {[
                                { key: 'alvo', label: 'Alvo', color: brandPalette.azul },
                                { key: 'parlamentares', label: 'Deputados citados', color: brandPalette.verde },
                                { key: 'fontes', label: 'Veículos', color: brandPalette.laranja },
                                { key: 'temas', label: 'Temas', color: brandPalette.azulClaro },
                                { key: 'partidos', label: 'Partidos', color: '#4F81BD' },
                            ].map(({ key, label, color }) => (
                                <Chip
                                    key={key}
                                    label={label}
                                    size="small"
                                    onClick={() => setGrafoCategorias(p => ({ ...p, [key]: !p[key] }))}
                                    sx={{
                                        fontFamily: 'Montserrat', fontWeight: 600, fontSize: '0.75rem',
                                        bgcolor: grafoCategorias[key] ? color : '#E0E0E0',
                                        color: grafoCategorias[key] ? '#fff' : '#888',
                                        cursor: 'pointer', '&:hover': { opacity: 0.85 }
                                    }}
                                />
                            ))}
                        </Stack>
                    </Box>

                    {/* Linha 2: filtros de pivot (tema + veículo) */}
                    <Box sx={{ display: 'flex', gap: 1.5, mb: 1.5, flexWrap: 'wrap', alignItems: 'center' }}>
                        <FormControl size="small" sx={{ minWidth: 180 }}>
                            <InputLabel sx={{ fontFamily: 'Inter', fontSize: '0.82rem' }}>Filtrar por Tema</InputLabel>
                            <Select
                                value={grafoPivotTema}
                                label="Filtrar por Tema"
                                onChange={e => setGrafoPivotTema(e.target.value)}
                                sx={{ fontFamily: 'Inter', fontSize: '0.82rem', borderRadius: 2 }}
                            >
                                <MenuItem value=""><em>Todos os temas</em></MenuItem>
                                {(dadosAnalise.graph?.nodes || [])
                                    .filter(n => n.category === 3)
                                    .map(n => <MenuItem key={n.id} value={n.name} sx={{ fontFamily: 'Inter', fontSize: '0.82rem' }}>{n.name}</MenuItem>)
                                }
                            </Select>
                        </FormControl>

                        <FormControl size="small" sx={{ minWidth: 220 }}>
                            <InputLabel sx={{ fontFamily: 'Inter', fontSize: '0.82rem' }}>Filtrar por Veículo</InputLabel>
                            <Select
                                value={grafoPivotVeiculo}
                                label="Filtrar por Veículo"
                                onChange={e => setGrafoPivotVeiculo(e.target.value)}
                                sx={{ fontFamily: 'Inter', fontSize: '0.82rem', borderRadius: 2 }}
                            >
                                <MenuItem value=""><em>Todos os veículos</em></MenuItem>
                                {(dadosAnalise.graph?.nodes || [])
                                    .filter(n => n.category === 2)
                                    .map(n => <MenuItem key={n.id} value={n.raw_name || n.name} sx={{ fontFamily: 'Inter', fontSize: '0.82rem' }}>{n.raw_name || n.name}</MenuItem>)
                                }
                            </Select>
                        </FormControl>

                        {(grafoPivotTema || grafoPivotVeiculo) && (
                            <Chip
                                label="Limpar filtros"
                                size="small"
                                onClick={() => { setGrafoPivotTema(''); setGrafoPivotVeiculo(''); }}
                                sx={{ fontFamily: 'Montserrat', fontWeight: 600, fontSize: '0.72rem', bgcolor: 'rgba(237,139,0,0.12)', color: brandPalette.laranja, border: `1px solid ${brandPalette.laranja}`, cursor: 'pointer' }}
                            />
                        )}
                    </Box>

                    <Alert severity="info" icon={false} sx={{ mb: 1.5, py: 0.75, borderRadius: 2, fontSize: '0.82rem', bgcolor: '#EAF3FB', border: '1px solid #C3DCF0', color: '#1a3a6e' }}>
                        <strong>Parlamentares citados</strong> (nós verdes) aparecem nas mesmas notícias do parlamentar analisado — pelos mesmos veículos e temas. Arestas tracejadas indicam co-ocorrência.
                    </Alert>

                    {/* Louvain toggle */}
                    {dadosAnalise?.graph?.nodes?.length > 0 && (
                      <Box sx={{ mb: 1.5, display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
                        <Chip
                          label={(() => {
                            if (!mostrarComunidades) return '🔬 Comunidades Louvain';
                            const n = new Set(Object.values(dadosAnalise.graph.communities || {})).size;
                            return `🔬 Comunidades Louvain — ${n} grupos`;
                          })()}
                          onClick={() => setMostrarComunidades(v => !v)}
                          color={mostrarComunidades ? 'primary' : 'default'}
                          variant={mostrarComunidades ? 'filled' : 'outlined'}
                          size="small"
                          sx={{ fontWeight: 600, cursor: 'pointer' }}
                        />
                        {mostrarComunidades && (() => {
                          const ids = [...new Set(Object.values(dadosAnalise.graph.communities || {}))].sort((a, b) => a - b);
                          return ids.map(i => (
                            <Box key={i} sx={{ display: 'flex', alignItems: 'center', gap: 0.4 }}>
                              <Box sx={{ width: 10, height: 10, borderRadius: '50%', bgcolor: COMMUNITY_PALETTE_IMPRENSA[i % COMMUNITY_PALETTE_IMPRENSA.length] }} />
                              <Typography variant="caption" sx={{ color: '#555', fontSize: '0.68rem' }}>C{i + 1}</Typography>
                            </Box>
                          ));
                        })()}
                      </Box>
                    )}

                    {chartGraphM?.series?.length > 0 && chartGraphM.series[0]?.data?.length > 0 ? (
                      <ReactECharts
                        option={chartGraphM}
                        style={{ height: '620px', width: '100%' }}
                        notMerge={true}
                      />
                    ) : (
                      <Box sx={{ height: '520px', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#999' }}>
                        <CircularProgress size={30} sx={{ mr: 2 }} />
                        <Typography>Processando grafo de relações...</Typography>
                      </Box>
                    )}
                </Paper>
            </Grid>
          </Grid>

          {/* TABELA DE AUDITORIA */}
          <Paper sx={{ p: 3, mt: 4 }}>
                <Typography variant="h6" sx={{ mb: 3, fontWeight: 'bold' }}>Detalhamento da Amostra Auditada</Typography>
                <Box sx={{ overflowX: 'auto' }}>
                    <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                        <thead>
                            <tr style={{ borderBottom: '2px solid #eee', textAlign: 'left' }}>
                                <th style={{ padding: '12px' }}>Veículo</th>
                                <th>Data</th>
                                <th>Sentimento</th>
                                <th>Resumo Forense</th>
                                <th>Ações</th>
                            </tr>
                        </thead>
                        <tbody>
                            {dadosAnalise.amostra_noticias.map((n, idx) => {
                                let dataExibicao = '01/01/2025';
                                if (n.data_noticia && n.data_noticia !== 'None') {
                                    if (n.data_noticia.toString().includes('/')) {
                                        dataExibicao = n.data_noticia;
                                    } else {
                                        const d = new Date(n.data_noticia);
                                        if (!isNaN(d.getTime())) dataExibicao = d.toLocaleDateString('pt-BR');
                                    }
                                }
                                return (
                                    <tr key={idx} style={{ borderBottom: '1px solid #f5f5f5' }}>
                                        <td style={{ padding: '12px' }}>{n.veiculo_nome}</td>
                                        <td>{dataExibicao}</td>
                                        <td><Chip size="small" label={n.sentimento_score?.toFixed(1)} sx={{
                                          bgcolor: n.sentimento_score >= 7 ? 'rgba(0,151,57,0.15)' : n.sentimento_score <= 4 ? 'rgba(237,139,0,0.15)' : 'rgba(79,129,189,0.15)',
                                          color: n.sentimento_score >= 7 ? brandPalette.verde : n.sentimento_score <= 4 ? brandPalette.laranja : brandPalette.azulClaro,
                                          fontWeight: 700
                                        }} /></td>
                                        <td style={{ fontSize: '0.85rem', color: '#666' }}>{n.resumo_forense}</td>
                                        <td><Button size="small" href={n.link} target="_blank">Ver</Button></td>
                                    </tr>
                                );
                            })}
                        </tbody>
                    </table>
                </Box>
          </Paper>

          <Box sx={{ my: 4 }}>
            <Button
              variant="contained"
              size="large"
              fullWidth
              onClick={gerarDossie}
              disabled={loadingRelatorio || !dadosAnalise}
              startIcon={
                loadingRelatorio ? (
                  <CircularProgress size={30} color="inherit" />
                ) : (
                  <Box
                    component="img"
                    src="/expressions/antunes_angry.png"
                    alt="IA Antunes"
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
                bgcolor: brandPalette.verde,
                '&:hover': { bgcolor: '#007a30' },
                py: 3,
                px: 4,
                fontSize: '1.2rem',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'flex-start',
                textAlign: 'left',
                borderRadius: 4,
                boxShadow: 3,
                textTransform: 'none'
              }}
            >
              {loadingRelatorio 
                ? 'A Inteligência IA está processando o dossiê...' 
                : `Acione a Inteligência Artificial para gerar o Dossiê de Inteligência IA do parlamentar ${dadosAnalise?.profile?.nome || parlamentoSelecionado}`}
            </Button>
            {relatorioIA && (
              <Paper elevation={0} sx={{
                mt: 2, p: 4, borderRadius: 4,
                bgcolor: '#F7F9FC',
                border: `1.5px solid ${brandPalette.azulClaro}30`,
                '& p': {
                  fontFamily: 'Montserrat, sans-serif',
                  fontSize: '1rem',
                  lineHeight: 1.8,
                  color: '#1A2A3A',
                  mb: 2,
                  mt: 0,
                },
                '& strong': {
                  color: brandPalette.azul,
                  fontWeight: 700,
                },
                '& h1, & h2, & h3': {
                  fontFamily: 'Montserrat, sans-serif',
                  color: brandPalette.azul,
                  fontWeight: 700,
                  mt: 2,
                  mb: 1,
                },
              }}>
                <Box sx={{
                  display: 'flex', alignItems: 'center', gap: 1.5, mb: 2.5,
                  pb: 2, borderBottom: `2px solid ${brandPalette.azulClaro}30`
                }}>
                  <Box component="img"
                    src="/expressions/antunes_angry.png"
                    alt="Antunes IA"
                    sx={{ height: 44, width: 44, borderRadius: '50%', objectFit: 'cover', objectPosition: 'center 15%', border: `2px solid ${brandPalette.azul}` }}
                  />
                  <Box>
                    <Typography sx={{ fontFamily: 'Montserrat', fontWeight: 700, fontSize: '0.85rem', color: brandPalette.azul, letterSpacing: '0.08em', textTransform: 'uppercase' }}>
                      Dossiê de Inteligência
                    </Typography>
                    <Typography sx={{ fontFamily: 'Montserrat', fontSize: '0.78rem', color: brandPalette.cinza }}>
                      Gerado por IA Antunes · {dadosAnalise?.profile?.nome || parlamentoSelecionado}
                    </Typography>
                  </Box>
                </Box>
                <ReactMarkdown
                  components={{
                    p: ({ children }) => (
                      <Typography component="p" sx={{ fontFamily: 'Montserrat, sans-serif', fontSize: '1rem', lineHeight: 1.8, color: '#1A2A3A', mb: 2 }}>
                        {children}
                      </Typography>
                    ),
                    strong: ({ children }) => (
                      <Box component="strong" sx={{ color: brandPalette.azul, fontWeight: 700 }}>{children}</Box>
                    ),
                    h1: ({ children }) => <Typography variant="h6" sx={{ fontFamily: 'Montserrat', fontWeight: 700, color: brandPalette.azul, mb: 1, mt: 2 }}>{children}</Typography>,
                    h2: ({ children }) => <Typography variant="subtitle1" sx={{ fontFamily: 'Montserrat', fontWeight: 700, color: brandPalette.azul, mb: 1, mt: 2 }}>{children}</Typography>,
                    h3: ({ children }) => <Typography variant="subtitle2" sx={{ fontFamily: 'Montserrat', fontWeight: 700, color: brandPalette.azulClaro, mb: 0.5, mt: 1.5 }}>{children}</Typography>,
                  }}
                >
                  {relatorioIA}
                </ReactMarkdown>
              </Paper>
            )}
          </Box>
        </Box>
      )}
    </Container>
  );
};

export default AuditoriaImprensaV2;
