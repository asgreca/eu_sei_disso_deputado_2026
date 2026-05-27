import React from 'react';
import { Box, Paper, Grid, Avatar, Typography, Chip } from '@mui/material';
import { API_BASE_URL } from '../config';

// Fallback local — garante logo mesmo quando o backend retorna null
const PARTIDO_LOGOS_FALLBACK = {
  "AVANTE":       "https://commons.wikimedia.org/wiki/Special:FilePath/AVANTE_Brazil_Logo.png?width=250",
  "PT":           "https://commons.wikimedia.org/wiki/Special:FilePath/PT_(Brazil)_logo_2021.svg?width=250",
  "MDB":          "https://commons.wikimedia.org/wiki/Special:FilePath/Movimento_Democr%C3%A1tico_Brasileiro_(2017).svg?width=250",
  "PL":           "https://commons.wikimedia.org/wiki/Special:FilePath/Partido_Liberal_(Brazil)_logo.svg?width=250",
  "PP":           "https://commons.wikimedia.org/wiki/Special:FilePath/Progressistas_(Brazil)_logo.svg?width=250",
  "PODE":         "https://commons.wikimedia.org/wiki/Special:FilePath/Logo_Podemos_20.png?width=250",
  "PODEMOS":      "https://commons.wikimedia.org/wiki/Special:FilePath/Logo_Podemos_20.png?width=250",
  "PDT":          "https://commons.wikimedia.org/wiki/Special:FilePath/LogoPDT.png?width=250",
  "PSB":          "https://commons.wikimedia.org/wiki/Special:FilePath/Logo_of_the_Brazilian_Socialist_Party_(wordmark_color).svg?width=250",
  "PSD":          "https://commons.wikimedia.org/wiki/Special:FilePath/PSD_Brazil_logo.svg?width=250",
  "PSDB":         "https://commons.wikimedia.org/wiki/Special:FilePath/Logo_of_the_Brazilian_Social_Democracy_Party_(2023).svg?width=250",
  "UNIÃO":        "https://commons.wikimedia.org/wiki/Special:FilePath/Uniao_Brasil.png?width=250",
  "UNIAO":        "https://commons.wikimedia.org/wiki/Special:FilePath/Uniao_Brasil.png?width=250",
  "REPUBLICANOS": "https://commons.wikimedia.org/wiki/Special:FilePath/Republicanos_(Brazil)_logo.svg?width=250",
  "PSOL":         "https://commons.wikimedia.org/wiki/Special:FilePath/Logo_PSOL_roxo.svg?width=250",
  "PCDOB":        "https://commons.wikimedia.org/wiki/Special:FilePath/Pc_do_b_logo.svg?width=250",
  "PC DO B":      "https://commons.wikimedia.org/wiki/Special:FilePath/Pc_do_b_logo.svg?width=250",
  "SOLIDARIEDADE":"https://commons.wikimedia.org/wiki/Special:FilePath/Solidariedade_(partido_pol%C3%ADtico)_logo.svg?width=250",
  "NOVO":         "https://commons.wikimedia.org/wiki/Special:FilePath/NOVO_Logo_2023.png?width=250",
  "CIDADANIA":    "https://commons.wikimedia.org/wiki/Special:FilePath/Cidadania_(partido_pol%C3%ADtico)_logo.svg?width=250",
  "PV":           "https://commons.wikimedia.org/wiki/Special:FilePath/Logo_Partido_Verde.svg?width=250",
  "REDE":         "https://commons.wikimedia.org/wiki/Special:FilePath/Rede_Sustentabilidade_logo.svg?width=250",
  "PRD":          "https://commons.wikimedia.org/wiki/Special:FilePath/Partido_Renova%C3%A7%C3%A3o_Democr%C3%A1tica_logo.svg?width=250",
  "AGIR":         "https://commons.wikimedia.org/wiki/Special:FilePath/Agir_(partido_pol%C3%ADtico_brasileiro)_logo.svg?width=250",
  "DC":           "https://commons.wikimedia.org/wiki/Special:FilePath/Democracia_Crist%C3%A3_Logo.png?width=250",
  "PMB":          "https://commons.wikimedia.org/wiki/Special:FilePath/PMB.png?width=250",
  "PMN":          "https://commons.wikimedia.org/wiki/Special:FilePath/PMN_Brazil.png?width=250",
  "PROS":         "https://commons.wikimedia.org/wiki/Special:FilePath/PROS_Logo.svg?width=250",
  "PTB":          "https://commons.wikimedia.org/wiki/Special:FilePath/PTB_logo.svg?width=250",
  "SD":           "https://commons.wikimedia.org/wiki/Special:FilePath/Solidariedade_(partido_pol%C3%ADtico)_logo.svg?width=250",
};

const proxyImg = (url) =>
  url ? `${API_BASE_URL}/api/proxy/imagem?url=${encodeURIComponent(url)}` : '';

/** Resolve logo do partido: prioriza mapa curado, depois prop do backend */
const resolvePartidoLogo = (partidoLogo, partido) => {
  const sigla = (partido || '').toUpperCase().trim();
  const url = PARTIDO_LOGOS_FALLBACK[sigla] || partidoLogo || '';
  return url ? proxyImg(url) : '';
};

const ParlamentarHeader = ({ foto, nome, partido, estado, partidoLogo, estadoFlag, rubrica }) => {
  const partidoLogoSrc = resolvePartidoLogo(partidoLogo, partido);
  const estadoFlagSrc  = estadoFlag ? proxyImg(estadoFlag) : '';

  return (
    <Paper elevation={3} sx={{ p: 4, mb: 4, bgcolor: '#FFFFFF', borderRadius: 4, border: '1px solid #e0e0e0' }}>
      <Grid container spacing={3} alignItems="center">
        <Grid item xs={12} md={2} sx={{ display: 'flex', justifyContent: 'center' }}>
          <Avatar
            src={foto}
            alt={nome}
            sx={{ width: 140, height: 140, border: '4px solid #009739', boxShadow: '0 4px 12px rgba(0,0,0,0.1)' }}
          >
            {nome?.[0] || '?'}
          </Avatar>
        </Grid>

        <Grid item xs={12} md={7}>
          <Typography variant="h3" fontWeight="bold" sx={{ color: '#003366', letterSpacing: '-0.5px' }}>
            {nome}
          </Typography>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, mt: 2 }}>
            {partido && (
              <Chip
                avatar={partidoLogoSrc ? <Avatar src={partidoLogoSrc} /> : undefined}
                label={partido}
                sx={{ bgcolor: '#E8F5E9', color: '#2E7D32', fontWeight: 'bold', px: 0.5, fontSize: '0.9rem' }}
              />
            )}
            {estado && (
              <Chip
                avatar={estadoFlagSrc ? <Avatar src={estadoFlagSrc} /> : undefined}
                label={estado}
                sx={{ bgcolor: '#E3F2FD', color: '#1565C0', fontWeight: 'bold', px: 0.5, fontSize: '0.9rem' }}
              />
            )}
          </Box>
          {rubrica && (
            <Typography variant="body1" sx={{ mt: 1, color: '#444', fontWeight: 600 }}>
              {rubrica}
            </Typography>
          )}
        </Grid>

        <Grid item xs={12} md={3} sx={{ display: 'flex', justifyContent: { xs: 'center', md: 'flex-end' }, alignItems: 'center' }}>
          <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2 }}>
            {partidoLogoSrc && (
              <Box
                component="img"
                src={partidoLogoSrc}
                alt={`Logo ${partido || 'Partido'}`}
                sx={{ height: 70, width: 'auto', maxWidth: 140, objectFit: 'contain', filter: 'drop-shadow(0 2px 4px rgba(0,0,0,0.1))' }}
                onError={(e) => { e.target.style.display = 'none'; }}
              />
            )}
            {estadoFlagSrc && (
              <Box
                component="img"
                src={estadoFlagSrc}
                alt={`Bandeira ${estado || ''}`}
                sx={{ height: 40, width: 'auto', borderRadius: '4px', boxShadow: '0 2px 8px rgba(0,0,0,0.15)' }}
                onError={(e) => { e.target.style.display = 'none'; }}
              />
            )}
          </Box>
        </Grid>
      </Grid>
    </Paper>
  );
};

export default ParlamentarHeader;
