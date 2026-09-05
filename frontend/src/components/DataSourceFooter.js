import React from 'react';
import { Box, Typography, Divider, Chip } from '@mui/material';
import OpenInNewIcon from '@mui/icons-material/OpenInNew';

const SOURCE_STYLES = {
  camara:  { color: '#003366', bg: '#e8eef5' },
  tse:     { color: '#7B1FA2', bg: '#f3e5f5' },
  receita: { color: '#1B5E20', bg: '#e8f5e9' },
  cgu:     { color: '#BF360C', bg: '#fbe9e7' },
  stf:     { color: '#E65100', bg: '#fff3e0' },
  openai:  { color: '#555', bg: '#f5f5f5' },
};

const SourceLink = ({ label, href, type = 'camara' }) => {
  const s = SOURCE_STYLES[type] || SOURCE_STYLES.camara;
  return (
    <Box
      component="a"
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      sx={{
        display: 'inline-flex', alignItems: 'center', gap: 0.4,
        color: s.color, bgcolor: s.bg,
        px: 1.2, py: 0.4, borderRadius: 2,
        fontSize: '0.72rem', fontWeight: 600,
        textDecoration: 'none',
        border: `1px solid ${s.color}22`,
        '&:hover': { textDecoration: 'underline', opacity: 0.85 },
        transition: 'opacity 0.15s',
      }}
    >
      {label}
      <OpenInNewIcon sx={{ fontSize: '0.7rem' }} />
    </Box>
  );
};

/**
 * sources: array de { label, href, type }
 * note: string opcional com observação extra
 */
export default function DataSourceFooter({ sources = [], note }) {
  if (!sources.length) return null;
  return (
    <Box sx={{ mt: 5, mb: 2 }}>
      <Divider sx={{ mb: 2 }} />
      <Box sx={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 1.5 }}>
        <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 600, mr: 0.5 }}>
          🔗 Fontes:
        </Typography>
        {sources.map((s, i) => (
          <SourceLink key={i} label={s.label} href={s.href} type={s.type} />
        ))}
      </Box>
      {note && (
        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1, lineHeight: 1.6 }}>
          {note}
        </Typography>
      )}
    </Box>
  );
}
