import React, { useState, useEffect } from 'react';
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
  useCurrentParty = false
}) => {
  const [estados, setEstados] = useState(ESTADOS_BR);
  const [partidos, setPartidos] = useState([]);
  const [partidosAtuais, setPartidosAtuais] = useState([]);
  const [parlamentares, setParlamentares] = useState([]);
  const [comissoes, setComissoes] = useState([]);
  const [despesas, setDespesas] = useState([]);

  const [loading, setLoading] = useState({
    estados: false, partidos: false, partidosAtuais: false,
    parlamentares: false, despesas: false, comissoes: false,
  });
  const setL = (key, val) => setLoading(prev => ({ ...prev, [key]: val }));

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
    setL('estados', true);
    try {
      let url = `${API_BASE_URL}/api/filtros/estados`;
      if (sourceType === 'conformidade') url = `${API_BASE_URL}/api/filtros/conformidade`;
      else if (sourceType === 'passagens') url = `${API_BASE_URL}/api/filtros/estados?source=passagens`;
      const response = await fetch(url, { headers: API_HEADERS });
      if (!response.ok) throw new Error('Erro na carga de estados');
      const data = await response.json();
      const estadosList = data.estados || data || [];
      setEstados(Array.isArray(estadosList) ? estadosList : []);
    } catch (error) {
      setEstados(ESTADOS_BR);
    } finally {
      setL('estados', false);
    }
  };

  const loadPartidos = async (estado) => {
    setL('partidos', true);
    try {
      let url = '';
      if (sourceType === 'conformidade') url = `${API_BASE_URL}/api/filtros/conformidade?uf=${estado || ''}`;
      else if (sourceType === 'passagens') url = `${API_BASE_URL}/api/filtros/partidos?source=passagens&estado=${estado && estado !== 'Todos' ? encodeURIComponent(estado) : ''}`;
      else { url = `${API_BASE_URL}/api/filtros/partidos?estado=${estado || ''}`; if (useCurrentParty) url += `&atual=true`; }
      const response = await fetch(url, { headers: API_HEADERS });
      if (!response.ok) throw new Error('Erro na carga de partidos');
      const data = await response.json();
      setPartidos(Array.isArray(data.partidos || data) ? (data.partidos || data) : []);
    } catch (error) {
      console.error('❌ Erro ao carregar partidos:', error);
    } finally {
      setL('partidos', false);
    }
  };

  const loadParlamentares = async (estado, partido) => {
    setL('parlamentares', true);
    try {
      let url = '';
      if (sourceType === 'conformidade') url = `${API_BASE_URL}/api/filtros/conformidade?uf=${estado || ''}&partido=${partido || ''}`;
      else if (sourceType === 'emendas') { const p = new URLSearchParams(); if (estado && estado !== 'Todos') p.append('estado', estado); if (partido && partido !== 'Todos') p.append('partido', partido); url = `${API_BASE_URL}/api/emendas/parlamentares?${p.toString()}`; }
      else if (sourceType === 'passagens') { const p = new URLSearchParams(); p.append('source', 'passagens'); if (estado && estado !== 'Todos') p.append('estado', estado); if (partido && partido !== 'Todos') p.append('partido', partido); url = `${API_BASE_URL}/api/filtros/parlamentares?${p.toString()}`; }
      else { let q = '/api/filtros/parlamentares?'; if (estado && estado !== 'Todos') q += `estado=${estado}&`; if (partido && partido !== 'Todos') q += `${useCurrentParty ? 'partido_atual' : 'partido'}=${encodeURIComponent(partido)}&`; url = `${API_BASE_URL}${q}`; }
      const response = await fetch(url, { headers: API_HEADERS });
      if (!response.ok) throw new Error('Erro na carga de parlamentares');
      const data = await response.json();
      const list = data.parlamentares || data || [];
      const unique = new Map();
      (Array.isArray(list) ? list : []).forEach(p => { const nome = p.nome || p.nomeParlamentar || p; if (nome && !unique.has(nome)) unique.set(nome, { label: nome, value: nome, ...p }); });
      setParlamentares(Array.from(unique.values()));
    } catch (error) {
      console.error('❌ Erro ao carregar parlamentares:', error);
    } finally {
      setL('parlamentares', false);
    }
  };

  const loadParlamentaresDuckDB = async (estado, partidoAtual, partidoEleicao) => {
    setL('parlamentares', true);
    try {
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

      setParlamentares(mapped);
    } catch (error) {
      console.error('❌ Erro ao carregar parlamentares do DuckDB:', error);
    } finally {
      setL('parlamentares', false);
    }
  };

  const loadPartidosAtuais = async (estado, partidoEleicao, parlamentar) => {
    setL('partidosAtuais', true);
    try {
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
      setL('partidosAtuais', false);
    }
  };

  const loadDespesas = async (estado, partido, parlamentar) => {
    setL('despesas', true);
    try {
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
      setDespesas([]);
    } finally {
      setL('despesas', false);
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
    setL('comissoes', true);
    try {
      const url = parlamentar && parlamentar !== 'Todos'
        ? `/api/filtros/comissoes?parlamentar=${encodeURIComponent(parlamentar)}`
        : `/api/filtros/comissoes`;
      const response = await axios.get(url, { headers: API_HEADERS });
      const list = response.data.comissoes || response.data || [];
      setComissoes((Array.isArray(list) ? list : []).map(c => ({
        label: c.comissao || c.label || c,
        value: c.comissao || c.value || c
      })));
    } catch (error) {
      setComissoes([]);
    } finally {
      setL('comissoes', false);
    }
  };

  const iconMap = {
    estado: '📍', partido: '🏛️', partidoAtual: '🏢',
    parlamentar: '👤', comissao: '🏛️', despesa: '💰'
  };
  const labelMap = {
    estado: 'Estado',
    partido: useCurrentParty ? 'Partido Atual' : 'Partido (Eleição)',
    partidoAtual: 'Partido Atual',
    parlamentar: 'Parlamentar',
    comissao: 'Comissão',
    despesa: 'Tipo de Despesa'
  };
  const loadingKeyMap = {
    estado: 'estados', partido: 'partidos', partidoAtual: 'partidosAtuais',
    parlamentar: 'parlamentares', comissao: 'comissoes', despesa: 'despesas'
  };
  const itemsMap = {
    estado: estados, partido: partidos, partidoAtual: partidosAtuais,
    parlamentar: parlamentares, comissao: comissoes, despesa: despesas
  };

  const renderSelect = (field, items, value, onChange) => {
    const isLoading = loading[loadingKeyMap[field] || field];
    const label = `${iconMap[field]} ${labelMap[field]}`;
    return (
      <FormControl fullWidth disabled={isLoading} sx={{ position: 'relative' }}>
        <InputLabel id={`filter-${field}-label`}>{label}</InputLabel>
        <Select
          labelId={`filter-${field}-label`}
          value={value}
          label={label}
          onChange={onChange}
          sx={{ backgroundColor: '#FFFFFF', borderRadius: '8px' }}
        >
          {isLoading
            ? <MenuItem disabled value="">
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, color: '#546e7a', fontSize: '14px' }}>
                  <CircularProgress size={13} thickness={5} sx={{ color: '#546e7a' }} />
                  Carregando...
                </Box>
              </MenuItem>
            : [
                <MenuItem key="todos" value="Todos">Todos</MenuItem>,
                ...items.map((opt) => (
                  <MenuItem key={getOptionValue(opt)} value={getOptionValue(opt)}>
                    {getOptionLabel(opt)}
                  </MenuItem>
                ))
              ]
          }
        </Select>
        {isLoading && (
          <CircularProgress
            size={16}
            thickness={5}
            sx={{
              position: 'absolute', right: 36, top: '50%',
              transform: 'translateY(-50%)', color: '#546e7a', pointerEvents: 'none',
            }}
          />
        )}
      </FormControl>
    );
  };

  return (
    <Paper elevation={2} sx={{ p: 3, borderRadius: '12px', mb: 3 }}>
      <Typography variant="h6" sx={{ mb: 2, color: '#003366', fontWeight: 'bold' }}>
        Filtros Intercambiáveis
      </Typography>

      <Grid container spacing={2}>
        {fields.map((field) => (
          <Grid item xs={12} sm={6} md={3} key={field}>
            {renderSelect(
              field,
              itemsMap[field] || [],
              filters[field],
              (e) => handleFilterChange(field, e.target.value)
            )}
          </Grid>
        ))}

        {showComissao && (
          <Grid item xs={12} sm={6} md={3}>
            {renderSelect(
              'comissao',
              comissoes,
              filters.comissao,
              (e) => handleFilterChange('comissao', e.target.value)
            )}
          </Grid>
        )}
      </Grid>
    </Paper>
  );
};

export default FilterSelector;
