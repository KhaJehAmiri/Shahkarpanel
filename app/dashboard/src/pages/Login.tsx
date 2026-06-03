import {
  Alert,
  AlertDescription,
  AlertIcon,
  Box,
  Button,
  chakra,
  FormControl,
  HStack,
  Text,
  VStack,
} from "@chakra-ui/react";
import { ArrowRightOnRectangleIcon } from "@heroicons/react/24/outline";
import { zodResolver } from "@hookform/resolvers/zod";
import React, { FC, useEffect, useState } from "react";
import { FieldValues, useForm } from "react-hook-form";
import { useLocation, useNavigate } from "react-router-dom";
import { z } from "zod";
import { Input } from "components/Input";
import { fetch } from "service/http";
import { removeAuthToken, setAuthToken } from "utils/authStorage";
import { ReactComponent as Logo } from "assets/logo.svg";
import { useTranslation } from "react-i18next";
import { Language } from "components/Language";

const schema = z.object({
  username: z.string().min(1, "login.fieldRequired"),
  password: z.string().min(1, "login.fieldRequired"),
});

export const LogoIcon = chakra(Logo, {
  baseStyle: { w: 14, h: 14 },
});

const LoginIcon = chakra(ArrowRightOnRectangleIcon, {
  baseStyle: { w: 5, h: 5, strokeWidth: "2px" },
});

export const Login: FC = () => {
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();
  const { t } = useTranslation();
  const location = useLocation();
  const {
    register,
    formState: { errors },
    handleSubmit,
  } = useForm({ resolver: zodResolver(schema) });

  useEffect(() => {
    removeAuthToken();
    if (location.pathname !== "/login") {
      navigate("/login", { replace: true });
    }
  }, []);

  const login = (values: FieldValues) => {
    setError("");
    const formData = new FormData();
    formData.append("username", values.username);
    formData.append("password", values.password);
    formData.append("grant_type", "password");
    setLoading(true);
    fetch("/admin/token", { method: "post", body: formData })
      .then(({ access_token: token }) => {
        setAuthToken(token);
        navigate("/");
      })
      .catch((err) => {
        setError(err.response._data.detail);
      })
      .finally(() => setLoading(false));
  };

  return (
    <Box className="nxp-login-page" minH="100vh" w="full" position="relative">
      <HStack position="absolute" top={6} right={6} zIndex={2}>
        <Language />
      </HStack>
      <FlexCenter>
        <Box className="nxp-login-card" w="full" maxW="420px" p={{ base: 6, md: 10 }}>
          <VStack spacing={6} w="full">
            <LogoIcon color="var(--chakra-colors-accent-400)" />
            <VStack spacing={1}>
              <Text fontSize="2xl" fontWeight="bold" letterSpacing="-0.03em">
                NexusPanel
              </Text>
              <Text color="gray.500" fontSize="sm" textAlign="center">
                {t("login.welcomeBack")}
              </Text>
            </VStack>
            <Box w="full">
              <form onSubmit={handleSubmit(login)}>
                <VStack spacing={4}>
                  <FormControl>
                    <Input
                      w="full"
                      placeholder={t("username")}
                      {...register("username")}
                      error={t(errors?.username?.message as string)}
                    />
                  </FormControl>
                  <FormControl>
                    <Input
                      w="full"
                      type="password"
                      placeholder={t("password")}
                      {...register("password")}
                      error={t(errors?.password?.message as string)}
                    />
                  </FormControl>
                  {error && (
                    <Alert status="error" rounded="lg" w="full">
                      <AlertIcon />
                      <AlertDescription>{error}</AlertDescription>
                    </Alert>
                  )}
                  <Button
                    isLoading={loading}
                    type="submit"
                    w="full"
                    size="lg"
                    colorScheme="accent"
                  >
                    <LoginIcon marginRight={1} />
                    {t("login")}
                  </Button>
                </VStack>
              </form>
            </Box>
            <Text fontSize="xs" color="gray.600">
              Professional proxy control plane
            </Text>
          </VStack>
        </Box>
      </FlexCenter>
    </Box>
  );
};

const FlexCenter: FC<{ children: React.ReactNode }> = ({ children }) => (
  <Box
    minH="100vh"
    display="flex"
    alignItems="center"
    justifyContent="center"
    px={4}
    py={12}
  >
    {children}
  </Box>
);

export default Login;
