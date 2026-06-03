import { extendTheme, type ThemeConfig } from "@chakra-ui/react";

const config: ThemeConfig = {
  initialColorMode: "dark",
  useSystemColorMode: false,
};

export const theme = extendTheme({
  config,
  shadows: {
    outline: "0 0 0 2px var(--chakra-colors-accent-400)",
    card: "0 8px 32px rgba(0, 0, 0, 0.24)",
    glow: "0 0 40px rgba(45, 212, 191, 0.15)",
  },
  radii: {
    xl: "1rem",
    "2xl": "1.25rem",
    "3xl": "1.5rem",
  },
  fonts: {
    heading:
      '"Plus Jakarta Sans", Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
    body: '"Plus Jakarta Sans", Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
  },
  styles: {
    global: (props: { colorMode: string }) => ({
      body: {
        bg: props.colorMode === "dark" ? "surface.950" : "gray.50",
        color: props.colorMode === "dark" ? "gray.100" : "gray.800",
      },
      "#root": {
        minHeight: "100vh",
      },
    }),
  },
  colors: {
    "light-border": "#e2e8f0",
    accent: {
      50: "#ccfbf1",
      100: "#99f6e4",
      200: "#5eead4",
      300: "#2dd4bf",
      400: "#14b8a6",
      500: "#0d9488",
      600: "#0f766e",
      700: "#115e59",
      800: "#134e4a",
      900: "#042f2e",
    },
    primary: {
      50: "#ccfbf1",
      100: "#99f6e4",
      200: "#5eead4",
      300: "#2dd4bf",
      400: "#14b8a6",
      500: "#0d9488",
      600: "#0f766e",
      700: "#115e59",
      800: "#134e4a",
      900: "#042f2e",
    },
    brand: {
      500: "#6366f1",
      600: "#4f46e5",
    },
    surface: {
      900: "#0f1419",
      950: "#0a0e12",
    },
    gray: {
      750: "#1a2332",
      850: "#121a24",
    },
  },
  semanticTokens: {
    colors: {
      "chakra-body-bg": { _light: "gray.50", _dark: "surface.950" },
      "chakra-body-text": { _light: "gray.800", _dark: "gray.100" },
    },
  },
  components: {
    Button: {
      defaultProps: { colorScheme: "accent" },
      baseStyle: {
        fontWeight: "semibold",
        borderRadius: "lg",
      },
    },
    Alert: {
      baseStyle: {
        container: { borderRadius: "lg", fontSize: "sm" },
      },
    },
    Card: {
      baseStyle: {
        container: {
          borderRadius: "2xl",
          _dark: { bg: "gray.850", borderColor: "whiteAlpha.100" },
          _light: { bg: "white", borderColor: "gray.200" },
        },
      },
    },
    Select: {
      baseStyle: {
        field: {
          borderRadius: "lg",
          _dark: { borderColor: "whiteAlpha.200" },
        },
      },
    },
    FormLabel: {
      baseStyle: {
        fontSize: "sm",
        fontWeight: "medium",
        mb: "1",
        _dark: { color: "gray.300" },
      },
    },
    Input: {
      baseStyle: {
        field: {
          borderRadius: "lg",
          _focusVisible: {
            boxShadow: "0 0 0 1px var(--chakra-colors-accent-400)",
            borderColor: "accent.400",
          },
          _dark: {
            bg: "surface.900",
            borderColor: "whiteAlpha.200",
            _placeholder: { color: "gray.500" },
          },
        },
      },
    },
    Table: {
      baseStyle: {
        table: { borderCollapse: "separate", borderSpacing: 0 },
        thead: { borderBottomColor: "light-border" },
        th: {
          background: "#f8fafc",
          borderColor: "light-border !important",
          borderBottomColor: "light-border !important",
          borderTop: "1px solid",
          borderTopColor: "light-border !important",
          _first: { borderLeft: "1px solid", borderColor: "light-border !important" },
          _last: { borderRight: "1px solid", borderColor: "light-border !important" },
          _dark: {
            borderColor: "whiteAlpha.200 !important",
            background: "gray.850",
          },
        },
        td: {
          transition: "all .1s ease-out",
          borderColor: "light-border",
          _dark: {
            borderColor: "whiteAlpha.100",
            borderBottomColor: "whiteAlpha.100 !important",
          },
        },
        tr: {
          "&.interactive": {
            cursor: "pointer",
            _hover: {
              "& > td": { bg: "gray.100" },
              _dark: { "& > td": { bg: "gray.750" } },
            },
          },
        },
      },
    },
  },
});
