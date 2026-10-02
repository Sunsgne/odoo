import { useEffect, useState } from "react";
import { Alert, Box, Button, Card, CardContent, MenuItem, TextField, Typography } from "@mui/material";
import { call } from "../api";

export function IpamPage() {
  const [domains, setDomains] = useState([]);
  const [domainId, setDomainId] = useState("");
  const [address, setAddress] = useState("");
  const [object, setObject] = useState("");
  const [hit, setHit] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    call("zenlenet.prefix", "ipam_domains", []).then(setDomains).catch((err) => setError(err.message));
  }, []);

  async function search(event) {
    event.preventDefault();
    setError("");
    try {
      const found = await call("zenlenet.prefix", "ipam_lookup", [], {
        address,
        obj: object,
        domain_id: domainId ? Number(domainId) : false,
      });
      if (!found.prefix_id) {
        setHit(null);
        setError("没有匹配");
        return;
      }
      const [row] = await call("zenlenet.prefix", "read", [[found.prefix_id], ["prefix", "status", "partner_id", "description"]]);
      setHit(row);
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <Box sx={{ maxWidth: 720, mx: "auto", mt: 6 }}>
      <Card>
        <CardContent>
          <Box component="form" onSubmit={search} sx={{ display: "grid", gap: 2 }}>
            <TextField select label="管理域" value={domainId} onChange={(event) => setDomainId(event.target.value)}>
              <MenuItem value="">全部</MenuItem>
              {domains.map((item) => <MenuItem key={item.id} value={item.id}>{item.name}</MenuItem>)}
            </TextField>
            <TextField label="地址" value={address} onChange={(event) => setAddress(event.target.value)} />
            <TextField label="对象" value={object} onChange={(event) => setObject(event.target.value)} />
            <Button type="submit" variant="contained">搜索</Button>
          </Box>
        </CardContent>
      </Card>
      {error ? <Alert severity="warning" sx={{ mt: 2 }}>{error}</Alert> : null}
      {hit ? (
        <Card sx={{ mt: 2 }}>
          <CardContent>
            <Typography variant="h6">{hit.prefix}</Typography>
            <Typography color="text.secondary">{hit.status}</Typography>
            <Typography>{Array.isArray(hit.partner_id) ? hit.partner_id[1] : ""}</Typography>
            <Typography>{hit.description || ""}</Typography>
          </CardContent>
        </Card>
      ) : null}
    </Box>
  );
}
