import React, { useEffect, useRef } from 'react';
import * as echarts from 'echarts';
import { Box } from '@mui/material';

const EChartWrapper = ({ option, style, height = '400px', onEvents }) => {
  const chartRef = useRef(null);
  const chartInstance = useRef(null);

  useEffect(() => {
    if (chartRef.current && !chartInstance.current) {
      chartInstance.current = echarts.init(chartRef.current);
    }

    if (chartInstance.current && option) {
      const brandOption = {
        color: ['#009739', '#003366', '#FFF81C', '#ED8B00', '#666666', '#4F81BD', '#66BB6A'],
        ...option,
      };
      chartInstance.current.setOption(brandOption, true);
    }

    return () => {
      if (chartInstance.current) {
        chartInstance.current.dispose();
        chartInstance.current = null;
      }
    };
  }, [option]);

  useEffect(() => {
    if (chartInstance.current && onEvents) {
      Object.keys(onEvents).forEach((eventName) => {
        chartInstance.current.off(eventName);
        chartInstance.current.on(eventName, onEvents[eventName]);
      });
    }
  }, [onEvents]);

  useEffect(() => {
    const handleResize = () => {
      if (chartInstance.current) {
        chartInstance.current.resize();
      }
    };

    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  return <Box ref={chartRef} style={{ width: '100%', height, ...style }} />;
};

export default EChartWrapper;

