import { createTheme } from "@mui/material/styles";

export const theme = createTheme({
  palette: {
    mode: "light",
    primary: { main: "#1976d2" },
    secondary: { main: "#9c27b0" },
    background: { default: "#f5f5f5", paper: "#ffffff" },
    error: { main: "#d32f2f" },
    warning: { main: "#ed6c02" },
    success: { main: "#2e7d32" },
  },
  shape: { borderRadius: 4 },
  typography: {
    fontFamily: 'Roboto, "Noto Sans SC", "PingFang SC", "Microsoft YaHei", sans-serif',
    h5: { fontWeight: 500 },
    h6: { fontWeight: 500 },
    button: { textTransform: "none", fontWeight: 500 },
  },
  components: {
    MuiButton: { defaultProps: { disableElevation: true } },
    MuiPaper: { defaultProps: { elevation: 1 } },
  },
});
