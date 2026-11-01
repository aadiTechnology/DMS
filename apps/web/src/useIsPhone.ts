import { useMediaQuery, type Theme } from "@mui/material";

/** True on a phone-sized screen (the same breakpoint the application shell switches at). */
export const useIsPhone = () => useMediaQuery((th: Theme) => th.breakpoints.down("md"));
