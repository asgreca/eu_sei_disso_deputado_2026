import React, { useEffect, useMemo, useRef, useState } from 'react';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import {
  Alert,
  Avatar,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  Grid,
  LinearProgress,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography,
} from '@mui/material';
import axios from '../config/axios';
import { API_HEADERS, handleApiError } from '../config';
import FilterSelector from '../components/FilterSelector';

const statCardSx = {
  height: '100%',
  borderRadius: '18px',
  backgroundColor: '#F8FAFC',
  border: '1px solid #E6ECF3',
  boxShadow: '0 10px 24px rgba(0, 51, 102, 0.08)',
};

const statCardContentSx = {
  height: '100%',
  display: 'flex',
  flexDirection: 'column',
  justifyContent: 'space-between',
  gap: 1.25,
};

const statTitleSx = {
  color: '#5B677A',
  fontWeight: 700,
  fontSize: { xs: '1rem', md: '1.15rem', lg: '1.2rem' },
  lineHeight: 1.3,
  overflowWrap: 'anywhere',
};

const statValueSx = {
  fontSize: 'clamp(2.05rem, 2.4vw, 2.9rem)',
  lineHeight: 1.05,
  fontWeight: 800,
  mt: 0.75,
  overflowWrap: 'anywhere',
  wordBreak: 'break-word',
  letterSpacing: '-0.03em',
  fontVariantNumeric: 'tabular-nums',
};

const miniVisualCircleSx = {
  width: 44,
  height: 44,
  minWidth: 44,
  borderRadius: '50%',
  backgroundColor: '#fff',
  border: '2px solid #D9E5F2',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  overflow: 'hidden',
  boxSizing: 'border-box',
  boxShadow: '0 4px 12px rgba(12, 60, 120, 0.10)',
};

const circularHeaderMediaSx = {
  bgcolor: 'white',
  width: 120,
  height: 120,
  minWidth: 120,
  maxWidth: 120,
  aspectRatio: '1 / 1',
  borderRadius: '50%',
  boxSizing: 'border-box',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  overflow: 'hidden',
  flex: '0 0 120px',
  p: 1.5,
};

const formatInt = (value) => Number(value || 0).toLocaleString('pt-BR');
const formatPercent = (value) => `${Number(value || 0).toLocaleString('pt-BR', { minimumFractionDigits: 1, maximumFractionDigits: 1 })}%`;
const normalizeName = (value) => String(value || '')
  .normalize('NFD')
  .replace(/[\u0300-\u036f]/g, '')
  .trim()
  .toUpperCase();

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

const pickFirstImageUrl = (...values) => {
  for (const value of values) {
    const normalized = normalizeCommonsFileUrl(value);
    if (normalized) return normalized;
  }
  return '';
};

const resolveLeaderElectionPartyLogo = (local, infoParlamentar) => {
  const leaderParty = normalizeName(local?.partido_deputado_dominante || local?.partido_dominante || '');
  const deputyElectionParty = normalizeName(infoParlamentar?.partido || '');
  const deputyCurrentParty = normalizeName(infoParlamentar?.partidoAtual || '');

  return pickFirstImageUrl(
    local?.logo_partido_deputado_dominante,
    local?.logo_partido_dominante,
    leaderParty && leaderParty === deputyElectionParty ? (local?.logo_partido_parlamentar || infoParlamentar?.logoPartido) : '',
    leaderParty && leaderParty === deputyCurrentParty ? (local?.logo_partido_atual_parlamentar || infoParlamentar?.logoPartido) : '',
  );
};

const buildPartidoLeituraText = (local, parlamentarNome) => {
  const nome = parlamentarNome || 'O deputado analisado';
  const partidoDominante = String(local?.partido_dominante || '').trim();
  const partidoAtualLider = String(local?.partido_atual_deputado_dominante || '').trim();
  const partidoParlamentarMinoritaria = Boolean(local?.partido_parlamentar_minoritaria);
  const deputadoLider = Boolean(local?.deputado_parlamentar_lider);

  if (deputadoLider && partidoParlamentarMinoritaria && partidoDominante) {
    const partidoAtualTrecho = partidoAtualLider && partidoAtualLider !== partidoDominante
      ? ` Hoje, o deputado que lidera este local está no ${partidoAtualLider}.`
      : '';
    return `Individualmente, ${nome} ficou em 1º neste local. No agregado partidário entre os deputados eleitos, porém, a legenda que mais somou votos foi ${partidoDominante}.${partidoAtualTrecho}`;
  }

  if (deputadoLider && !partidoParlamentarMinoritaria) {
    if (partidoDominante) {
      return `Individualmente, ${nome} ficou em 1º neste local, e sua legenda também foi a que mais somou votos entre os deputados eleitos.`;
    }
    return `Individualmente, ${nome} ficou em 1º neste local.`;
  }

  if (partidoDominante) {
    const partidoAtualTrecho = partidoAtualLider && partidoAtualLider !== partidoDominante
      ? ` O deputado líder do local hoje está no ${partidoAtualLider}.`
      : '';
    return `No agregado partidário entre os deputados eleitos, a legenda dominante neste local é ${partidoDominante}.${partidoAtualTrecho}`;
  }

  return 'Leitura partidária indisponível para este local.';
};

const ESTADO_BBOX = {
  AC: { latMin: -13.0, latMax: -5.0, lngMin: -76.0, lngMax: -64.0 },
  AL: { latMin: -12.5, latMax: -6.8, lngMin: -40.5, lngMax: -33.5 },
  AP: { latMin: -6.0, latMax: 7.0, lngMin: -56.8, lngMax: -49.0 },
  AM: { latMin: -12.0, latMax: 7.0, lngMin: -75.0, lngMax: -54.0 },
  BA: { latMin: -20.5, latMax: -7.0, lngMin: -48.0, lngMax: -35.0 },
  CE: { latMin: -10.0, latMax: -0.8, lngMin: -43.5, lngMax: -35.0 },
  DF: { latMin: -17.0, latMax: -14.0, lngMin: -49.0, lngMax: -46.0 },
  ES: { latMin: -22.5, latMax: -16.0, lngMin: -43.0, lngMax: -38.0 },
  GO: { latMin: -21.5, latMax: -12.0, lngMin: -55.0, lngMax: -44.0 },
  MA: { latMin: -12.5, latMax: 1.0, lngMin: -52.0, lngMax: -40.0 },
  MT: { latMin: -20.5, latMax: -5.0, lngMin: -63.0, lngMax: -48.0 },
  MS: { latMin: -25.0, latMax: -15.5, lngMin: -59.0, lngMax: -51.0 },
  MG: { latMin: -24.5, latMax: -12.5, lngMin: -53.0, lngMax: -38.0 },
  PA: { latMin: -10.5, latMax: 5.0, lngMin: -61.0, lngMax: -46.0 },
  PB: { latMin: -10.5, latMax: -4.5, lngMin: -40.0, lngMax: -33.0 },
  PR: { latMin: -28.5, latMax: -20.5, lngMin: -56.5, lngMax: -46.0 },
  PE: { latMin: -11.5, latMax: -5.0, lngMin: -42.5, lngMax: -32.5 },
  PI: { latMin: -13.0, latMax: -0.5, lngMin: -47.0, lngMax: -39.0 },
  RJ: { latMin: -25.0, latMax: -19.0, lngMin: -46.0, lngMax: -39.0 },
  RN: { latMin: -9.0, latMax: -3.0, lngMin: -39.5, lngMax: -33.0 },
  RS: { latMin: -35.5, latMax: -25.0, lngMin: -58.5, lngMax: -47.5 },
  RO: { latMin: -15.5, latMax: -5.5, lngMin: -67.0, lngMax: -58.0 },
  RR: { latMin: -1.5, latMax: 7.0, lngMin: -66.0, lngMax: -57.0 },
  SC: { latMin: -31.0, latMax: -23.0, lngMin: -55.0, lngMax: -46.0 },
  SP: { latMin: -27.0, latMax: -18.0, lngMin: -55.0, lngMax: -42.0 },
  SE: { latMin: -13.0, latMax: -8.0, lngMin: -39.5, lngMax: -35.0 },
  TO: { latMin: -14.0, latMax: -3.0, lngMin: -52.0, lngMax: -44.0 },
};

const pointInState = (lat, lng, estado) => {
  const bbox = ESTADO_BBOX[(estado || '').toUpperCase()];
  if (!bbox) return true;
  return lat >= bbox.latMin && lat <= bbox.latMax && lng >= bbox.lngMin && lng <= bbox.lngMax;
};

const pointInRing = (lat, lng, ring) => {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const xi = Number(ring[i][0]);
    const yi = Number(ring[i][1]);
    const xj = Number(ring[j][0]);
    const yj = Number(ring[j][1]);
    const intersect = ((yi > lat) !== (yj > lat))
      && (lng < ((xj - xi) * (lat - yi)) / ((yj - yi) || Number.EPSILON) + xi);
    if (intersect) inside = !inside;
  }
  return inside;
};

const pointInGeoJsonPolygon = (lat, lng, geometry) => {
  if (!geometry || !geometry.type || !geometry.coordinates) return false;
  if (geometry.type === 'Polygon') {
    const [outerRing, ...holes] = geometry.coordinates;
    if (!outerRing || !pointInRing(lat, lng, outerRing)) return false;
    return !holes.some((hole) => pointInRing(lat, lng, hole));
  }
  if (geometry.type === 'MultiPolygon') {
    return geometry.coordinates.some((polygon) => {
      const [outerRing, ...holes] = polygon;
      if (!outerRing || !pointInRing(lat, lng, outerRing)) return false;
      return !holes.some((hole) => pointInRing(lat, lng, hole));
    });
  }
  return false;
};

const createPartyIcon = (local, options = {}) => {
  const sigla = (local.partido_dominante || '?').toUpperCase();
  const logoUrl = options.imageUrl || local.logo_partido_dominante;
  const altText = options.altText || sigla;
  const html = `
    <div style="
      width: 50px;
      height: 50px;
      border-radius: 50%;
      background: #ffffff;
      border: 3px solid #0C4B8E;
      box-shadow: 0 8px 18px rgba(0, 51, 102, 0.28);
      display: flex;
      align-items: center;
      justify-content: center;
      overflow: hidden;
    ">
      ${
        logoUrl
          ? `<div style="width: 38px; height: 38px; border-radius: 50%; background: #ffffff; display: flex; align-items: center; justify-content: center; overflow: hidden; padding: 3px; box-sizing: border-box;">
               <img src="${logoUrl}" alt="${altText}" style="width: 100%; height: 100%; object-fit: cover; object-position: center center; display: block;" />
             </div>`
          : `<span style="font-size: 12px; font-weight: 800; color: #0C4B8E;">${sigla}</span>`
      }
    </div>
  `;

  return L.divIcon({
    className: 'party-zone-marker',
    html,
    iconSize: [50, 50],
    iconAnchor: [25, 25],
    popupAnchor: [0, -20],
  });
};

const MapaPartidario = () => {
  const [filters, setFilters] = useState({
    estado: '',
    partido: '',
    partidoAtual: '',
    parlamentar: '',
    parlamentarLabel: '',
  });
  const [selectedFilters, setSelectedFilters] = useState({
    estado: '',
    partido: '',
    partidoAtual: '',
    parlamentar: '',
    parlamentarLabel: '',
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [payload, setPayload] = useState(null);

  const mapContainerRef = useRef(null);
  const mapInstanceRef = useRef(null);

  const clearMapInstance = () => {
    if (mapInstanceRef.current) {
      mapInstanceRef.current.remove();
      mapInstanceRef.current = null;
    }
    if (mapContainerRef.current) {
      mapContainerRef.current.innerHTML = '';
    }
  };

  const loadMap = (locais) => {
    if (!mapContainerRef.current) return;

    clearMapInstance();

    const mapDiv = document.createElement('div');
    mapDiv.style.width = '100%';
    mapDiv.style.height = '680px';
    mapDiv.style.borderRadius = '16px';
    mapDiv.style.background = '#EAF2FB';
    mapContainerRef.current.appendChild(mapDiv);

    const map = L.map(mapDiv, {
      zoomControl: true,
      scrollWheelZoom: true,
    });
    mapInstanceRef.current = map;

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '&copy; OpenStreetMap',
      maxZoom: 18,
    }).addTo(map);

    const selectedEstado = (selectedFilters.estado || payload?.filtros?.estado || '').toUpperCase();
    const selectedPartido = (selectedFilters.partido || payload?.filtros?.partido || '').toUpperCase();
    const selectedPartidoAtual = (selectedFilters.partidoAtual || payload?.filtros?.partido_atual || '').toUpperCase();
    const selectedParlamentar = String(selectedFilters.parlamentar || payload?.filtros?.parlamentar || '').trim();
    const estadoPerimetro = payload?.estado_perimetro || null;
    const useParlamentarRecorte = selectedParlamentar && selectedParlamentar !== 'Todos';
    let validLocais = (locais || []).filter((item) => {
      if (!Number.isFinite(item?.lat) || !Number.isFinite(item?.lng)) return false;
      const lat = Number(item.lat);
      const lng = Number(item.lng);
      if (estadoPerimetro) {
        if (!pointInGeoJsonPolygon(lat, lng, estadoPerimetro)) return false;
      } else if (!pointInState(lat, lng, selectedEstado)) {
        return false;
      }
      if (!useParlamentarRecorte && selectedPartido && selectedPartido !== 'TODOS') {
        return String(item?.partido_dominante || '').trim().toUpperCase() === selectedPartido;
      }
      if (!useParlamentarRecorte && selectedPartidoAtual && selectedPartidoAtual !== 'TODOS') {
        return String(item?.partido_atual_deputado_dominante || '').trim().toUpperCase() === selectedPartidoAtual;
      }
      return true;
    });

    if (!validLocais.length) {
      mapDiv.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;font-size:1.1rem;color:#46627f;">Sem coordenadas válidas para o recorte selecionado.</div>';
      return;
    }

    if (estadoPerimetro) {
      const perimeterLayer = L.geoJSON(estadoPerimetro, {
        style: {
          color: '#0C4B8E',
          weight: 2,
          opacity: 0.55,
          fillOpacity: 0.03,
        },
      }).addTo(map);
      map.fitBounds(perimeterLayer.getBounds(), { padding: [24, 24] });
    } else {
      const bounds = L.latLngBounds(validLocais.map((item) => [item.lat, item.lng]));
      map.fitBounds(bounds, { padding: [36, 36] });
    }

    validLocais.forEach((local) => {
      const useParlamentarFace = selectedParlamentar && selectedParlamentar !== 'Todos' && Boolean(local?.deputado_parlamentar_lider);
      const selectedName = selectedFilters.parlamentarLabel || selectedParlamentar;
      const dominantName = local.deputado_dominante || '';
      const isTieAtTop = useParlamentarFace
        && Number(local?.gap_para_lider_votos) === 0
        && normalizeName(dominantName) !== normalizeName(selectedName);
      const selectedLogo = useParlamentarFace
        ? infoParlamentar?.foto
        : (selectedPartidoAtual && selectedPartidoAtual !== 'TODOS'
          ? (local.logo_partido_atual_deputado_dominante || local.logo_partido_dominante)
          : local.logo_partido_dominante);
      const selectedAlt = useParlamentarFace
        ? selectedName
        : (selectedPartidoAtual && selectedPartidoAtual !== 'TODOS'
          ? (local.partido_atual_deputado_dominante || local.partido_dominante || '?')
          : (local.partido_dominante || '?'));
      const marker = L.marker([local.lat, local.lng], {
        icon: createPartyIcon(local, {
          imageUrl: selectedLogo,
          altText: selectedAlt,
        }),
      }).addTo(map);

      const selectedDeputyBlock = local.votos_parlamentar
        ? [
            '<hr style="margin:8px 0;border:none;border-top:1px solid #dbe5f1;" />',
            `<strong>${selectedName}</strong>: ${formatInt(local.votos_parlamentar)} votos`,
            local.share_parlamentar !== null && local.share_parlamentar !== undefined ? `Share no recorte dos eleitos: ${formatPercent(local.share_parlamentar)}` : null,
            local.rank_parlamentar ? `Posição do deputado neste local: ${local.rank_parlamentar}º` : null,
            isTieAtTop ? `O deputado empatou em 1º neste local com ${dominantName}.` : null,
            Number(local.rank_parlamentar) === 1 && !isTieAtTop ? 'O deputado venceu este local.' : null,
            buildPartidoLeituraText(local, selectedName),
          ]
        : [];

      marker.bindPopup(
        [
          `<strong>${local.local_votacao || 'Local não informado'} · ${local.municipio_referencia}</strong>`,
          `Partido dominante: ${local.partido_dominante || 'N/D'}`,
          `Deputado líder: ${dominantName || 'N/D'}`,
          `Votos do partido: ${formatInt(local.votos_partido_dominante)}`,
          `Participação: ${formatPercent(local.share_partido_dominante)}`,
          ...selectedDeputyBlock,
        ].filter(Boolean).join('<br>')
      );
    });
  };

  useEffect(() => () => clearMapInstance(), []);

  useEffect(() => {
    if (payload?.locais?.length || payload?.zonas?.length) {
      loadMap(payload.locais || payload.zonas);
    } else {
      clearMapInstance();
    }
  }, [payload]);

  useEffect(() => {
    const parlamentar = String(filters.parlamentar || '').trim();
    if (!filters.estado || filters.estado === 'Todos' || !parlamentar || parlamentar === 'Todos') return;

    let cancelled = false;
    const resolveCurrentParty = async () => {
      try {
        const response = await axios.get('/api/mapa-partidario/zonas', {
          headers: API_HEADERS,
          timeout: 180000,
          params: {
            estado: filters.estado,
            parlamentar,
          },
        });

        if (cancelled) return;

        const resolvedCurrentParty = String(
          response?.data?.info_parlamentar?.partidoAtual
          || response?.data?.info_parlamentar?.partido_atual
          || ''
        ).trim();

        const resolvedElectionParty = String(
          response?.data?.info_parlamentar?.partido
          || response?.data?.info_parlamentar?.partido_eleicao
          || ''
        ).trim();

        setFilters((prev) => {
          const next = { ...prev };
          if (resolvedCurrentParty && resolvedCurrentParty !== prev.partidoAtual) {
            next.partidoAtual = resolvedCurrentParty;
          }
          if (resolvedElectionParty && resolvedElectionParty !== prev.partido) {
            next.partido = resolvedElectionParty;
          }
          return next;
        });
      } catch (err) {
        console.error('Erro ao resolver partido atual do parlamentar:', err);
      }
    };

    resolveCurrentParty();

    return () => {
      cancelled = true;
    };
  }, [filters.estado, filters.parlamentar]);

  const handleExecute = async () => {
    if (!filters.estado || filters.estado === 'Todos') return;

    setLoading(true);
    setError(null);
    setSelectedFilters(filters);

    try {
      const response = await axios.get('/api/mapa-partidario/zonas', {
        headers: API_HEADERS,
        timeout: 180000,
        params: {
          estado: filters.estado,
          parlamentar: filters.parlamentar || undefined,
          ...(filters.parlamentar && filters.parlamentar !== 'Todos'
            ? {}
            : {
                partido: filters.partido || undefined,
                partido_atual: filters.partidoAtual || undefined,
              }),
        },
      });
      setPayload(response.data);
    } catch (err) {
      setError(handleApiError(err));
    } finally {
      setLoading(false);
    }
  };

  const resumo = payload?.resumo || {};
  const infoParlamentar = payload?.info_parlamentar || null;
  const analiseParlamentar = payload?.analise_parlamentar || null;
  const parlamentarDisplayName = analiseParlamentar?.parlamentar || selectedFilters.parlamentarLabel || selectedFilters.parlamentar || 'O deputado analisado';
  const partidoLogoUrl = normalizeCommonsFileUrl(infoParlamentar?.logoPartido);
  const estadoFlagUrl = normalizeCommonsFileUrl(infoParlamentar?.estado_logo_url);

  const titleText = useMemo(() => {
    if (analiseParlamentar?.parlamentar) {
      return `Mapa Partidário do Território de ${analiseParlamentar.parlamentar}`;
    }
    return 'Mapa Partidário por Local de Votação';
  }, [analiseParlamentar]);

  return (
    <Box sx={{ px: { xs: 1, md: 2 }, pb: 6 }}>
      <Box sx={{ mb: 4 }}>
        <Typography variant="h2" sx={{ fontWeight: 800, color: '#0C3C78', mb: 1, fontSize: { xs: '2.2rem', md: '3.6rem' } }}>
          🗺️ Mapa Partidário dos Locais de Votação
        </Typography>
        <Typography variant="h6" sx={{ color: '#5B677A', maxWidth: 980, lineHeight: 1.5 }}>
          Veja, em cada escola, endereço ou área de votação, qual partido domina entre os deputados federais eleitos e, quando um deputado
          for escolhido, meça quão forte ele é frente aos demais vencedores exatamente nesse mesmo território.
        </Typography>
      </Box>

      <FilterSelector
        requireSelection={true}
        requireAll={true}
        onFiltersChange={setFilters}
        fields={['estado', 'partido', 'partidoAtual', 'parlamentar']}
      />

      <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, mb: 3, flexWrap: 'wrap' }}>
        <Button
          variant="contained"
          onClick={handleExecute}
          disabled={loading || !filters.estado || filters.estado === 'Todos' || !filters.partido || filters.partido === 'Todos' || !filters.parlamentar || filters.parlamentar === 'Todos'}
          sx={{
            borderRadius: '16px',
            px: 4,
            py: 1.6,
            backgroundColor: '#0F9D44',
            fontWeight: 800,
            boxShadow: '0 10px 24px rgba(15, 157, 68, 0.22)',
            '&:hover': { backgroundColor: '#0B7F36' },
          }}
        >
          Executar Mapa Partidário
        </Button>
        {selectedFilters.estado && (
          <Chip
            label={`Recorte atual: ${selectedFilters.estado}${selectedFilters.partido ? ` · eleição ${selectedFilters.partido}` : ''}${selectedFilters.partidoAtual ? ` · atual ${selectedFilters.partidoAtual}` : ''}${selectedFilters.parlamentarLabel ? ` · ${selectedFilters.parlamentarLabel}` : ''}`}
            sx={{ backgroundColor: '#E9F4FF', color: '#0C3C78', fontWeight: 700 }}
          />
        )}
      </Box>

      {loading && (
        <Paper elevation={0} sx={{ p: 3, mb: 3, borderRadius: '18px', border: '1px solid #DCE8F5', backgroundColor: '#F5FAFF' }}>
          <Typography sx={{ color: '#0C3C78', fontWeight: 700, mb: 1 }}>
            Consolidando o mapa partidário do estado e ranqueando os eleitos por local de votação/endereço.
          </Typography>
          <LinearProgress sx={{ height: 10, borderRadius: 999 }} />
        </Paper>
      )}

      {error && (
        <Alert severity="error" sx={{ mb: 3, borderRadius: '14px' }}>
          {error}
        </Alert>
      )}

      {payload && (
        <>
          {infoParlamentar && (
            <Paper sx={{ p: 4, mb: 3, borderRadius: '12px', bgcolor: '#003366', color: 'white' }}>
              <Grid container spacing={3} alignItems="center">
                <Grid item xs={12} md={3}>
                  {infoParlamentar.foto && (
                    <Box sx={{ bgcolor: 'white', borderRadius: '50%', p: 0.5, width: 148, height: 148, mx: 'auto', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                      <Avatar
                        src={infoParlamentar.foto}
                        sx={{ width: 140, height: 140, border: '4px solid #009739' }}
                      />
                    </Box>
                  )}
                </Grid>
                <Grid item xs={12} md={6}>
                  <Typography variant="h5" sx={{ fontWeight: 'bold', color: 'white', mb: 2 }}>
                    {infoParlamentar?.nome || analiseParlamentar?.parlamentar || 'N/A'}
                  </Typography>
                  <Box sx={{ display: 'flex', gap: 2, flexWrap: 'wrap' }}>
                    <Chip label={`Eleição: ${infoParlamentar?.partido || analiseParlamentar?.partido || 'N/A'}`} sx={{ backgroundColor: 'white', color: '#009739', fontWeight: 'bold' }} />
                    {(infoParlamentar?.partidoAtual || analiseParlamentar?.partido_atual) && (
                      <Chip label={`Atual: ${infoParlamentar?.partidoAtual || analiseParlamentar?.partido_atual}`} sx={{ backgroundColor: '#E9F4FF', color: '#0C3C78', fontWeight: 'bold' }} />
                    )}
                    <Chip label={infoParlamentar?.estado || selectedFilters.estado || 'N/A'} sx={{ backgroundColor: 'rgba(255,255,255,0.2)', color: 'white', fontWeight: 'bold' }} />
                  </Box>
                </Grid>
                <Grid item xs={12} md={3} sx={{ display: 'flex', gap: 2, justifyContent: 'center', alignItems: 'center' }}>
                  {partidoLogoUrl && (
                    <Box sx={circularHeaderMediaSx}>
                      <Box
                        component="img"
                        src={partidoLogoUrl}
                        alt={`Logo ${infoParlamentar?.partido || ''}`}
                        sx={{
                          width: '88%',
                          height: '88%',
                          display: 'block',
                          objectFit: 'contain',
                          objectPosition: 'center center',
                        }}
                      />
                    </Box>
                  )}
                  {estadoFlagUrl && (
                    <Box sx={circularHeaderMediaSx}>
                      <Box
                        component="img"
                        src={estadoFlagUrl}
                        alt={`Bandeira ${infoParlamentar?.estado || selectedFilters.estado || ''}`}
                        sx={{
                          width: '88%',
                          height: '88%',
                          display: 'block',
                          objectFit: 'contain',
                          objectPosition: 'center center',
                        }}
                      />
                    </Box>
                  )}
                </Grid>
              </Grid>
            </Paper>
          )}

          <Grid container spacing={2.5} sx={{ mb: 3 }}>
            <Grid item xs={12} md={3}>
              <Card sx={statCardSx}>
                <CardContent>
                  <Typography variant="h6" sx={{ color: '#5B677A', fontWeight: 700 }}>Locais Mapeados</Typography>
                  <Typography sx={{ fontSize: '3.2rem', fontWeight: 800, color: '#0C3C78', mt: 1 }}>{formatInt(resumo.locais_mapeados)}</Typography>
                </CardContent>
              </Card>
            </Grid>
            <Grid item xs={12} md={3}>
              <Card sx={statCardSx}>
                <CardContent>
                  <Typography variant="h6" sx={{ color: '#5B677A', fontWeight: 700 }}>Municípios Cobertos</Typography>
                  <Typography sx={{ fontSize: '3.2rem', fontWeight: 800, color: '#0F9D44', mt: 1 }}>{formatInt(resumo.municipios_cobertos)}</Typography>
                </CardContent>
              </Card>
            </Grid>
            <Grid item xs={12} md={3}>
              <Card sx={statCardSx}>
                <CardContent>
                  <Typography variant="h6" sx={{ color: '#5B677A', fontWeight: 700 }}>Partidos Representados</Typography>
                  <Typography sx={{ fontSize: '3.2rem', fontWeight: 800, color: '#F57C00', mt: 1 }}>{formatInt(resumo.partidos_representados)}</Typography>
                </CardContent>
              </Card>
            </Grid>
            <Grid item xs={12} md={3}>
              <Card sx={statCardSx}>
                <CardContent>
                  <Typography variant="h6" sx={{ color: '#5B677A', fontWeight: 700 }}>Partido com Mais Locais</Typography>
                  <Typography sx={{ fontSize: '2.5rem', fontWeight: 800, color: '#0C3C78', mt: 1 }}>
                    {resumo.partido_lider_geral || 'N/D'}
                  </Typography>
                  {resumo.partido_lider_geral_locais ? (
                    <Typography sx={{ color: '#5B677A', mt: 1 }}>
                      Lidera em {formatInt(resumo.partido_lider_geral_locais)} locais do estado.
                    </Typography>
                  ) : null}
                </CardContent>
              </Card>
            </Grid>
          </Grid>

          <Paper elevation={0} sx={{ p: 3, mb: 3, borderRadius: '20px', border: '1px solid #E3EBF5', boxShadow: '0 12px 28px rgba(0, 51, 102, 0.08)' }}>
            <Typography variant="h4" sx={{ fontWeight: 800, color: '#0C3C78', mb: 1 }}>
              {titleText}
            </Typography>
            <Typography sx={{ color: '#5B677A', mb: 3, maxWidth: 980 }}>
              Cada ponto representa um local de votação agregado por escola ou endereço. A marca exibida é a legenda que domina aquele
              território entre os deputados federais eleitos. O filtro de partido da eleição olha a legenda de 2022; o filtro de
              partido atual olha a legenda corrente do deputado líder daquele local. Quando um deputado é selecionado, o mapa passa a
              mostrar os locais em que ele realmente aparece com votos no estado, sem depender do partido atual para montar o recorte.
            </Typography>
            <Box ref={mapContainerRef} />
          </Paper>

          {analiseParlamentar && (
            <>
              <Paper elevation={0} sx={{ p: 3, mb: 3, borderRadius: '20px', border: '1px solid #E3EBF5', boxShadow: '0 12px 28px rgba(0, 51, 102, 0.08)' }}>
                <Typography variant="h4" sx={{ fontWeight: 800, color: '#0C3C78', mb: 1 }}>
                  Competição do Deputado no Mesmo Território
                </Typography>
                <Typography sx={{ color: '#5B677A', mb: 3, maxWidth: 1100 }}>
                  Este bloco responde quem domina o território analisado, quantos locais o deputado de interesse efetivamente lidera e
                  em quantos lugares sua legenda é minoritária frente ao partido predominante daquele endereço de votação.
                </Typography>

                <Box
                  sx={{
                    mb: 1,
                    display: 'grid',
                    gap: 2.5,
                    gridTemplateColumns: {
                      xs: '1fr',
                      sm: 'repeat(2, minmax(0, 1fr))',
                      xl: 'repeat(5, minmax(0, 1fr))',
                    },
                  }}
                >
                  <Card sx={statCardSx}>
                    <CardContent sx={statCardContentSx}>
                      <Typography sx={statTitleSx}>Locais com Presença</Typography>
                      <Typography sx={{ ...statValueSx, color: '#0C3C78' }}>{formatInt(analiseParlamentar.locais_com_presenca)}</Typography>
                      <Typography sx={{ color: '#5B677A', fontSize: { xs: '0.95rem', md: '0.98rem' }, lineHeight: 1.45 }}>
                        Locais em que o deputado apareceu com votos entre os eleitos do recorte.
                      </Typography>
                    </CardContent>
                  </Card>
                  <Card sx={statCardSx}>
                    <CardContent sx={statCardContentSx}>
                      <Typography sx={statTitleSx}>Locais Liderados</Typography>
                      <Typography sx={{ ...statValueSx, color: '#0F9D44' }}>{formatInt(analiseParlamentar.locais_liderados)}</Typography>
                      <Typography sx={{ color: '#5B677A', fontSize: { xs: '0.95rem', md: '0.98rem' }, lineHeight: 1.45 }}>
                        Locais em que ele ficou em 1º lugar individualmente.
                      </Typography>
                    </CardContent>
                  </Card>
                  <Card sx={statCardSx}>
                    <CardContent sx={statCardContentSx}>
                      <Typography sx={statTitleSx}>Votos no Recorte</Typography>
                      <Typography sx={{ ...statValueSx, color: '#F57C00' }}>{formatInt(analiseParlamentar.votos_no_recorte)}</Typography>
                      <Typography sx={{ color: '#5B677A', fontSize: { xs: '0.95rem', md: '0.98rem' }, lineHeight: 1.45 }}>
                        Soma dos votos do deputado nos locais em que ele lidera o território observado.
                      </Typography>
                    </CardContent>
                  </Card>
                  <Card sx={statCardSx}>
                    <CardContent sx={statCardContentSx}>
                      <Typography sx={statTitleSx}>Força Média no Local</Typography>
                      <Typography sx={{ ...statValueSx, color: '#0C3C78' }}>{formatPercent(analiseParlamentar.share_medio_no_recorte)}</Typography>
                      <Typography sx={{ color: '#5B677A', fontSize: { xs: '0.95rem', md: '0.98rem' }, lineHeight: 1.45 }}>
                        Participação média do deputado entre os votos dos eleitos nos locais em que ele lidera.
                      </Typography>
                    </CardContent>
                  </Card>
                  <Card sx={statCardSx}>
                    <CardContent sx={statCardContentSx}>
                      <Typography sx={statTitleSx}>Legenda Minoritária</Typography>
                      <Typography sx={{ ...statValueSx, color: '#B7791F' }}>{formatInt(analiseParlamentar.locais_partido_minoritaria)}</Typography>
                      <Typography sx={{ color: '#5B677A', fontSize: { xs: '0.95rem', md: '0.98rem' }, lineHeight: 1.45 }}>
                        Locais em que o deputado vence individualmente, mas sua legenda não é a que mais soma votos entre os eleitos.
                      </Typography>
                    </CardContent>
                  </Card>
                </Box>

                {analiseParlamentar.lider_no_territorio?.parlamentar && (
                  <Alert severity="info" sx={{ mt: 3, borderRadius: '14px' }}>
                    No recorte em que {analiseParlamentar.parlamentar} circula, o nome que mais soma votos entre os eleitos é{' '}
                    <strong>{analiseParlamentar.lider_no_territorio.parlamentar}</strong>
                    {analiseParlamentar.lider_no_territorio.partido ? ` (${analiseParlamentar.lider_no_territorio.partido})` : ''},
                    com {formatInt(analiseParlamentar.lider_no_territorio.votos)} votos agregados.
                  </Alert>
                )}
              </Paper>

              <Grid container spacing={3}>
                {/* Principais Competidores */}
                <Grid item xs={12} lg={5}>
                  <Paper elevation={0} sx={{ p: 3, borderRadius: '20px', border: '1px solid #E3EBF5', boxShadow: '0 12px 28px rgba(0, 51, 102, 0.08)', height: '100%' }}>
                    <Typography variant="h6" sx={{ fontWeight: 800, color: '#0C3C78', mb: 2 }}>
                      Principais Competidores no Mesmo Recorte
                    </Typography>
                    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                      {(analiseParlamentar.competidores || []).slice(0, 5).map((item, idx) => (
                        <Box key={`${item.parlamentar}-${item.partido}`} sx={{
                          display: 'flex', alignItems: 'center', gap: 1.5, p: 1.5,
                          borderRadius: '12px', bgcolor: idx === 0 ? '#EEF4FF' : '#F8FAFD',
                          border: '1px solid', borderColor: idx === 0 ? '#C7D9F8' : '#E8EFF8',
                        }}>
                          <Box sx={{
                            width: 28, height: 28, borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center',
                            bgcolor: idx === 0 ? '#0C3C78' : '#CBD5E1', flexShrink: 0,
                          }}>
                            <Typography sx={{ fontWeight: 800, color: '#fff', fontSize: '0.75rem' }}>{idx + 1}</Typography>
                          </Box>
                          <Box sx={{ flex: 1, minWidth: 0 }}>
                            <Typography sx={{ fontWeight: 700, color: '#0C3C78', fontSize: '0.85rem', lineHeight: 1.2, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                              {item.parlamentar}
                            </Typography>
                            <Typography sx={{ fontSize: '0.75rem', color: '#5B677A' }}>{item.partido || 'N/D'}</Typography>
                          </Box>
                          <Box sx={{ textAlign: 'right', flexShrink: 0 }}>
                            <Typography sx={{ fontWeight: 800, color: '#0C3C78', fontSize: '0.9rem' }}>{formatInt(item.votos)}</Typography>
                            <Typography sx={{ fontSize: '0.72rem', color: '#5B677A' }}>{formatInt(item.locais_presentes)} locais</Typography>
                          </Box>
                        </Box>
                      ))}
                    </Box>
                  </Paper>
                </Grid>

                {/* Top 5 Locais com Mais Folga — cards verticais */}
                <Grid item xs={12} lg={7}>
                  <Paper elevation={0} sx={{ p: 3, borderRadius: '20px', border: '1px solid #E3EBF5', boxShadow: '0 12px 28px rgba(0, 51, 102, 0.08)', height: '100%' }}>
                    <Typography variant="h6" sx={{ fontWeight: 800, color: '#0C3C78', mb: 2 }}>
                      Top 5 Locais em que o Deputado Liderou com Mais Folga
                    </Typography>
                    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5 }}>
                      {(analiseParlamentar.locais || []).slice(0, 5).map((item, idx) => {
                        const leaderPartyLogo = resolveLeaderElectionPartyLogo(item, infoParlamentar);
                        const logoPartido2022 = normalizeCommonsFileUrl(item.logo_partido_parlamentar || infoParlamentar?.logoPartido);
                        const logoPartidoAtual = normalizeCommonsFileUrl(item.logo_partido_atual_parlamentar || infoParlamentar?.logoPartido);
                        return (
                          <Box key={`${item.local_key}-${item.municipio_referencia}-${idx}`} sx={{
                            display: 'flex', gap: 2, p: 1.5, borderRadius: '14px',
                            bgcolor: '#F8FAFD', border: '1px solid #E3EBF5',
                            flexWrap: 'wrap',
                          }}>
                            {/* Local + Endereço + Município */}
                            <Box sx={{ flex: '1 1 180px', minWidth: 0 }}>
                              <Typography sx={{ fontWeight: 700, color: '#0C3C78', fontSize: '0.82rem', lineHeight: 1.3, mb: 0.25 }}>
                                {item.local_votacao}
                              </Typography>
                              {item.endereco && (
                                <Typography sx={{ fontSize: '0.72rem', color: '#7A8FA6', lineHeight: 1.2, mb: 0.25 }}>
                                  {item.endereco}
                                </Typography>
                              )}
                              <Chip label={item.municipio_referencia} size="small" sx={{ bgcolor: '#E3EBF5', color: '#0C3C78', fontWeight: 700, fontSize: '0.7rem', height: 20 }} />
                            </Box>

                            {/* 1º no local */}
                            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flex: '0 0 auto' }}>
                              <Avatar
                                src={item.foto_deputado_dominante || infoParlamentar?.foto || undefined}
                                alt={item.deputado_dominante || 'Líder'}
                                sx={{ width: 38, height: 38, border: '2px solid #0C4B8E' }}
                              />
                              <Box>
                                <Typography sx={{ fontWeight: 700, color: '#0C3C78', fontSize: '0.78rem', lineHeight: 1.2, maxWidth: 110, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                  {item.deputado_dominante || parlamentarDisplayName}
                                </Typography>
                                {/* Logos partido 2022 e atual */}
                                <Box sx={{ display: 'flex', gap: 0.75, mt: 0.25, alignItems: 'center' }}>
                                  <Box sx={{ ...miniVisualCircleSx, width: 26, height: 26 }}>
                                    {leaderPartyLogo ? (
                                      <Box component="img" src={leaderPartyLogo} sx={{ width: '80%', height: '80%', objectFit: 'contain' }} />
                                    ) : (
                                      <Typography sx={{ fontSize: '0.6rem', fontWeight: 800, color: '#0C3C78' }}>
                                        {item.partido_deputado_dominante || item.partido_dominante || '?'}
                                      </Typography>
                                    )}
                                  </Box>
                                  <Typography sx={{ fontSize: '0.68rem', color: '#7A8FA6' }}>2022</Typography>
                                  {logoPartido2022 && (
                                    <>
                                      <Box sx={{ ...miniVisualCircleSx, width: 26, height: 26 }}>
                                        <Box component="img" src={logoPartido2022} sx={{ width: '80%', height: '80%', objectFit: 'contain' }} />
                                      </Box>
                                      <Typography sx={{ fontSize: '0.68rem', color: '#7A8FA6' }}>atual</Typography>
                                    </>
                                  )}
                                </Box>
                              </Box>
                            </Box>

                            {/* Votos + Folga */}
                            <Box sx={{ textAlign: 'right', flex: '0 0 auto', ml: 'auto' }}>
                              <Typography sx={{ fontWeight: 800, color: '#0C3C78', fontSize: '0.9rem' }}>{formatInt(item.votos_parlamentar)}</Typography>
                              <Typography sx={{ fontSize: '0.7rem', color: '#5B677A' }}>votos</Typography>
                              <Typography sx={{ fontWeight: 800, color: '#0F9D44', fontSize: '0.88rem', mt: 0.5 }}>
                                +{formatInt(item.vantagem_sobre_segundo_votos)}
                              </Typography>
                              <Typography sx={{ fontSize: '0.68rem', color: '#5B677A' }}>
                                {item.deputado_segundo_colocado ? `sobre ${item.deputado_segundo_colocado.split(' ')[0]}` : 'folga'}
                              </Typography>
                            </Box>
                          </Box>
                        );
                      })}
                    </Box>
                  </Paper>
                </Grid>
              </Grid>
            </>
          )}
        </>
      )}
    </Box>
  );
};

export default MapaPartidario;
