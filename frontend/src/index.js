import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { ThemeProvider, createTheme } from '@mui/material/styles';
import CssBaseline from '@mui/material/CssBaseline';
import axios from 'axios';
import App from './App';

// Configuração global do axios para NUNCA fazer cache
axios.defaults.headers.common['Cache-Control'] = 'no-cache, no-store, must-revalidate';
axios.defaults.headers.common['Pragma'] = 'no-cache';
axios.defaults.headers.common['Expires'] = '0';

// Interceptor para adicionar timestamp em TODAS as requisições
axios.interceptors.request.use((config) => {
  // Adiciona timestamp único para evitar cache
  const separator = config.url.includes('?') ? '&' : '?';
  config.url = `${config.url}${separator}_nocache=${Date.now()}`;
  return config;
});

// Tema customizado seguindo o manual de marca
const theme = createTheme({
  palette: {
    primary: {
      main: '#009739', // Verde principal
    },
    secondary: {
      main: '#003366', // Azul principal
    },
    warning: {
      main: '#FFF81C', // Amarelo para alertas
    },
    error: {
      main: '#ED8B00', // Laranja escuro para avisos
    },
    background: {
      default: '#FFFFFF', // Branco
      paper: '#FFFFFF',
    },
    text: {
      primary: '#003366', // Azul para textos principais
      secondary: '#666666', // Cinza para textos secundários
    },
  },
  typography: {
    fontFamily: '"Inter", "Roboto", "Helvetica", "Arial", sans-serif',
    h1: {
      fontFamily: '"Montserrat", sans-serif',
      fontWeight: 700,
      color: '#003366',
    },
    h2: {
      fontFamily: '"Montserrat", sans-serif',
      fontWeight: 700,
      color: '#003366',
    },
    h3: {
      fontFamily: '"Montserrat", sans-serif',
      fontWeight: 700,
      color: '#003366',
    },
    h4: {
      fontFamily: '"Montserrat", sans-serif',
      fontWeight: 700,
      color: '#003366',
    },
    h5: {
      fontFamily: '"Montserrat", sans-serif',
      fontWeight: 700,
      color: '#003366',
    },
    h6: {
      fontFamily: '"Montserrat", sans-serif',
      fontWeight: 700,
      color: '#003366',
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
  },
});

const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(
  <React.StrictMode>
    <BrowserRouter>
      <ThemeProvider theme={theme}>
        <CssBaseline />
        <App />
      </ThemeProvider>
    </BrowserRouter>
  </React.StrictMode>
);
