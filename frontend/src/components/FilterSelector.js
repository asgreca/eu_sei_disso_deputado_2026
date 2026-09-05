import React, { useState, useEffect, useRef } from 'react';
import {
  Box,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Grid,
  Paper,
  Typography,
  CircularProgress,
  LinearProgress,
  Alert,
} from '@mui/material';
import axios from '../config/axios';
import { API_HEADERS, API_BASE_URL } from '../config';

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

const ESTADOS_BR = [
  'AC', 'AL', 'AP', 'AM', 'BA', 'CE', 'DF', 'ES', 'GO', 'MA', 'MT', 'MS',
  'MG', 'PA', 'PB', 'PR', 'PE', 'PI', 'RJ', 'RN', 'RS', 'RO', 'RR', 'SC',
  'SP', 'SE', 'TO',
];

const FilterSelector = ({
  onFiltersChange,
  fields = ['estado', 'partido', 'parlamentar'],
  showComissao = false,
  sourceType = 'default', // 'default', 'conformidade', 'passagens' ou 'emendas'
  useCurrentParty = false,
  requireSelection = false,
  requireAll = false,
}) => {
  const [estados, setEstados] = useState([]);
  const [partidos, setPartidos] = useState([]);
  const [partidosAtuais, setPartidosAtuais] = useState([]);
  const [parlamentares, setParlamentares] = useState([]);
  const [comissoes, setComissoes] = useState([]);
  const [despesas, setDespesas] = useState([]);

  const [loadingEstados, setLoadingEstados] = useState(false);
  const [loadingPartidos, setLoadingPartidos] = useState(false);
  const [loadingParlamentares, setLoadingParlamentares] = useState(false);
  // Evita condição de corrida: respostas de requisições antigas (ex.: a carga inicial sem
  // filtro) podem chegar depois de uma busca já filtrada e sobrescrever a lista com dados errados.
  const parlamentaresRequestId = useRef(0);
  const [loadingComissoes, setLoadingComissoes] = useState(false);
  const [loadingDespesas, setLoadingDespesas] = useState(false);

  const [filters, setFilters] = useState({
    estado: '',
    partido: '',
    partidoAtual: '',
    parlamentar: '',
    parlamentarLabel: '',
    comissao: '',
    despesa: ''
  });

  const getOptionValue = (option) => {
    if (option && typeof option === 'object') {
      return option.value ?? option.label ?? '';
    }
    return option ?? '';
  };

  const getOptionLabel = (option) => {
    if (option && typeof option === 'object') {
      return option.label ?? option.value ?? '';
    }
    return option ?? '';
  };

  useEffect(() => {
    loadEstados();
  }, []);

  const loadEstados = async () => {
    try {
      setLoadingEstados(true);
      console.log(`🔍 FilterSelector [${sourceType}]: Carregando estados...`);
      let url = `${API_BASE_URL}/api/filtros/estados`;
      if (sourceType === 'conformidade') {
        url = `${API_BASE_URL}/api/filtros/conformidade`;
      } else if (sourceType === 'passagens') {
        url = `${API_BASE_URL}/api/filtros/estados?source=passagens`;
      }

      const response = await fetch(url, { headers: API_HEADERS });
      if (!response.ok) throw new Error('Erro na carga de estados');

      const data = await response.json();
      const estadosList = data.estados || data || [];
      console.log(`✅ FilterSelector: ${estadosList.length} estados carregados.`);
      setEstados(Array.isArray(estadosList) ? estadosList : []);
    } catch (error) {
      console.error('❌ Erro ao carregar estados:', error);
      setEstados(ESTADOS_BR);
    } finally {
      setLoadingEstados(false);
    }
  };

  const loadPartidos = async (estado) => {
    try {
      setLoadingPartidos(true);
      console.log(`🔍 FilterSelector [${sourceType}]: Carregando partidos para ${estado}...`);

      let url = '';
      if (sourceType === 'conformidade') {
        url = `${API_BASE_URL}/api/filtros/conformidade?uf=${estado || ''}`;
      } else if (sourceType === 'passagens') {
        const estadoQuery = estado && estado !== 'Todos' ? encodeURIComponent(estado) : '';
        url = `${API_BASE_URL}/api/filtros/partidos?source=passagens&estado=${estadoQuery}`;
      } else {
        url = `${API_BASE_URL}/api/filtros/partidos?estado=${estado || ''}`;
        if (useCurrentParty) {
          url += `&atual=true`;
        }
      }

      const response = await fetch(url, { headers: API_HEADERS });
      if (!response.ok) throw new Error('Erro na carga de partidos');

      const data = await response.json();
      const partidosList = data.partidos || data || [];
      console.log(`✅ FilterSelector: ${partidosList.length} partidos carregados.`);
      setPartidos(Array.isArray(partidosList) ? partidosList : []);
    } catch (error) {
      console.error('❌ Erro ao carregar partidos:', error);
    } finally {
      setLoadingPartidos(false);
    }
  };

  const loadParlamentares = async (estado, partido) => {
    const requestId = ++parlamentaresRequestId.current;
    try {
      setLoadingParlamentares(true);
      console.log(`🔍 FilterSelector [${sourceType}]: Carregando parlamentares para ${estado} / ${partido}...`);

      let url = '';
      if (sourceType === 'conformidade') {
        url = `${API_BASE_URL}/api/filtros/conformidade?uf=${estado || ''}&partido=${partido || ''}`;
      } else if (sourceType === 'emendas') {
        const params = new URLSearchParams();
        if (estado && estado !== 'Todos') params.append('estado', estado);
        if (partido && partido !== 'Todos') params.append('partido', partido);
        url = `${API_BASE_URL}/api/emendas/parlamentares?${params.toString()}`;
      } else if (sourceType === 'passagens') {
        const params = new URLSearchParams();
        params.append('source', 'passagens');
        if (estado && estado !== 'Todos') params.append('estado', estado);
        if (partido && partido !== 'Todos') params.append('partido', partido);
        url = `${API_BASE_URL}/api/filtros/parlamentares?${params.toString()}`;
      } else {
        let queryPath = '/api/filtros/parlamentares?';
        if (estado && estado !== 'Todos') queryPath += `estado=${estado}&`;
        if (partido && partido !== 'Todos') {
          const param = useCurrentParty ? 'partido_atual' : 'partido';
          queryPath += `${param}=${encodeURIComponent(partido)}&`;
        }
        url = `${API_BASE_URL}${queryPath}`;
      }

      const response = await fetch(url, { headers: API_HEADERS });
      if (!response.ok) throw new Error('Erro na carga de parlamentares');
      
      const data = await response.json();
      const parlamentaresList = data.parlamentares || data || [];
      // Deduplicar por nome
      const uniqueParlamentares = new Map();
      (Array.isArray(parlamentaresList) ? parlamentaresList : []).forEach(p => {
        const nome = p.nome || p.nomeParlamentar || p;
        if (nome && !uniqueParlamentares.has(nome)) {
          uniqueParlamentares.set(nome, {
            label: nome,
            value: nome,
            ...p
          });
        }
      });

      const mapped = Array.from(uniqueParlamentares.values());

      // Descarta a resposta se já existe uma busca mais recente em andamento
      // (evita que uma requisição antiga, resolvida fora de ordem, sobrescreva a lista certa).
      if (requestId !== parlamentaresRequestId.current) {
        console.log(`⏭️ FilterSelector: resposta obsoleta de parlamentares descartada (req ${requestId}, atual ${parlamentaresRequestId.current}).`);
        return;
      }

      console.log(`✅ FilterSelector: ${mapped.length} parlamentares únicos carregados.`);
      setParlamentares(mapped);
    } catch (error) {
      console.error('❌ Erro ao carregar parlamentares:', error);
    } finally {
      if (requestId === parlamentaresRequestId.current) {
        setLoadingParlamentares(false);
      }
    }
  };

  const loadParlamentaresDuckDB = async (estado, partidoAtual, partidoEleicao) => {
    const requestId = ++parlamentaresRequestId.current;
    try {
      setLoadingParlamentares(true);
      let url = `${API_BASE_URL}/api/mapa-eleitoral/filtros?`;
      if (estado && estado !== 'Todos') url += `uf=${estado}&`;
      if (partidoAtual && partidoAtual !== 'Todos') url += `partido_atual=${encodeURIComponent(partidoAtual)}&`;
      if (partidoEleicao && partidoEleicao !== 'Todos') url += `partido_eleicao=${encodeURIComponent(partidoEleicao)}&`;

      const response = await fetch(url, { headers: API_HEADERS });
      if (!response.ok) throw new Error('Erro ao carregar parlamentares');
      const data = await response.json();
      const uniqueParls = [...new Set(data.parlamentares || [])];
      const mapped = uniqueParls.map(p => ({ label: p, value: p }));

      const selectedParlamentar = String(filters.parlamentarLabel || filters.parlamentar || '').trim();
      if (selectedParlamentar && !mapped.some((p) => getOptionValue(p) === selectedParlamentar)) {
        mapped.unshift({ label: selectedParlamentar, value: selectedParlamentar });
      }

      if (requestId !== parlamentaresRequestId.current) return;
      setParlamentares(mapped);
    } catch (error) {
      console.error('❌ Erro ao carregar parlamentares do DuckDB:', error);
    } finally {
      if (requestId === parlamentaresRequestId.current) {
        setLoadingParlamentares(false);
      }
    }
  };

  const loadPartidosAtuais = async (estado, partidoEleicao, parlamentar) => {
    try {
      setLoadingPartidos(true);
      let url = `${API_BASE_URL}/api/mapa-eleitoral/filtros?`;
      if (estado && estado !== 'Todos') url += `uf=${estado}&`;
      if (partidoEleicao && partidoEleicao !== 'Todos') url += `partido_eleicao=${encodeURIComponent(partidoEleicao)}`;
      
      const response = await fetch(url, { headers: API_HEADERS });
      if (!response.ok) throw new Error('Erro ao carregar partidos atuais');
      const data = await response.json();

      const currentParties = Array.isArray(data.partidos_atuais) ? [...data.partidos_atuais] : [];

      if (parlamentar && parlamentar !== 'Todos') {
        try {
          const detalhe = await fetch(
            `${API_BASE_URL}/api/mapa-partidario/zonas?estado=${encodeURIComponent(estado || '')}&parlamentar=${encodeURIComponent(parlamentar)}`,
            { headers: API_HEADERS }
          );
          if (detalhe.ok) {
            const detalheData = await detalhe.json();
            const partidoAtualReal = String(
              detalheData?.info_parlamentar?.partidoAtual
              || detalheData?.info_parlamentar?.partido_atual
              || ''
            ).trim();
            if (partidoAtualReal && !currentParties.includes(partidoAtualReal)) {
              currentParties.unshift(partidoAtualReal);
            }
          }
        } catch (innerError) {
          console.warn('⚠️ FilterSelector: falha ao resolver partido atual real do parlamentar:', innerError);
        }
      }

      setPartidosAtuais(currentParties);
    } catch (error) {
      console.error('❌ Erro ao carregar partidos atuais:', error);
    } finally {
      setLoadingPartidos(false);
    }
  };

  const loadDespesas = async (estado, partido, parlamentar) => {
    try {
      setLoadingDespesas(true);
      console.log(`🔍 FilterSelector: Carregando despesas para ${parlamentar}...`);
      let url = `/api/filtros/despesas-parlamentar?parlamentar=${encodeURIComponent(parlamentar || 'Todos')}`;
      if (estado && estado !== 'Todos') url += `&estado=${estado}`;
      if (partido && partido !== 'Todos') url += `&partido=${partido}`;

      const response = await axios.get(url, { headers: API_HEADERS });
      const despesasList = response.data.despesas || response.data || [];
      
      const mapped = (Array.isArray(despesasList) ? despesasList : [])
        .filter(d => !d.toUpperCase().includes("PASSAGEM AÉREA"))
        .map(d => ({
          label: MAPA_DESPESAS[d] || d,
          value: d
        }));

      console.log(`✅ FilterSelector: ${mapped.length} despesas carregadas.`);
      setDespesas(mapped);
    } catch (error) {
      console.error('❌ Erro ao carregar despesas:', error);
      setDespesas([]);
    } finally {
      setLoadingDespesas(false);
    }
  };

  useEffect(() => {
    if (fields.includes('partido') || fields.includes('partidoAtual')) {
      loadPartidos(filters.estado);
    }
    if (fields.includes('partidoAtual')) {
      loadPartidosAtuais(filters.estado, filters.partido, filters.parlamentar);
    }
  }, [filters.estado, filters.partido, filters.parlamentar]);

  useEffect(() => {
    if (fields.includes('parlamentar')) {
      if (fields.includes('partidoAtual')) {
        // Página do mapa eleitoral: busca parlamentares do DuckDB por partido atual e eleição
        loadParlamentaresDuckDB(filters.estado, filters.partidoAtual, filters.partido);
      } else {
        loadParlamentares(filters.estado, filters.partido || filters.partidoAtual);
      }
    }
  }, [filters.estado, filters.partido, filters.partidoAtual]);

  useEffect(() => {
    if (showComissao) {
      loadComissoes(filters.parlamentar);
    }
  }, [filters.parlamentar, showComissao]);

  useEffect(() => {
    if (fields.includes('despesa')) {
      loadDespesas(filters.estado, filters.partido || filters.partidoAtual, filters.parlamentar);
    }
  }, [filters.estado, filters.partido, filters.partidoAtual, filters.parlamentar, fields]);

  const handleFilterChange = (field, value) => {
    const newFilters = { ...filters, [field]: value };

    // Reset dependent filters
    if (field === 'estado') {
      newFilters.partido = '';
      newFilters.partidoAtual = '';
      newFilters.parlamentar = '';
      newFilters.parlamentarLabel = '';
      newFilters.comissao = '';
    } else if (field === 'partido') {
      newFilters.partidoAtual = '';
      newFilters.parlamentar = '';
      newFilters.parlamentarLabel = '';
      newFilters.comissao = '';
      newFilters.despesa = '';
    } else if (field === 'partidoAtual') {
      newFilters.comissao = '';
      newFilters.despesa = '';
    } else if (field === 'parlamentar') {
      const selectedParlamentar = parlamentares.find((parl) => getOptionValue(parl) === value);
      newFilters.parlamentarLabel = getOptionLabel(selectedParlamentar) || value;
      newFilters.comissao = '';
      newFilters.despesa = '';
    }

    setFilters(newFilters);
    onFiltersChange(newFilters);
  };

  const loadComissoes = async (parlamentar) => {
    try {
      setLoadingComissoes(true);
      console.log(`🔍 FilterSelector: Carregando comissões...`);
      const url = parlamentar && parlamentar !== 'Todos' 
        ? `/api/filtros/comissoes?parlamentar=${encodeURIComponent(parlamentar)}`
        : `/api/filtros/comissoes`;
        
      const response = await axios.get(url, { headers: API_HEADERS });
      const comissoesList = response.data.comissoes || response.data || [];
      
      const mapped = (Array.isArray(comissoesList) ? comissoesList : []).map(c => ({
        label: c.comissao || c.label || c,
        value: c.comissao || c.value || c
      }));

      console.log(`✅ FilterSelector: ${mapped.length} comissões carregadas.`);
      setComissoes(mapped);
    } catch (error) {
      console.error('❌ Erro ao carregar comissões:', error);
      setComissoes([]);
    } finally {
      setLoadingComissoes(false);
    }
  };

  const loadingMap = {
    estado: loadingEstados,
    partido: loadingPartidos,
    partidoAtual: loadingPartidos,
    parlamentar: loadingParlamentares,
    comissao: loadingComissoes,
    despesa: loadingDespesas,
  };

  const SpinnerIcon = () => (
    <CircularProgress size={18} thickness={4} sx={{ mr: 1, color: 'inherit', opacity: 0.6 }} />
  );

  const iconMap = {
    estado: '📍',
    partido: '🏛️',
    partidoAtual: '🏢',
    parlamentar: '👤',
    comissao: '🏛️',
    despesa: '💰'
  };

  const labelMap = {
    estado: 'Estado',
    partido: useCurrentParty ? 'Partido Atual' : 'Partido (Eleição)',
    partidoAtual: 'Partido Atual',
    parlamentar: 'Parlamentar',
    comissao: 'Comissão',
    despesa: 'Tipo de Despesa'
  };

  const isAnyLoading = loadingEstados || loadingPartidos || loadingParlamentares || loadingComissoes || loadingDespesas;
  const selectionFields = ['estado', 'partido', 'partidoAtual', 'parlamentar'];
  const hasSelection = selectionFields.some(f => filters[f] && filters[f] !== 'Todos');
  const hasAllSelection = ['estado', 'partido', 'parlamentar'].every(f => filters[f] && filters[f] !== 'Todos');
  const showSelectionWarning = requireSelection && !isAnyLoading && (requireAll ? !hasAllSelection : !hasSelection);

  return (
    <Paper elevation={2} sx={{ p: 3, borderRadius: '12px', mb: 3, position: 'relative', overflow: 'hidden' }}>
      {isAnyLoading && (
        <LinearProgress
          sx={{
            position: 'absolute', top: 0, left: 0, right: 0,
            height: 3,
            borderRadius: '12px 12px 0 0',
            '& .MuiLinearProgress-bar': { backgroundColor: '#1976d2' },
            backgroundColor: 'rgba(25, 118, 210, 0.15)',
          }}
        />
      )}
      <Typography variant="h6" sx={{ mb: 2, color: '#003366', fontWeight: 'bold' }}>
        Filtros Intercambiáveis
      </Typography>

      <Grid container spacing={2}>
        {fields.map((field) => (
          <Grid item xs={12} sm={6} md={3} key={field}>
            <FormControl fullWidth>
              <InputLabel id={`filter-${field}-label`}>
                {`${iconMap[field]} ${labelMap[field]}`}
              </InputLabel>
              <Select
                labelId={`filter-${field}-label`}
                id={`filter-${field}`}
                value={filters[field]}
                label={`${iconMap[field]} ${labelMap[field]}`}
                onChange={(e) => handleFilterChange(field, e.target.value)}
                disabled={loadingMap[field]}
                IconComponent={loadingMap[field] ? SpinnerIcon : undefined}
                sx={{
                  backgroundColor: '#FFFFFF',
                  borderRadius: '8px',
                }}
              >
                <MenuItem value="Todos">Todos</MenuItem>
                {field === 'estado' && estados.map((est) => (
                  <MenuItem key={getOptionValue(est)} value={getOptionValue(est)}>{getOptionLabel(est)}</MenuItem>
                ))}
                {field === 'partido' && partidos.map((part) => (
                  <MenuItem key={getOptionValue(part)} value={getOptionValue(part)}>{getOptionLabel(part)}</MenuItem>
                ))}
                {field === 'partidoAtual' && partidosAtuais.map((part) => (
                  <MenuItem key={getOptionValue(part)} value={getOptionValue(part)}>{getOptionLabel(part)}</MenuItem>
                ))}
                {field === 'parlamentar' && parlamentares.map((parl) => (
                  <MenuItem key={getOptionValue(parl)} value={getOptionValue(parl)}>{getOptionLabel(parl)}</MenuItem>
                ))}
                {field === 'despesa' && despesas.map((desp) => (
                  <MenuItem key={getOptionValue(desp)} value={getOptionValue(desp)}>{getOptionLabel(desp)}</MenuItem>
                ))}
              </Select>
            </FormControl>
          </Grid>
        ))}

        {showComissao && (
          <Grid item xs={12} sm={6} md={3}>
            <FormControl fullWidth>
              <InputLabel id="filter-comissao-label">
                🏛️ Comissão
              </InputLabel>
              <Select
                labelId="filter-comissao-label"
                id="filter-comissao"
                value={filters.comissao}
                label="🏛️ Comissão"
                onChange={(e) => handleFilterChange('comissao', e.target.value)}
                disabled={loadingComissoes}
                IconComponent={loadingComissoes ? SpinnerIcon : undefined}
                sx={{
                  backgroundColor: '#FFFFFF',
                  borderRadius: '8px',
                }}
              >
                <MenuItem value="Todos">Todos</MenuItem>
                {comissoes.map((com) => (
                  <MenuItem key={getOptionValue(com)} value={getOptionValue(com)}>
                    {getOptionLabel(com)}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
          </Grid>
        )}
      </Grid>

      {showSelectionWarning && (
        <Alert severity="warning" sx={{ mt: 2, borderRadius: '8px' }}>
          {requireAll
            ? 'Selecione Estado, Partido e Parlamentar para continuar.'
            : 'Selecione pelo menos um filtro — Estado, Partido ou Parlamentar — antes de executar.'}
        </Alert>
      )}
    </Paper>
  );
};

export default FilterSelector;
