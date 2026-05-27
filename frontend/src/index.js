import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { ThemeProvider, createTheme } from '@mui/material';
import CssBaseline from '@mui/material/CssBaseline';
import axios from 'axios';
import App from './App';

// Configuração global do axios para NUNCA fazer cache
axios.defaults.headers.common['Cache-Control'] = 'no-cache, no-store, must-revalidate';
axios.defaults.headers.common['Pragma'] = 'no-cache';
axios.defaults.headers.common['Expires'] = '0';

// Interceptor para adicionar timestamp em TODAS as requisições
axios.interceptors.request.use((config) => {
  const separator = config.url.includes('?') ? '&' : '?';
  config.url = `${config.url}${separator}_nocache=${Date.now()}`;
  return config;
});

const ThemedApp = () => {
  const theme = createTheme({
    palette: {
      mode: 'light',
      primary: { main: '#009739' },
      secondary: { main: '#003366' },
      warning: { main: '#FFF81C' },
      error: { main: '#ED8B00' },
      background: {
        default: '#FFFFFF',
        paper: '#FFFFFF',
      },
      text: {
        primary: '#003366',
        secondary: '#666666',
      },
    },
    typography: {
      fontFamily: '"Inter", "Roboto", "Helvetica", "Arial", sans-serif',
      h1: {
        fontFamily: '"Montserrat", sans-serif',
        fontWeight: 700,
        letterSpacing: '-0.03em',
        lineHeight: 1.05,
      },
      h2: {
        fontFamily: '"Montserrat", sans-serif',
        fontWeight: 700,
        letterSpacing: '-0.03em',
        lineHeight: 1.05,
      },
      h3: {
        fontFamily: '"Montserrat", sans-serif',
        fontWeight: 700,
        letterSpacing: '-0.02em',
        lineHeight: 1.1,
      },
      h4: {
        fontFamily: '"Montserrat", sans-serif',
        fontWeight: 700,
        letterSpacing: '-0.02em',
        lineHeight: 1.1,
      },
      h5: {
        fontFamily: '"Montserrat", sans-serif',
        fontWeight: 700,
        letterSpacing: '-0.01em',
      },
      h6: {
        fontFamily: '"Montserrat", sans-serif',
        fontWeight: 700,
      },
      body1: {
        fontFamily: '"Inter", sans-serif',
        fontWeight: 400,
      },
      body2: {
        fontFamily: '"Inter", sans-serif',
        fontWeight: 400,
      },
      caption: {
        fontFamily: '"Roboto Mono", monospace',
        fontWeight: 400,
      },
    },
    components: {
      MuiButton: {
        styleOverrides: {
          root: {
            borderRadius: 8,
            textTransform: 'none',
            fontWeight: 600,
          },
          contained: {
            backgroundColor: '#009739',
            '&:hover': {
              backgroundColor: '#007a2f',
            },
          },
        },
      },
      MuiAppBar: {
        styleOverrides: {
          root: {
            backgroundColor: '#003366',
          },
        },
      },
      MuiPaper: {
        styleOverrides: {
          root: {
            backgroundImage: 'none',
          },
        },
      },
    },
  });

  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <App />
    </ThemeProvider>
  );
};

const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(
  <React.StrictMode>
    <BrowserRouter>
      <ThemedApp />
    </BrowserRouter>
  </React.StrictMode>
);
