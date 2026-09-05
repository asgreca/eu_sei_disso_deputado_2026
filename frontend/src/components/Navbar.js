import React, { useState } from 'react';
import {
    AppBar,
    Box,
    Toolbar,
    IconButton,
    Typography,
    Menu,
    MenuItem,
    Button,
    Container,
    Drawer,
    List,
    ListItem,
    ListItemText,
    Collapse,
} from '@mui/material';
import MenuIcon from '@mui/icons-material/Menu';
import ExpandLess from '@mui/icons-material/ExpandLess';
import ExpandMore from '@mui/icons-material/ExpandMore';
import { useNavigate } from 'react-router-dom';
import Logo from './Logo';

const pages = [
    {
        title: 'Gastos',
        items: [
            { name: 'Detalhamento', path: '/gastos/detalhamento' },
            { name: 'Passagens Aéreas', path: '/gastos/passagens' },
            { name: 'Ranking', path: '/gastos/ranking' },
            { name: 'Emendas', path: '/gastos/emendas' },
            { name: 'Conflito em Emendas', path: '/gastos/conflitos' },
            { name: 'Assessores', path: '/parlamentar/assessores' },
        ],
    },
    {
        title: 'Mapas',
        items: [
            { name: 'Mapa Eleitoral', path: '/mapa/eleitoral2' },
            { name: 'Mapa Partidário', path: '/mapa/partidario' },
        ],
    },
    {
        title: 'Comissões',
        items: [
            { name: 'Atuação', path: '/comissoes/atuacao' },
            { name: 'Presença', path: '/comissoes/presenca' },
        ],
    },
    {
        title: 'Votação',
        items: [
            { name: 'Votação Geral', path: '/votos/geral' },
            { name: 'Votação por Parlamentar', path: '/votos/parlamentar' },
        ],
    },
    {
        title: 'Análise',
        items: [
            { name: 'Imprensa', path: '/analise/imprensa' },
            { name: 'Sociograma', path: '/conexoes/sociograma' },
            { name: 'Busca Semântica', path: '/busca/semantica' },
            { name: 'Chat Parlamentar', path: '/analise/chat' },
        ],
    },
    {
        title: 'Manifesto',
        items: [
            { name: 'Metodologia e Dados Abertos', path: '/manifesto' },
        ],
    },
];

const Navbar = () => {
    const navigate = useNavigate();
    const [anchorElNav, setAnchorElNav] = useState(null);
    const [anchorElMenus, setAnchorElMenus] = useState({});
    const [mobileOpen, setMobileOpen] = useState(false);
    const [mobileMenuOpen, setMobileMenuOpen] = useState({});

    const handleOpenNavMenu = (event) => {
        setMobileOpen(true);
    };

    const handleCloseNavMenu = () => {
        setMobileOpen(false);
    };

    const handleOpenMenu = (event, title) => {
        setAnchorElMenus({ ...anchorElMenus, [title]: event.currentTarget });
    };

    const handleCloseMenu = (title) => {
        setAnchorElMenus({ ...anchorElMenus, [title]: null });
    };

    const handleNavigate = (path) => {
        navigate(path);
        handleCloseNavMenu();
        setAnchorElMenus({});
    };

    const toggleMobileMenu = (title) => {
        setMobileMenuOpen((prev) => ({ ...prev, [title]: !prev[title] }));
    };

    return (
        <AppBar position="static" sx={{ backgroundColor: '#003366' }}>
            <Container maxWidth="xl">
                <Toolbar disableGutters>
                    {/* Desktop Logo */}
                    <Box
                        sx={{
                            display: { xs: 'none', md: 'flex' },
                            mr: 2,
                            cursor: 'pointer',
                            backgroundColor: 'white',
                            p: '8px 16px',
                            borderRadius: '8px',
                            alignItems: 'center'
                        }}
                        onClick={() => navigate('/')}
                    >
                        <Logo variant="horizontal" sx={{ maxHeight: '60px' }} />
                    </Box>

                    {/* Mobile Menu Icon */}
                    <Box sx={{ flexGrow: 1, display: { xs: 'flex', md: 'none' } }}>
                        <IconButton
                            size="large"
                            aria-label="menu"
                            aria-controls="menu-appbar"
                            aria-haspopup="true"
                            onClick={handleOpenNavMenu}
                            color="inherit"
                        >
                            <MenuIcon />
                        </IconButton>
                    </Box>

                    {/* Mobile Logo */}
                    <Box
                        sx={{
                            flexGrow: 1,
                            display: { xs: 'flex', md: 'none' },
                            justifyContent: 'center',
                            cursor: 'pointer',
                            alignItems: 'center'
                        }}
                        onClick={() => navigate('/')}
                    >
                        <Box sx={{ backgroundColor: 'white', p: '6px 14px', borderRadius: '6px' }}>
                            <Logo variant="horizontal" sx={{ maxHeight: '45px' }} />
                        </Box>
                    </Box>

                    {/* Desktop Menu */}
                    <Box sx={{ flexGrow: 1, display: { xs: 'none', md: 'flex' }, justifyContent: 'flex-end' }}>
                        {pages.map((page) => (
                            <Box key={page.title}>
                                <Button
                                    onClick={(e) => handleOpenMenu(e, page.title)}
                                    sx={{ my: 2, color: 'white', display: 'block', fontWeight: 600 }}
                                    endIcon={<ExpandMore />}
                                >
                                    {page.title}
                                </Button>
                                <Menu
                                    anchorEl={anchorElMenus[page.title]}
                                    open={Boolean(anchorElMenus[page.title])}
                                    onClose={() => handleCloseMenu(page.title)}
                                    MenuListProps={{ onMouseLeave: () => handleCloseMenu(page.title) }}
                                >
                                    {page.items.map((item) => (
                                        <MenuItem key={item.name} onClick={() => handleNavigate(item.path)}>
                                            <Typography textAlign="center">{item.name}</Typography>
                                        </MenuItem>
                                    ))}
                                </Menu>
                            </Box>
                        ))}
                    </Box>
                </Toolbar>
            </Container>

            {/* Mobile Drawer */}
            <Drawer
                anchor="left"
                open={mobileOpen}
                onClose={handleCloseNavMenu}
                sx={{
                    display: { xs: 'block', md: 'none' },
                    '& .MuiDrawer-paper': { boxSizing: 'border-box', width: 250 },
                }}
            >
                <Box sx={{ p: 2, display: 'flex', justifyContent: 'center', backgroundColor: '#003366' }}>
                    <Box sx={{ backgroundColor: 'white', p: '8px 16px', borderRadius: '8px', width: 'fit-content' }}>
                        <Logo variant="horizontal" sx={{ maxHeight: '50px' }} />
                    </Box>
                </Box>
                <List>
                    <ListItem button onClick={() => handleNavigate('/')}>
                        <ListItemText primary="Home" />
                    </ListItem>
                    {pages.map((page) => (
                        <React.Fragment key={page.title}>
                            <ListItem button onClick={() => toggleMobileMenu(page.title)}>
                                <ListItemText primary={page.title} />
                                {mobileMenuOpen[page.title] ? <ExpandLess /> : <ExpandMore />}
                            </ListItem>
                            <Collapse in={mobileMenuOpen[page.title]} timeout="auto" unmountOnExit>
                                <List component="div" disablePadding>
                                    {page.items.map((item) => (
                                        <ListItem button key={item.name} sx={{ pl: 4 }} onClick={() => handleNavigate(item.path)}>
                                            <ListItemText primary={item.name} />
                                        </ListItem>
                                    ))}
                                </List>
                            </Collapse>
                        </React.Fragment>
                    ))}
                </List>
            </Drawer>
        </AppBar>
    );
};

export default Navbar;
