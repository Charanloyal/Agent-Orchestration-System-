import { createBrowserRouter, type RouteObject } from "react-router";

import { HomeRedirect, RequireAuth } from "./components/AppShell";
import { NewRunPage } from "./pages/NewRunPage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { RunPage } from "./pages/RunPage";
import { RunsPage } from "./pages/RunsPage";
import { SignInPage } from "./pages/SignInPage";
import { UploadsPage } from "./pages/UploadsPage";
import { UsagePage } from "./pages/UsagePage";

export const routes: RouteObject[] = [
  { path: "/signin", element: <SignInPage /> },
  {
    element: <RequireAuth />,
    children: [
      { index: true, element: <HomeRedirect /> },
      { path: "w/:workspaceId/runs", element: <RunsPage /> },
      { path: "w/:workspaceId/new", element: <NewRunPage /> },
      { path: "w/:workspaceId/documents", element: <UploadsPage /> },
      { path: "w/:workspaceId/usage", element: <UsagePage /> },
      { path: "runs/:runId", element: <RunPage /> },
    ],
  },
  { path: "*", element: <NotFoundPage /> },
];

export const router = createBrowserRouter(routes);
