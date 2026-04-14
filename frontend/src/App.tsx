import { useEffect, useState } from "react";
import { NavLink, Route, Routes } from "react-router-dom";
import { fetchModels, fetchProjects } from "./api";
import { ConfigPage } from "./pages/ConfigPage";
import { WorkspacePage } from "./pages/WorkspacePage";
import type { Project } from "./types";

export default function App() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [models, setModels] = useState<string[]>([]);
  const [defaultModel, setDefaultModel] = useState("");
  const [error, setError] = useState("");

  async function reload() {
    try {
      const [projectPayload, modelPayload] = await Promise.all([
        fetchProjects(),
        fetchModels(),
      ]);
      setProjects(projectPayload.projects);
      setModels(modelPayload.models);
      setDefaultModel(modelPayload.defaultModel);
      setError("");
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "Failed to load application data.",
      );
    }
  }

  useEffect(() => {
    void reload();
  }, []);

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="app-brand">
          <div className="brand-mark" aria-hidden="true">
            PO
          </div>
          <div className="brand-copy">
            <p className="eyebrow">Cafe Workspace</p>
            <h1>Prompt Optimizer</h1>
            <p className="app-tagline">
              Turn repository changes into a clear implementation brief.
            </p>
          </div>
        </div>
        <nav className="top-nav" aria-label="Primary">
          <NavLink to="/">Config</NavLink>
          {projects[0] ? (
            <NavLink to={`/workspace/${projects[0].id}`}>Workspace</NavLink>
          ) : null}
        </nav>
      </header>

      {error ? <div className="status-banner error">{error}</div> : null}

      <Routes>
        <Route
          path="/"
          element={
            <ConfigPage
              defaultModel={defaultModel}
              models={models}
              projects={projects}
              onSaved={reload}
            />
          }
        />
        <Route path="/workspace/:projectId" element={<WorkspacePage />} />
      </Routes>
    </div>
  );
}
