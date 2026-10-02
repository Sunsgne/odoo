import { useState } from "react";
import { NavLink, Route, Routes, useNavigate } from "react-router-dom";
import { AppBar, Box, Drawer, List, ListItemButton, ListItemText, ListSubheader, Toolbar, Typography, Button } from "@mui/material";
import { NAV } from "../nav";
import { Dashboard } from "../pages/Dashboard";
import { Resource } from "../pages/Resource";
import { IpamPage } from "../pages/Ipam";
import { CampusPage } from "../pages/Campus";
import { ItamPage } from "../pages/Itam";
import { DutyPage } from "../pages/Duty";
import { PurchasePage } from "../pages/Purchase";

const DRAWER = 240;

export function Shell({ session }) {
  const [title, setTitle] = useState("工作台");
  const navigate = useNavigate();

  return (
    <Box sx={{ display: "flex", minHeight: "100vh", bgcolor: "background.default" }}>
      <AppBar position="fixed" color="inherit" sx={{ zIndex: (theme) => theme.zIndex.drawer + 1 }}>
        <Toolbar>
          <Typography variant="h6" sx={{ flexGrow: 1 }}>{title}</Typography>
          <Typography variant="body2" sx={{ mr: 2 }}>{session.name}</Typography>
          <Button color="primary" onClick={() => { window.location.href = "/web/session/logout?redirect=/zenlenet/console"; }}>退出</Button>
        </Toolbar>
      </AppBar>
      <Drawer variant="permanent" sx={{ width: DRAWER, [`& .MuiDrawer-paper`]: { width: DRAWER, boxSizing: "border-box" } }}>
        <Toolbar />
        <List dense>
          <ListItemButton component={NavLink} to="/home" onClick={() => setTitle("工作台")}>
            <ListItemText primary="工作台" />
          </ListItemButton>
          {NAV.filter((group) => group.items).map((group) => (
            <Box key={group.label}>
              <ListSubheader>{group.label}</ListSubheader>
              {group.items.map((item) => (
                <ListItemButton
                  key={item.key}
                  component={NavLink}
                  to={`/${item.key}`}
                  sx={{ pl: 3 }}
                  onClick={() => setTitle(item.label)}
                >
                  <ListItemText primary={item.label} />
                </ListItemButton>
              ))}
            </Box>
          ))}
        </List>
      </Drawer>
      <Box component="main" sx={{ flexGrow: 1, p: 3, mt: 8, ml: `${DRAWER}px` }}>
        <Routes>
          <Route path="/" element={<Dashboard navigate={navigate} setTitle={setTitle} />} />
          <Route path="/home" element={<Dashboard navigate={navigate} setTitle={setTitle} />} />
          <Route path="/ipam" element={<IpamPage />} />
          <Route path="/campus" element={<CampusPage navigate={navigate} />} />
          <Route path="/itam" element={<ItamPage navigate={navigate} />} />
          <Route path="/duty" element={<DutyPage />} />
          <Route path="/purchase" element={<PurchasePage navigate={navigate} />} />
          <Route path="/open/:model/:id" element={<Resource setTitle={setTitle} />} />
          <Route path="/:key" element={<Resource setTitle={setTitle} />} />
        </Routes>
      </Box>
    </Box>
  );
}
