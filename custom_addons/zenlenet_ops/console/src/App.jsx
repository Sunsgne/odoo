import { useEffect, useState } from "react";
import { HashRouter } from "react-router-dom";
import { CssBaseline, LinearProgress, ThemeProvider } from "@mui/material";
import { theme } from "./theme";
import { who } from "./api";
import { Login } from "./pages/Login";
import { Shell } from "./shell/Shell";

export function App() {
  const [session, setSession] = useState(null);

  useEffect(() => {
    who().then(setSession).catch(() => setSession({ uid: false, db: "zenlenet" }));
  }, []);

  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      {!session ? <LinearProgress /> : session.uid ? (
        <HashRouter>
          <Shell session={session} />
        </HashRouter>
      ) : (
        <Login db={session.db} onDone={setSession} />
      )}
    </ThemeProvider>
  );
}
