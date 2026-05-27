import React, { useEffect, useRef } from 'react';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';

// Fix para ícones padrão do Leaflet
delete L.Icon.Default.prototype._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: require('leaflet/dist/images/marker-icon-2x.png'),
  iconUrl: require('leaflet/dist/images/marker-icon.png'),
  shadowUrl: require('leaflet/dist/images/marker-shadow.png'),
});

const LeafletMap = ({ aeroportos, rotas }) => {
  const mapRef = useRef(null);
  const mapInstanceRef = useRef(null);

  useEffect(() => {
    if (!mapRef.current || mapInstanceRef.current) return;

    // Inicializar mapa centrado no Brasil
    const map = L.map(mapRef.current).setView([-15.7801, -47.9292], 4);

    // Adicionar camada de tiles (CartoDB Positron — livre, sem bloqueio de referer)
    L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
      attribution: '© <a href="https://carto.com/">CARTO</a>',
      subdomains: 'abcd',
      maxZoom: 19
    }).addTo(map);

    mapInstanceRef.current = map;

    return () => {
      if (mapInstanceRef.current) {
        mapInstanceRef.current.remove();
        mapInstanceRef.current = null;
      }
    };
  }, []);

  useEffect(() => {
    if (!mapInstanceRef.current) return;
    if (!aeroportos && !rotas) return;

    const map = mapInstanceRef.current;
    
    // Limpar marcadores e linhas anteriores
    map.eachLayer((layer) => {
      if (layer instanceof L.Marker || layer instanceof L.Polyline) {
        map.removeLayer(layer);
      }
    });

    // Se aeroportos é passado e NÃO tem rotas, plotar como pontos simples (para fornecedores)
    if (aeroportos && aeroportos.length > 0 && (!rotas || rotas.length === 0)) {
      console.log('🗺️ Plotando pontos simples (fornecedores):', aeroportos.length);
      
      aeroportos.forEach(ponto => {
        if (ponto.latitude && ponto.longitude) {
          // Usar emoji temático ou padrão - DIRETO como ícone (sem background)
          const emoji = ponto.sigla || "📍";
          
          const marker = L.marker([ponto.latitude, ponto.longitude], {
            icon: L.divIcon({
              html: `<div style="
                width: 16px;
                height: 16px;
                background-color: #003366;
                border: 3px solid #ffffff;
                border-radius: 50%;
                box-shadow: 0 2px 4px rgba(0,0,0,0.3);
              "></div>`,
              className: 'custom-marker-blue',
              iconSize: [16, 16],
              iconAnchor: [8, 8]
            })
          }).addTo(map);

          // Popup detalhado com cidade e estado
          const popupContent = `
            <div style="font-family: Arial, sans-serif; padding: 12px; min-width: 240px;">
              <div style="font-size: 32px; text-align: center; margin-bottom: 8px;">${emoji}</div>
              <strong style="color: #003366; font-size: 15px; display: block; margin-bottom: 8px;">${ponto.nome || 'Fornecedor'}</strong>
              ${ponto.total ? `<div style="color: #009739; font-weight: bold; font-size: 18px; margin-bottom: 6px;">💰 R$ ${ponto.total.toLocaleString('pt-BR', { minimumFractionDigits: 2 })}</div>` : ''}
              ${ponto.quantidade ? `<div style="color: #666; font-size: 13px; margin-bottom: 4px;">📊 Lançamentos: ${ponto.quantidade}</div>` : ''}
              ${ponto.cidade_fornecedor ? `<div style="color: #666; font-size: 13px; margin-bottom: 4px;">📍 Cidade: ${ponto.cidade_fornecedor}</div>` : ''}
              ${ponto.endereco_completo && !ponto.endereco_completo.includes('não encontrado na API') ? `<div style="color: #999; font-size: 11px; margin-top: 6px;">🏠 ${ponto.endereco_completo}</div>` : ''}
            </div>
          `;
          
          marker.bindPopup(popupContent);
        }
      });

      // Ajustar zoom para mostrar todos os pontos
      if (aeroportos.length > 0) {
        const pontosValidos = aeroportos.filter(p => p.latitude && p.longitude);
        if (pontosValidos.length > 0) {
          const group = new L.featureGroup();
          pontosValidos.forEach(p => {
            group.addLayer(L.marker([p.latitude, p.longitude]));
          });
          map.fitBounds(group.getBounds().pad(0.1));
        }
      }
      
      return;
    }

    // Criar mapa de aeroportos (para rotas de voos)
    const aeroportosMap = {};
    if (aeroportos) {
      aeroportos.forEach(airport => {
        if (airport.latitude >= -35 && airport.latitude <= 5 && 
            airport.longitude >= -75 && airport.longitude <= -30) {
          aeroportosMap[airport.sigla] = {
            nome: airport.nome,
            coords: [airport.latitude, airport.longitude],
          };
        }
      });
    }

    // Processar rotas
    const rotasProcessadas = [];
    rotas.forEach(rota => {
      const origemData = aeroportosMap[rota.origem];
      const destinoData = aeroportosMap[rota.destino];

      if (origemData && destinoData) {
        rotasProcessadas.push({
          origem: rota.origem,
          destino: rota.destino,
          origemCoords: origemData.coords,
          destinoCoords: destinoData.coords,
          origemNome: origemData.nome,
          destinoNome: destinoData.nome
        });
      }
    });

    // Criar marcadores personalizados (serão criados dentro do loop)

    // Adicionar marcadores e linhas
    const aeroportosUsados = new Set();
    rotasProcessadas.forEach(rota => {
      // Marcador de origem
      if (!aeroportosUsados.has(rota.origem)) {
        const marker = L.marker(rota.origemCoords, {
          icon: L.divIcon({
            html: `<div style="
              background-color: #003366;
              border: 3px solid #009739;
              border-radius: 50%;
              width: 20px;
              height: 20px;
              display: flex;
              align-items: center;
              justify-content: center;
              color: white;
              font-size: 10px;
              font-weight: bold;
              box-shadow: 0 2px 4px rgba(0,0,0,0.3);
            ">${rota.origem}</div>`,
            className: 'custom-marker',
            iconSize: [20, 20],
            iconAnchor: [10, 10]
          })
        }).addTo(map);

        marker.bindPopup(`
          <div style="font-family: Arial, sans-serif; padding: 8px;">
            <strong style="color: #003366;">${rota.origem}</strong><br/>
            <span style="color: #666;">${rota.origemNome}</span><br/>
            <small style="color: #009739;">Aeroporto de Origem</small>
          </div>
        `);

        aeroportosUsados.add(rota.origem);
      }

      // Marcador de destino
      if (!aeroportosUsados.has(rota.destino)) {
        const marker = L.marker(rota.destinoCoords, {
          icon: L.divIcon({
            html: `<div style="
              background-color: #ED8B00;
              border: 2px solid #ffffff;
              border-radius: 50%;
              width: 18px;
              height: 18px;
              display: flex;
              align-items: center;
              justify-content: center;
              color: white;
              font-size: 9px;
              font-weight: bold;
              box-shadow: 0 2px 4px rgba(0,0,0,0.3);
            ">${rota.destino}</div>`,
            className: 'custom-marker',
            iconSize: [18, 18],
            iconAnchor: [9, 9]
          })
        }).addTo(map);

        marker.bindPopup(`
          <div style="font-family: Arial, sans-serif; padding: 8px;">
            <strong style="color: #003366;">${rota.destino}</strong><br/>
            <span style="color: #666;">${rota.destinoNome}</span><br/>
            <small style="color: #ED8B00;">Aeroporto de Destino</small>
          </div>
        `);

        aeroportosUsados.add(rota.destino);
      }

      // Linha de rota
      const polyline = L.polyline([rota.origemCoords, rota.destinoCoords], {
        color: '#009739',
        weight: 3,
        opacity: 0.8,
        smoothFactor: 1
      }).addTo(map);

      // Adicionar popup na linha
      polyline.bindPopup(`
        <div style="font-family: Arial, sans-serif; padding: 8px;">
          <strong style="color: #003366;">Rota: ${rota.origem} → ${rota.destino}</strong><br/>
          <span style="color: #666;">${rota.origemNome} → ${rota.destinoNome}</span>
        </div>
      `);
    });

    // Ajustar zoom para mostrar todas as rotas
    if (rotasProcessadas.length > 0) {
      const group = new L.featureGroup();
      rotasProcessadas.forEach(rota => {
        group.addLayer(L.marker(rota.origemCoords));
        group.addLayer(L.marker(rota.destinoCoords));
      });
      map.fitBounds(group.getBounds().pad(0.1));
    }

  }, [aeroportos, rotas]);

  return (
    <div 
      ref={mapRef} 
      style={{ 
        width: '100%', 
        height: '500px', 
        borderRadius: '8px',
        border: '1px solid #ddd'
      }} 
    />
  );
};

export default LeafletMap;
