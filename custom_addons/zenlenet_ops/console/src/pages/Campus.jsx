import { useEffect, useState } from "react";
import { Box, Button, Card, CardActionArea, CardContent, LinearProgress, TextField, Typography } from "@mui/material";
import { call } from "../api";

export function CampusPage({ navigate }) {
  const [sites, setSites] = useState([]);
  const [region, setRegion] = useState("");
  const [state, setState] = useState("");
  const [query, setQuery] = useState("");

  async function load(text = query) {
    setSites(await call("zenlenet.datacenter", "dc_tree", [text]));
  }

  useEffect(() => { load("").catch(() => {}); }, []);

  const regions = [...new Set(sites.map((site) => site.region || "未分地区"))];
  const visible = sites.filter((site) => (!region || site.region === region) && (!state || site.state === state));
  const groups = {};
  visible.forEach((site) => {
    const name = site.region || "未分地区";
    groups[name] = groups[name] || [];
    groups[name].push(site);
  });

  return (
    <Box>
      <Box sx={{ display: "flex", gap: 1, flexWrap: "wrap", mb: 2 }}>
        <Button variant={region ? "outlined" : "contained"} onClick={() => setRegion("")}>全部</Button>
        {regions.map((name) => (
          <Button key={name} variant={region === name ? "contained" : "outlined"} onClick={() => setRegion(name)}>{name}</Button>
        ))}
        <Button variant={state === "active" ? "contained" : "outlined"} onClick={() => setState(state === "active" ? "" : "active")}>在用</Button>
        <Button variant={state === "planning" ? "contained" : "outlined"} onClick={() => setState(state === "planning" ? "" : "planning")}>规划中</Button>
        <TextField size="small" label="名称" value={query} onChange={(event) => setQuery(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") load(); }} />
      </Box>
      {Object.entries(groups).map(([name, rows]) => (
        <Box key={name} sx={{ mb: 3 }}>
          <Typography variant="h6" sx={{ mb: 1 }}>{name}</Typography>
          <Box sx={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: 2 }}>
            {rows.map((site) => (
              <Card key={site.id}>
                <CardActionArea onClick={() => navigate("/prefixes")}>
                  <CardContent>
                    <Typography variant="subtitle1">{site.name}</Typography>
                    <Typography variant="body2" color="text.secondary">{site.facility}</Typography>
                    <Typography variant="body2" sx={{ mt: 1 }}>{site.device_count} 设备 · {site.prefix_count} 地址段 · {site.line_count} 线路</Typography>
                    <Typography variant="body2">{site.power_used_kw} / {site.power_kw} kW</Typography>
                    <LinearProgress variant="determinate" value={site.power_percent || 0} color={site.power_over ? "error" : "primary"} sx={{ mt: 1 }} />
                  </CardContent>
                </CardActionArea>
              </Card>
            ))}
          </Box>
        </Box>
      ))}
    </Box>
  );
}
