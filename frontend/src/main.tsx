import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "react-router/dom";

import { createQueryClient } from "./api/queryClient";
import { Toaster } from "./components/toast";
import { router } from "./router";
import { applyTheme, storedTheme } from "./theme";
import "./styles.css";

applyTheme(storedTheme());
const queryClient = createQueryClient();

const rootElement = document.getElementById("root");
if (!rootElement) {
  throw new Error("Root element #root not found.");
}

createRoot(rootElement).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
      <Toaster />
    </QueryClientProvider>
  </StrictMode>,
);
