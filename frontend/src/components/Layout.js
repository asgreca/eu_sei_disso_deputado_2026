import React, { useState } from 'react';
import {
  AppBar,
  Toolbar,
  Typography,
  Drawer,
  List,
  ListItem,
  ListItemIcon,
  ListItemText,
  Box,
  IconButton,
  useMediaQuery,
  useTheme,
  Divider,
} from '@mui/material';
import {
  Menu as MenuIcon,
  Home as HomeIcon,
  Search as SearchIcon,
  Assessment as AssessmentIcon,
  People as PeopleIcon,
  Flight as FlightIcon,
  Newspaper as NewspaperIcon,
  AccountBalance as AccountBalanceIcon,
  Timeline as TimelineIcon,
} from '@mui/icons-material';
import { useNavigate, useLocation } from 'react-router-dom';

const drawerWidth = 280;

const menuItems = [
  { text: 'Início', icon: <HomeIcon />, path: '/' },
  { text: 'Busca Semântica', icon: <SearchIcon />, path: '/busca-semantica' },
  { text: 'Atuação em Comissões', icon: <AccountBalanceIcon />, path: '/atuacao-comissoes' },
  { text: 'Odiograma', icon: <TimelineIcon />, path: '/odiograma' },
  { text: 'Gastos - Detalhamento', icon: <AssessmentIcon />, path: '/gastos/detalhamento' },
  { text: 'Gastos - Ranking', icon: <AssessmentIcon />, path: '/gastos/ranking' },
  { text: 'Passagens Aéreas', icon: <FlightIcon />, path: '/passagens-aereas' },
  { text: 'Análise de Imprensa', icon: <NewspaperIcon />, path: '/analise-imprensa' },
];

function Layout({ children }) {
  const [mobileOpen, setMobileOpen] = useState(false);
  const theme = useTheme();
  const isMobile = useMediaQuery(theme.breakpoints.down('md'));
  const navigate = useNavigate();
  const location = useLocation();

  const handleDrawerToggle = () => {
    setMobileOpen(!mobileOpen);
  };

  const handleNavigation = (path) => {
    navigate(path);
    if (isMobile) {
      setMobileOpen(false);
    }
  };

  const drawer = (
    <Box>
      <Toolbar sx={{ padding: '16px 8px !important', justifyContent: 'center' }}>
        <Box
          component="img"
          src="/eu_sei_disso_2.png"
          alt="Eu Sei Disso Deputado"
          sx={{
            width: '90%',
            height: 'auto',
            maxHeight: 120,
            objectFit: 'contain',
            cursor: 'pointer',
          }}
          onClick={() => handleNavigation('/')}
        />
      </Toolbar>
      <Divider />
      <List>
        {menuItems.map((item) => (
          <ListItem
            button
            key={item.text}
            onClick={() => handleNavigation(item.path)}
            selected={location.pathname === item.path}
            sx={{
              '&.Mui-selected': {
                backgroundColor: '#009739',
                color: 'white',
                '& .MuiListItemIcon-root': {
                  color: 'white',
                },
                '&:hover': {
                  backgroundColor: '#007a2f',
                },
              },
              '&:hover': {
                backgroundColor: '#E0E0E0',
              },
            }}
          >
            <ListItemIcon>{item.icon}</ListItemIcon>
            <ListItemText primary={item.text} />
          </ListItem>
        ))}
      </List>
    </Box>
  );

  return (
    <Box sx={{ display: 'flex' }}>
      <AppBar
        position="fixed"
        sx={{
          width: { md: `calc(100% - ${drawerWidth}px)` },
          ml: { md: `${drawerWidth}px` },
          backgroundColor: '#003366',
        }}
      >
        <Toolbar sx={{ minHeight: '80px !important' }}>
          <IconButton
            color="inherit"
            aria-label="open drawer"
            edge="start"
            onClick={handleDrawerToggle}
            sx={{ mr: 2, display: { md: 'none' } }}
          >
            <MenuIcon />
          </IconButton>
          <Box
            component="img"
            src="/eu_sei_disso_1.png"
            alt="Eu Sei Disso Deputado"
            sx={{
              height: 50,
              width: 'auto',
              maxWidth: { xs: '200px', sm: '300px', md: '400px' },
              objectFit: 'contain',
              cursor: 'pointer',
            }}
            onClick={() => handleNavigation('/')}
          />
        </Toolbar>
      </AppBar>

      <Box
        component="nav"
        sx={{ width: { md: drawerWidth }, flexShrink: { md: 0 } }}
      >
        <Drawer
          variant="temporary"
          open={mobileOpen}
          onClose={handleDrawerToggle}
          ModalProps={{
            keepMounted: true,
          }}
          sx={{
            display: { xs: 'block', md: 'none' },
            '& .MuiDrawer-paper': {
              boxSizing: 'border-box',
              width: drawerWidth,
            },
          }}
        >
          {drawer}
        </Drawer>
        <Drawer
          variant="permanent"
          sx={{
            display: { xs: 'none', md: 'block' },
            '& .MuiDrawer-paper': {
              boxSizing: 'border-box',
              width: drawerWidth,
            },
          }}
          open
        >
          {drawer}
        </Drawer>
      </Box>

      <Box
        component="main"
        sx={{
          flexGrow: 1,
          p: 3,
          width: { md: `calc(100% - ${drawerWidth}px)` },
        }}
      >
        <Toolbar />
        {children}
      </Box>
    </Box>
  );
}

export default Layout;
