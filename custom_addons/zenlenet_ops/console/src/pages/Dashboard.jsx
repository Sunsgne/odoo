import { useEffect, useState } from "react";
import { Alert, Box, Card, CardActionArea, CardContent, TextField, Typography } from "@mui/material";
import { call } from "../api";

const CARDS = [
  ["flows_mine", "我的在办交付", "flows"],
  ["tickets_overdue", "超时工单", "tickets"],
  ["unpaid_count", "未收款", "invoices"],
  ["contracts_expiring", "待续签合同", "contracts"],
  ["customers_active", "在网客户", "customers"],
  ["services_active", "在网服务", "quotes"],
  ["quotes_open", "待确认报价", "quotes"],
  ["ip_usage", "IP 使用率", "ipam"],
  ["lines_active", "在用线路", "lines"],
  ["datacenters", "数据中心", "campus"],
];

export function Dashboard({ navigate }) {
  const [home, setHome] = useState(null);
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState([]);
  const [error, setError] = useState("");

  useEffect(() => {
    call("zenlenet.home", "search_read", [], {
      fields: CARDS.map(([key]) => key).concat(["id", "unpaid_amount", "ip_free", "ip_total"]),
      limit: 1,
    }).then((rows) => setHome(rows[0] || {})).catch((err) => setError(err.message));
  }, []);

  async function search(event) {
    event.preventDefault();
    setHits(await call("zenlenet.home", "lookup", [query]));
  }

  return (
    <Box>
      {error ? <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert> : null}
      <Box component="form" onSubmit={search} sx={{ mb: 3, maxWidth: 640 }}>
        <TextField fullWidth label="查询" value={query} onChange={(event) => setQuery(event.target.value)} />
      </Box>
      {hits.length ? (
        <Card sx={{ mb: 3 }}>
          {hits.map((hit) => (
            <CardActionArea key={hit.key} onClick={() => navigate(`/open/${encodeURIComponent(hit.action.res_model)}/${hit.action.res_id}`)} sx={{ px: 2, py: 1 }}>
              <Typography variant="body2" color="text.secondary">{hit.kind}</Typography>
              <Typography>{hit.label}</Typography>
            </CardActionArea>
          ))}
        </Card>
      ) : null}
      <Box sx={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: 2 }}>
        {CARDS.map(([key, label, page]) => (
          <Card key={key}>
            <CardActionArea onClick={() => navigate(`/${page}`)}>
              <CardContent>
                <Typography variant="h4">{home ? home[key] : "—"}{key === "ip_usage" && home ? "%" : ""}</Typography>
                <Typography color="text.secondary">{label}</Typography>
              </CardContent>
            </CardActionArea>
          </Card>
        ))}
      </Box>
    </Box>
  );
}
