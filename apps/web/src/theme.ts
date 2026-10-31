import { createTheme } from "@mui/material/styles";

export const theme = createTheme({
  palette: {
    primary: { main: "#1f4e8c" },
    secondary: { main: "#0f766e" },
    background: { default: "#f5f7fa" },
  },
  shape: { borderRadius: 8 },
  typography: { fontFamily: '"Segoe UI", Roboto, Helvetica, Arial, sans-serif', h5: { fontWeight: 600 } },
  components: {
    MuiButton: { defaultProps: { disableElevation: true }, styleOverrides: { root: { textTransform: "none" } } },
    MuiPaper: { defaultProps: { variant: "outlined" } },
  },
});
