import { createBrowserRouter, type RouteObject } from "react-router";

import { HomeRedirect, RequireAuth } from "./components/AppShell";
import { ActivityPage } from "./pages/ActivityPage";
import { AdminAccessPage } from "./pages/AdminAccessPage";
import { AgentsPage } from "./pages/AgentsPage";
import { NewRunPage } from "./pages/NewRunPage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { RunPage } from "./pages/RunPage";
import { RunsPage } from "./pages/RunsPage";
import { SignInPage } from "./pages/SignInPage";
import { StylePage } from "./pages/StylePage";
import { UploadsPage } from "./pages/UploadsPage";
import { UsagePage } from "./pages/UsagePage";
import { WorkspaceSettingsPage } from "./pages/WorkspaceSettingsPage";

export const routes: RouteObject[] = [
  { path: "/signin", element: <SignInPage /> },
  {
    element: <RequireAuth />,
    children: [
      { index: true, element: <HomeRedirect /> },
      { path: "w/:workspaceId/runs", element: <RunsPage /> },
      { path: "w/:workspaceId/new", element: <NewRunPage /> },
      { path: "w/:workspaceId/documents", element: <UploadsPage /> },
      { path: "w/:workspaceId/agents", element: <AgentsPage /> },
      { path: "w/:workspaceId/style", element: <StylePage /> },
      { path: "w/:workspaceId/usage", element: <UsagePage /> },
      { path: "w/:workspaceId/activity", element: <ActivityPage /> },
      { path: "w/:workspaceId/settings", element: <WorkspaceSettingsPage /> },
      { path: "runs/:runId", element: <RunPage /> },
      { path: "admin/access", element: <AdminAccessPage /> },
    ],
  },
  {
    path: "*",
    element: (
      <main className="content" id="main">
        <NotFoundPage />
      </main>
    ),
  },
];

export const router = createBrowserRouter(routes);
