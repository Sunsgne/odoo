import { useState } from "react";
import { Alert, Box, Button, Paper, TextField, Typography } from "@mui/material";
import { authenticate, who } from "../api";

export function Login({ db, onDone }) {
  const [login, setLogin] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await authenticate(db || "zenlenet", login, password);
      onDone(await who());
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Box sx={{ minHeight: "100vh", display: "grid", placeItems: "center", bgcolor: "background.default" }}>
      <Paper sx={{ width: 380, p: 4 }}>
        <Typography variant="h5" sx={{ mb: 3 }}>尊领</Typography>
        <Box component="form" onSubmit={submit} sx={{ display: "grid", gap: 2 }}>
          {error ? <Alert severity="error">{error}</Alert> : null}
          <TextField label="账号" value={login} onChange={(event) => setLogin(event.target.value)} autoFocus />
          <TextField label="密码" type="password" value={password} onChange={(event) => setPassword(event.target.value)} />
          <Button type="submit" variant="contained" disabled={busy}>登录</Button>
        </Box>
      </Paper>
    </Box>
  );
}
