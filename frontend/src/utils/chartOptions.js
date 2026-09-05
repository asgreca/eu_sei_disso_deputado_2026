/**
 * ECharts Options Helper - Brand Manual Compliant
 * All charts must use ECharts and follow brand colors
 */

export const brandColors = {
  verde: '#009739',      // Botões principais, links, títulos secundários
  amarelo: '#FFF81C',     // Ícones, indicadores de atenção, alertas
  azul: '#003366',        // Cabeçalhos, menus, blocos de fundo, gráficos
  branco: '#FFFFFF',      // Fundo principal, áreas de respiro
  cinza: '#666666',       // Textos secundários, descrições, rodapés
  azulClaro: '#4F81BD',   // Gráficos comparativos
  verdeClaro: '#66BB6A',  // Indicadores positivos
  cinzaClaro: '#E0E0E0',  // Fundos neutros
  laranjaEscuro: '#ED8B00', // Avisos importantes
  laranjaClaro: '#FFB74D', // Destaques intermediários
};

export const createBaseOption = (title = '', subtitle = '') => ({
  backgroundColor: '#FFFFFF',
  title: {
    text: title,
    subtext: subtitle,
    left: 'center',
    textStyle: {
      color: brandColors.azul,
      fontFamily: 'Montserrat, Arial, sans-serif',
      fontWeight: 'bold',
      fontSize: 18,
    },
    subtextStyle: {
      color: brandColors.cinza,
      fontSize: 14,
    },
  },
  tooltip: {
    trigger: 'item',
    backgroundColor: 'rgba(50, 50, 50, 0.9)',
    borderColor: brandColors.verde,
    borderWidth: 2,
    textStyle: {
      color: '#FFFFFF',
      fontSize: 12,
    },
  },
  legend: {
    textStyle: {
      color: brandColors.azul,
      fontSize: 12,
    },
    top: '10%',
  },
});

const getAdaptivePercentScale = (values = []) => {
  const numericValues = (values || [])
    .map((value) => Number(value))
    .filter((value) => Number.isFinite(value) && value >= 0);

  const maxObserved = numericValues.length ? Math.max(...numericValues) : 0;

  if (maxObserved <= 2) return { max: 5, interval: 1 };
  if (maxObserved <= 5) return { max: 10, interval: 2 };
  if (maxObserved <= 10) return { max: 20, interval: 5 };
  if (maxObserved <= 20) return { max: 40, interval: 10 };
  if (maxObserved <= 40) return { max: 60, interval: 10 };
  if (maxObserved <= 60) return { max: 80, interval: 20 };

  return { max: 100, interval: 20 };
};

/**
 * Bar Chart - Brand Compliant
 */
export const createBarChartOption = (data, title = '', xAxisLabel = '') => {
  const option = createBaseOption(title);
  const valueFormatter = data.valueFormatter || ((value) => `${Number(value || 0).toLocaleString('pt-BR')}`);

  return {
    ...option,
    tooltip: {
      trigger: 'axis',
      axisPointer: {
        type: 'shadow',
      },
      backgroundColor: 'rgba(50, 50, 50, 0.9)',
      borderColor: brandColors.verde,
      textStyle: { color: '#FFFFFF' },
    },
    grid: {
      left: '3%',
      right: '4%',
      bottom: '3%',
      containLabel: true,
    },
    xAxis: {
      type: 'category',
      data: data.xAxis,
      axisLine: {
        lineStyle: {
          color: brandColors.cinza,
        },
      },
      axisLabel: {
        color: brandColors.azul,
        rotate: data.xAxis.length > 8 ? 35 : 0,
        interval: 0,
        formatter: (value) => {
          const text = String(value ?? '');
          if (text.length <= 18) return text;
          const words = text.split(' ');
          if (words.length > 1) return words.join('\n');
          return `${text.slice(0, 16)}…`;
        },
      },
    },
    yAxis: {
      type: 'value',
      axisLine: {
        lineStyle: {
          color: brandColors.cinza,
        },
      },
      axisLabel: {
        color: brandColors.azul,
      },
      splitLine: {
        lineStyle: {
          color: brandColors.cinzaClaro,
        },
      },
    },
    series: [{
      name: xAxisLabel || 'Valor',
      type: 'bar',
      data: data.values,
      itemStyle: {
        color: brandColors.verde,
        borderRadius: [8, 8, 0, 0], // Curved corners like Brasília
      },
      label: {
        show: data.showLabels || false,
        position: 'top',
        color: brandColors.azul,
        formatter: ({ value }) => valueFormatter(value),
      },
    }],
  };
};

export const createHorizontalPercentBarChartOption = (data, title = '', subtitle = '') => {
  const option = createBaseOption(title, subtitle);
  const percentScale = getAdaptivePercentScale(data.values);
  const palette = [
    brandColors.azul,
    brandColors.azulClaro,
    brandColors.verde,
    brandColors.verdeClaro,
    brandColors.laranjaEscuro,
    brandColors.laranjaClaro,
  ];

  return {
    ...option,
    tooltip: {
      trigger: 'axis',
      axisPointer: {
        type: 'shadow',
      },
      formatter: (params) => {
        const point = Array.isArray(params) ? params[0] : params;
        return `${point.name}<br/>${Number(point.value).toFixed(1)}%`;
      },
      backgroundColor: 'rgba(50, 50, 50, 0.92)',
      borderColor: brandColors.verde,
      textStyle: { color: '#FFFFFF' },
    },
    grid: {
      left: '4%',
      right: '6%',
      top: 72,
      bottom: 20,
      containLabel: true,
    },
    xAxis: {
      type: 'value',
      min: 0,
      max: percentScale.max,
      interval: percentScale.interval,
      axisLine: {
        lineStyle: {
          color: brandColors.cinza,
        },
      },
      axisLabel: {
        color: brandColors.azul,
        formatter: '{value}%',
      },
      splitLine: {
        lineStyle: {
          color: brandColors.cinzaClaro,
        },
      },
    },
    yAxis: {
      type: 'category',
      data: data.labels,
      axisLine: {
        show: false,
      },
      axisTick: {
        show: false,
      },
      axisLabel: {
        color: brandColors.azul,
        fontWeight: 600,
      },
    },
    series: [{
      type: 'bar',
      data: data.values.map((value, index) => ({
        value,
        itemStyle: {
          color: palette[index % palette.length],
          borderRadius: [0, 10, 10, 0],
        },
      })),
      label: {
        show: true,
        position: 'right',
        color: brandColors.azul,
        fontWeight: 'bold',
        formatter: ({ value }) => `${Number(value).toFixed(1)}%`,
      },
      barWidth: 18,
    }],
  };
};

export const createHorizontalValueBarChartOption = (data, title = '', subtitle = '', formatter = (value) => `${value}`) => {
  const option = createBaseOption(title, subtitle);
  const palette = [
    brandColors.azul,
    brandColors.verde,
    brandColors.azulClaro,
    brandColors.laranjaEscuro,
    brandColors.verdeClaro,
  ];

  const maxValue = Math.max(...data.values, 0);

  return {
    ...option,
    tooltip: {
      trigger: 'axis',
      axisPointer: {
        type: 'shadow',
      },
      formatter: (params) => {
        const point = Array.isArray(params) ? params[0] : params;
        return `${point.name}<br/>${formatter(point.value)}`;
      },
      backgroundColor: 'rgba(50, 50, 50, 0.92)',
      borderColor: brandColors.verde,
      textStyle: { color: '#FFFFFF' },
    },
    grid: {
      left: '4%',
      right: '6%',
      top: 72,
      bottom: 20,
      containLabel: true,
    },
    xAxis: {
      type: 'value',
      min: 0,
      max: maxValue > 0 ? maxValue * 1.15 : 100,
      axisLine: {
        lineStyle: {
          color: brandColors.cinza,
        },
      },
      axisLabel: {
        color: brandColors.azul,
        formatter: (value) => formatter(value),
      },
      splitLine: {
        lineStyle: {
          color: brandColors.cinzaClaro,
        },
      },
    },
    yAxis: {
      type: 'category',
      data: data.labels,
      axisLine: {
        show: false,
      },
      axisTick: {
        show: false,
      },
      axisLabel: {
        color: brandColors.azul,
        fontWeight: 600,
      },
    },
    series: [{
      type: 'bar',
      data: data.values.map((value, index) => ({
        value,
        itemStyle: {
          color: palette[index % palette.length],
          borderRadius: [0, 10, 10, 0],
        },
      })),
      label: {
        show: true,
        position: 'right',
        color: brandColors.azul,
        fontWeight: 'bold',
        formatter: ({ value }) => formatter(value),
      },
      barWidth: 18,
    }],
  };
};

export const createGroupedHorizontalPercentBarChartOption = (data, title = '', subtitle = '') => {
  const option = createBaseOption(title, subtitle);
  const percentScale = getAdaptivePercentScale((data.series || []).flatMap((serie) => serie.values || []));
  const seriesPalette = [brandColors.azul, brandColors.verde, brandColors.laranjaEscuro];

  return {
    ...option,
    title: {
      ...option.title,
      top: 8,
      subtextStyle: {
        ...option.title.subtextStyle,
        lineHeight: 22,
        width: 500,
        overflow: 'break',
      },
    },
    tooltip: {
      trigger: 'axis',
      axisPointer: {
        type: 'shadow',
      },
      formatter: (params) => {
        const rows = (Array.isArray(params) ? params : [params]).map(
          (point) => `${point.seriesName}: ${Number(point.value).toFixed(1)}%`
        );
        return `${params?.[0]?.name || ''}<br/>${rows.join('<br/>')}`;
      },
      backgroundColor: 'rgba(50, 50, 50, 0.92)',
      borderColor: brandColors.verde,
      textStyle: { color: '#FFFFFF' },
    },
    legend: {
      top: 96,
      textStyle: {
        color: brandColors.azul,
        fontSize: 11,
      },
      itemGap: 14,
      itemWidth: 14,
      itemHeight: 10,
    },
    grid: {
      left: '4%',
      right: '6%',
      top: 176,
      bottom: 20,
      containLabel: true,
    },
    xAxis: {
      type: 'value',
      min: 0,
      max: percentScale.max,
      interval: percentScale.interval,
      axisLine: {
        lineStyle: {
          color: brandColors.cinza,
        },
      },
      axisLabel: {
        color: brandColors.azul,
        formatter: '{value}%',
      },
      splitLine: {
        lineStyle: {
          color: brandColors.cinzaClaro,
        },
      },
    },
    yAxis: {
      type: 'category',
      data: data.labels,
      axisLine: {
        show: false,
      },
      axisTick: {
        show: false,
      },
      axisLabel: {
        color: brandColors.azul,
        fontWeight: 600,
      },
    },
    series: (data.series || []).map((serie, index) => ({
      name: serie.name,
      type: 'bar',
      data: serie.values,
      barMaxWidth: 14,
      itemStyle: {
        color: seriesPalette[index % seriesPalette.length],
        borderRadius: [0, 8, 8, 0],
      },
      label: {
        show: index === 0,
        position: 'right',
        color: brandColors.azul,
        formatter: ({ value }) => `${Number(value).toFixed(1)}%`,
      },
    })),
  };
};

/**
 * Pie Chart - Brand Compliant
 */
export const createPieChartOption = (data, title = '') => {
  const option = createBaseOption(title);

  const pieColors = [
    brandColors.verde,
    brandColors.azul,
    brandColors.azulClaro,
    brandColors.verdeClaro,
    brandColors.laranjaEscuro,
  ];

  return {
    ...option,
    legend: {
      ...option.legend,
      orient: 'vertical',
      left: 'left',
      top: '10%',
      itemGap: 10,
      itemWidth: 15,
      itemHeight: 15,
      textStyle: {
        color: brandColors.azul,
        fontSize: 11,
      },
    },
    series: [{
      name: title,
      type: 'pie',
      radius: '50%',
      center: ['60%', '50%'], // Deslocar para direita para dar espaço à legenda
      avoidLabelOverlap: false,
      itemStyle: {
        borderRadius: 10, // Curved like Brasília
        borderColor: brandColors.branco,
        borderWidth: 2,
      },
      label: {
        show: false, // Esconder labels do gráfico
      },
      labelLine: {
        show: false,
      },
      emphasis: {
        label: {
          show: true,
          fontSize: 13,
          fontWeight: 'bold',
          formatter: '{b}\n{c} ({d}%)',
          position: 'outside',
          distanceToLabelLine: 5,
        },
      },
      data: data.map((item, index) => ({
        value: item.value,
        name: item.name,
        itemStyle: {
          color: pieColors[index % pieColors.length],
        },
      })),
    }],
  };
};

export const createDonutChartOption = (data, title = '', subtitle = '') => {
  const option = createBaseOption(title, subtitle);
  const pieColors = [
    brandColors.azul,
    brandColors.verde,
    brandColors.azulClaro,
    brandColors.verdeClaro,
    brandColors.laranjaEscuro,
    brandColors.laranjaClaro,
  ];

  const total = data.reduce((sum, item) => sum + (Number(item.value) || 0), 0);

  return {
    ...option,
    tooltip: {
      trigger: 'item',
      formatter: ({ name, value }) => `${name}<br/>${Number(value).toFixed(1)}%`,
      backgroundColor: 'rgba(50, 50, 50, 0.92)',
      borderColor: brandColors.verde,
      textStyle: { color: '#FFFFFF' },
    },
    legend: {
      ...option.legend,
      bottom: 2,
      top: 'auto',
      itemGap: 12,
      textStyle: {
        color: brandColors.azul,
        fontSize: 12,
      },
    },
    series: [{
      name: title,
      type: 'pie',
      radius: ['42%', '62%'],
      center: ['50%', '58%'],
      avoidLabelOverlap: true,
      itemStyle: {
        borderColor: brandColors.branco,
        borderWidth: 3,
      },
      label: {
        show: true,
        formatter: ({ percent }) => `${Number(percent).toFixed(0)}%`,
        color: brandColors.azul,
        fontWeight: 'bold',
      },
      emphasis: {
        scale: true,
        scaleSize: 6,
      },
      data: data.map((item, index) => ({
        name: item.name,
        value: item.value,
        itemStyle: {
          color: pieColors[index % pieColors.length],
        },
      })),
    }],
    graphic: total > 0 ? [
      {
        type: 'text',
        left: 'center',
        top: '50%',
        style: {
          text: 'IBGE',
          textAlign: 'center',
          fill: brandColors.azul,
          fontSize: 16,
          fontWeight: 'bold',
          fontFamily: 'Montserrat, Arial, sans-serif',
        },
      },
      {
        type: 'text',
        left: 'center',
        top: '57%',
        style: {
          text: 'perfil territorial',
          textAlign: 'center',
          fill: brandColors.cinza,
          fontSize: 11,
          fontFamily: 'Montserrat, Arial, sans-serif',
        },
      },
    ] : [],
  };
};

export const createRadarChartOption = (data, title = '', subtitle = '') => {
  const option = createBaseOption(title, subtitle);
  const normalized = Array.isArray(data)
    ? {
        indicators: data.map((item) => item.name),
        series: [
          {
            name: 'Território do deputado',
            values: data.map((item) => Number(item.value) || 0),
            lineStyle: { color: brandColors.verde, width: 3 },
            areaStyle: { color: 'rgba(0, 151, 57, 0.18)' },
            itemStyle: { color: brandColors.verde },
            symbolSize: 8,
          },
        ],
      }
    : data;

  const allValues = (normalized.series || []).flatMap((serie) => serie.values || []);
  const percentScale = getAdaptivePercentScale(allValues);

  return {
    ...option,
    title: {
      ...option.title,
      top: 8,
      textStyle: {
        ...option.title.textStyle,
        fontSize: 17,
      },
      subtextStyle: {
        ...option.title.subtextStyle,
        lineHeight: 22,
        width: 420,
        overflow: 'break',
      },
    },
    legend: {
      show: (normalized.series || []).length > 1,
      top: 86,
      textStyle: {
        color: brandColors.azul,
        fontSize: 11,
      },
      itemWidth: 14,
      itemHeight: 10,
      itemGap: 18,
    },
    tooltip: {
      trigger: 'item',
      formatter: (params) => {
        const label = params?.name || '';
        const rows = (normalized.series || []).map((serie) => {
          const index = (normalized.indicators || []).indexOf(label);
          const value = index >= 0 ? serie.values?.[index] : null;
          return `${serie.name}: ${value !== null && value !== undefined ? Number(value).toFixed(1) : '0.0'}%`;
        });
        return `${label}<br/>${rows.join('<br/>')}`;
      },
      backgroundColor: 'rgba(50, 50, 50, 0.92)',
      borderColor: brandColors.verde,
      textStyle: { color: '#FFFFFF' },
    },
    radar: {
      center: ['50%', '72%'],
      radius: '40%',
      splitNumber: 4,
      axisName: {
        color: brandColors.azul,
        fontSize: 12,
        fontWeight: 600,
      },
      splitArea: {
        areaStyle: {
          color: ['rgba(79,129,189,0.05)', 'rgba(0,151,57,0.04)'],
        },
      },
      splitLine: {
        lineStyle: {
          color: '#D7E2EF',
        },
      },
      axisLine: {
        lineStyle: {
          color: '#D7E2EF',
        },
      },
      indicator: (normalized.indicators || []).map((name) => ({
        name,
        max: percentScale.max,
      })),
    },
    series: [{
      type: 'radar',
      data: (normalized.series || []).map((serie, index) => ({
        value: (serie.values || []).map((value) => Number(Number(value || 0).toFixed(1))),
        name: serie.name || '',
        areaStyle: serie.areaStyle || (index === 0 ? { color: 'rgba(0, 151, 57, 0.18)' } : { color: 'transparent' }),
        lineStyle: serie.lineStyle || { color: brandColors.verde, width: 3 },
        itemStyle: serie.itemStyle || { color: brandColors.azul },
        symbolSize: serie.symbolSize ?? 8,
      })),
    }],
  };
};

/**
 * Line Chart - Brand Compliant
 */
export const createLineChartOption = (data, title = '') => {
  const option = createBaseOption(title);

  return {
    ...option,
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'rgba(50, 50, 50, 0.9)',
      borderColor: brandColors.verde,
      textStyle: { color: '#FFFFFF' },
    },
    grid: {
      left: '3%',
      right: '4%',
      bottom: '3%',
      containLabel: true,
    },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: data.xAxis,
      axisLine: {
        lineStyle: {
          color: brandColors.cinza,
        },
      },
      axisLabel: {
        color: brandColors.azul,
      },
    },
    yAxis: {
      type: 'value',
      axisLine: {
        lineStyle: {
          color: brandColors.cinza,
        },
      },
      axisLabel: {
        color: brandColors.azul,
      },
      splitLine: {
        lineStyle: {
          color: brandColors.cinzaClaro,
        },
      },
    },
    series: data.series.map((serie, index) => ({
      name: serie.name,
      type: 'line',
      data: serie.data,
      smooth: true,
      itemStyle: {
        color: [brandColors.verde, brandColors.azul, brandColors.azulClaro][index % 3],
      },
      lineStyle: {
        width: 3,
      },
      symbol: 'circle',
      symbolSize: 8,
      areaStyle: serie.areaStyle || {},
    })),
  };
};

/**
 * TreeMap Chart - Brand Compliant
 */
export const createTreeMapOption = (data, title = '') => {
  const option = createBaseOption(title);

  const colorScale = [
    brandColors.azul,
    brandColors.verde,
    brandColors.laranjaEscuro,
    brandColors.azulClaro,
    brandColors.laranjaClaro,
  ];

  return {
    ...option,
    tooltip: {
      trigger: 'item',
      formatter: function (info) {
        const val = info.value;
        return [
          '<div style="font-weight:bold; border-bottom: 1px solid rgba(255,255,255,0.3); padding-bottom: 5px; margin-bottom: 5px">' + info.name + '</div>',
          'Votos: ' + val.toLocaleString('pt-BR')
        ].join('');
      }
    },
    series: [{
      type: 'treemap',
      roam: true,
      nodeClick: 'zoomToNode',
      breadcrumb: {
        show: true,
        itemStyle: {
          color: brandColors.azul,
        }
      },
      label: {
        show: true,
        color: brandColors.branco,
        fontWeight: 'bold',
        fontSize: 12,
        formatter: '{b}'
      },
      upperLabel: {
        show: true,
        height: 24,
        color: brandColors.azul,
        fontWeight: 'bold',
        fontSize: 13,
        backgroundColor: '#f5f5f5'
      },
      itemStyle: {
        borderColor: brandColors.branco,
        borderWidth: 2,
        gapWidth: 1,
      },
      levels: [
        {
          itemStyle: {
            borderColor: brandColors.azul,
            borderWidth: 2,
            gapWidth: 2
          },
          upperLabel: {
            show: false
          }
        },
        {
          itemStyle: {
            borderColor: brandColors.branco,
            borderWidth: 2,
            gapWidth: 1
          },
          upperLabel: {
            show: true
          }
        }
      ],
      data: data.map((item, index) => ({
        ...item,
        itemStyle: {
          color: colorScale[index % colorScale.length],
        },
      })),
    }],
  };
};

/**
 * Network/Graph Chart - Brand Compliant
 */
export const createNetworkOption = (nodes, links, title = '') => {
  const option = createBaseOption(title);

  return {
    ...option,
    series: [{
      type: 'graph',
      layout: 'force',
      force: {
        repulsion: 2000,
        edgeLength: 200,
        gravity: 0.1,
        layoutAnimation: true,
      },
      data: nodes,
      links: links.map(link => ({
        source: link.source,
        target: link.target,
        lineStyle: {
          color: link.color || brandColors.cinza,
          width: link.width || 2,
          curveness: 0.3,
        },
      })),
      categories: [
        { name: 'Parlamentar', itemStyle: { color: brandColors.azul } },
        { name: 'Partido', itemStyle: { color: brandColors.verde } },
        { name: 'Estado', itemStyle: { color: brandColors.laranjaEscuro } },
      ],
      emphasis: {
        focus: 'adjacency',
        lineStyle: {
          width: 4,
        },
      },
    }],
  };
};

export default {
  createBarChartOption,
  createPieChartOption,
  createLineChartOption,
  createTreeMapOption,
  createNetworkOption,
  brandColors,
};
