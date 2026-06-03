import {
  Box,
  Flex,
  HStack,
  IconButton,
  Text,
  useColorMode,
  VStack,
} from "@chakra-ui/react";
import {
  ArrowLeftOnRectangleIcon,
  MoonIcon,
  Squares2X2Icon,
  SunIcon,
  SwatchIcon,
  UsersIcon,
} from "@heroicons/react/24/outline";
import { FC, ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link as RouterLink } from "react-router-dom";
import { ReactComponent as Logo } from "assets/logo.svg";
import { Language } from "./Language";
import { updateThemeColor } from "utils/themeColor";

type ShellProps = {
  children: ReactNode;
  title?: string;
  actions?: ReactNode;
};

export const Shell: FC<ShellProps> = ({ children, title, actions }) => {
  const { t } = useTranslation();
  const { colorMode, toggleColorMode } = useColorMode();

  return (
    <Flex minH="100vh" bg="chakra-body-bg">
      <Box
        as="aside"
        w={{ base: "0", md: "240px" }}
        display={{ base: "none", md: "flex" }}
        flexDirection="column"
        borderRightWidth="1px"
        borderColor="whiteAlpha.100"
        bg={{ _dark: "gray.850", _light: "white" }}
        px={4}
        py={6}
        position="sticky"
        top={0}
        h="100vh"
      >
        <HStack spacing={3} mb={10}>
          <Box as={Logo} w={9} h={9} color="accent.400" />
          <VStack align="start" spacing={0}>
            <Text fontWeight="bold" fontSize="lg" letterSpacing="-0.02em">
              NexusPanel
            </Text>
            <Text fontSize="xs" color="gray.500">
              Control Plane
            </Text>
          </VStack>
        </HStack>
        <VStack align="stretch" spacing={1} flex={1}>
          <HStack
            as={RouterLink}
            to="/"
            px={3}
            py={2.5}
            borderRadius="lg"
            bg={title ? "transparent" : "whiteAlpha.100"}
            color={title ? "gray.500" : "accent.300"}
            fontWeight="semibold"
            fontSize="sm"
            _hover={{ bg: "whiteAlpha.100" }}
          >
            <UsersIcon width={18} />
            <Text>{t("users")}</Text>
          </HStack>
          <HStack
            as={RouterLink}
            to="/manage"
            px={3}
            py={2.5}
            borderRadius="lg"
            bg={title ? "whiteAlpha.100" : "transparent"}
            color={title ? "accent.300" : "gray.500"}
            fontWeight="semibold"
            fontSize="sm"
            _hover={{ bg: "whiteAlpha.100" }}
          >
            <SwatchIcon width={18} />
            <Text>White-label</Text>
          </HStack>
          <HStack
            px={3}
            py={2.5}
            borderRadius="lg"
            color="gray.500"
            fontSize="sm"
            opacity={0.7}
          >
            <Squares2X2Icon width={18} />
            <Text>Analytics</Text>
          </HStack>
        </VStack>
        <Text fontSize="xs" color="gray.600" mt={4}>
          © NexusPanel
        </Text>
      </Box>

      <Flex direction="column" flex={1} minW={0}>
        <HStack
          as="header"
          px={{ base: 4, md: 8 }}
          py={4}
          borderBottomWidth="1px"
          borderColor="whiteAlpha.100"
          justify="space-between"
          bg={{ _dark: "surface.950", _light: "white" }}
          position="sticky"
          top={0}
          zIndex={10}
          backdropFilter="blur(12px)"
        >
          <HStack spacing={3} display={{ base: "flex", md: "none" }}>
            <Box as={Logo} w={8} h={8} color="accent.400" />
            <Text fontWeight="bold">NexusPanel</Text>
          </HStack>
          <Text
            as="h1"
            fontWeight="semibold"
            fontSize="xl"
            display={{ base: "none", md: "block" }}
          >
            {title ?? t("users")}
          </Text>
          <HStack spacing={2}>
            {actions}
            <Language />
            <IconButton
              size="sm"
              variant="ghost"
              aria-label="toggle theme"
              icon={colorMode === "light" ? <MoonIcon width={18} /> : <SunIcon width={18} />}
              onClick={() => {
                updateThemeColor(colorMode === "dark" ? "light" : "dark");
                toggleColorMode();
              }}
            />
            <IconButton
              as={RouterLink}
              to="/login"
              size="sm"
              variant="ghost"
              aria-label="logout"
              icon={<ArrowLeftOnRectangleIcon width={18} />}
            />
          </HStack>
        </HStack>
        <Box
          as="main"
          flex={1}
          px={{ base: 4, md: 8 }}
          py={6}
          maxW="1600px"
          w="full"
          mx="auto"
        >
          {children}
        </Box>
      </Flex>
    </Flex>
  );
};
