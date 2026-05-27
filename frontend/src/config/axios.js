import axios from 'axios';

// Configuração base do axios para todas as requisições
const api = axios.create({
  baseURL: process.env.REACT_APP_API_URL || 'http://localhost:8000',
  timeout: 120000,
  headers: {
    'Content-Type': 'application/json',
    'X-API-Key': process.env.REACT_APP_API_KEY || '',
  },
});

// Interceptador para adicionar tokens ou outros headers
api.interceptors.request.use(
  (config) => {
    // Você pode adicionar lógica aqui para adicionar tokens, etc.
    return config;
  },
  (error) => {
    return Promise.reject(error);
  }
);

// Interceptador para tratar respostas e erros globais
api.interceptors.response.use(
  (response) => response,
  (error) => {
    // Tratamento global de erros
    if (error.response) {
      // Erro de resposta do servidor
      console.error('Erro na API:', error.response.data);
    } else if (error.request) {
      // Erro de requisição
      console.error('Erro de conexão com o servidor');
    } else {
      // Erro ao configurar a requisição
      console.error('Erro:', error.message);
    }
    return Promise.reject(error);
  }
);

export default api;
