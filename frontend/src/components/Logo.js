import React from 'react';
import { Box } from '@mui/material';

const Logo = ({ variant = 'horizontal', sx = {} }) => {
  const logoPath =
    variant === 'vertical' ? '/Eu_sei_disso_vertical.png' : '/Eu_sei_disso_horizontal.png';

  return (
    <Box
      component="img"
      src={logoPath}
      alt="Eu Sei Disso"
      sx={{
        maxHeight: '60px',
        width: 'auto',
        height: 'auto',
        ...sx,
      }}
    />
  );
};

export default Logo;



