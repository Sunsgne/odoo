import { useEffect, useState } from "react";
import { Box, Card, CardContent, Chip, List, ListItemButton, ListItemText, Typography } from "@mui/material";
import { call } from "../api";

export function ItamPage({ navigate }) {
  const [category, setCategory] = useState(false);
  const [board, setBoard] = useState(null);

  useEffect(() => {
    call("zenlenet.asset", "itam_board", [category]).then(setBoard);
  }, [category]);

  if (!board) {
    return null;
  }

  return (
    <Box>
      <Box sx={{ display: "flex", gap: 1, flexWrap: "wrap", mb: 2 }}>
        <Chip label="全部" color={category ? "default" : "primary"} onClick={() => setCategory(false)} />
        {board.categories.map((row) => (
          <Chip key={row.key} label={`${row.label} ${row.count}`} color={category === row.key ? "primary" : "default"} onClick={() => setCategory(category === row.key ? false : row.key)} />
        ))}
      </Box>
      <Box sx={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: 2 }}>
        <Card><CardContent><Typography variant="h3">{board.total}</Typography><Typography>资产总量</Typography><Typography color="text.secondary">自有 {board.owned_share}% · 非自有 {board.other_share}%</Typography></CardContent></Card>
        <Card><CardContent><Typography variant="h6">资产分布</Typography>{Object.entries({ in_rack: "在机柜内", stock: "在仓库内", unknown: "未知", repair: "维修", loan: "外借" }).map(([key, label]) => <Typography key={key}>{label} {board.places[key]}</Typography>)}</CardContent></Card>
        <CountCard title="数据中心" rows={board.datacenters} />
        <CountCard title="机房" rows={board.rooms} />
        <CountCard title="保质期" rows={board.warranties} />
        <CountCard title="资产型号" rows={board.models} />
        <CountCard title="资产属主" rows={board.owners} />
        <Card>
          <CardContent>
            <Typography variant="h6">进行中任务</Typography>
            <List dense>
              {board.tasks.map((task) => (
                <ListItemButton key={task.id} onClick={() => navigate("/asset-tasks")}>
                  <ListItemText primary={task.name} secondary={`${task.kind} ${task.asset}`} />
                </ListItemButton>
              ))}
            </List>
          </CardContent>
        </Card>
      </Box>
    </Box>
  );
}

function CountCard({ title, rows }) {
  return (
    <Card>
      <CardContent>
        <Typography variant="h6">{title}</Typography>
        {(rows || []).map((row) => (
          <Box key={row.key || row.label} sx={{ display: "flex", justifyContent: "space-between" }}>
            <Typography variant="body2">{row.label}</Typography>
            <Typography variant="body2">{row.count}</Typography>
          </Box>
        ))}
      </CardContent>
    </Card>
  );
}
