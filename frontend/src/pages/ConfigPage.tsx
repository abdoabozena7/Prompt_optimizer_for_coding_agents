import { FormEvent, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { pickProjectDirectory, saveProject } from "../api";
import type { Project } from "../types";

type ConfigPageProps = {
  defaultModel: string;
  models: string[];
  projects: Project[];
  onSaved: () => Promise<void>;
};

export function ConfigPage({
  defaultModel,
  models,
  projects,
  onSaved,
}: ConfigPageProps) {
  const navigate = useNavigate();
  const [localPath, setLocalPath] = useState("");
  const [remoteUrl, setRemoteUrl] = useState("");
  const [preferredModel, setPreferredModel] = useState(defaultModel);
  const [status, setStatus] = useState("");
  const [saving, setSaving] = useState(false);
  const [pickingDirectory, setPickingDirectory] = useState(false);

  useEffect(() => {
    if (!preferredModel && defaultModel) {
      setPreferredModel(defaultModel);
    }
  }, [defaultModel, preferredModel]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setStatus("");

    try {
      const response = await saveProject({
        local_path: localPath,
        remote_url: remoteUrl,
        preferred_model: preferredModel,
      });
      await onSaved();
      setStatus("Project saved.");
      navigate(`/workspace/${response.project.id}`);
    } catch (caught) {
      setStatus(caught instanceof Error ? caught.message : "Failed to save project.");
    } finally {
      setSaving(false);
    }
  }

  async function handlePickDirectory() {
    setPickingDirectory(true);
    setStatus("");

    try {
      const response = await pickProjectDirectory();
      setLocalPath(response.path);
    } catch (caught) {
      setStatus(
        caught instanceof Error ? caught.message : "Failed to open folder picker.",
      );
    } finally {
      setPickingDirectory(false);
    }
  }
  const recentProjects = projects.slice(0, 6);
  const latestProject = projects[0] ?? null;
  const modelLabel = preferredModel || defaultModel || "No model loaded";

  return (
    <main className="config-page">
      <section className="config-main">
        <div className="page-intro">
          <div>
            <p className="eyebrow">Project Setup</p>
            <h2>Save one repository and keep the workspace ready.</h2>
            <p className="lede">
              Keep the local path, optional remote URL, and preferred model in one
              place so the next analysis session opens with the same context.
            </p>
          </div>
          {latestProject ? (
            <button
              className="secondary-button"
              onClick={() => navigate(`/workspace/${latestProject.id}`)}
              type="button"
            >
              Open latest workspace
            </button>
          ) : null}
        </div>

        <div className="setup-summary-strip" aria-label="Workspace summary">
          <div className="setup-summary-item">
            <span>Saved projects</span>
            <strong>{projects.length}</strong>
          </div>
          <div className="setup-summary-item">
            <span>Available models</span>
            <strong>{models.length || 0}</strong>
          </div>
          <div className="setup-summary-item">
            <span>Current default</span>
            <strong>{defaultModel || "No model loaded"}</strong>
          </div>
        </div>

        <section className="config-surface">
          <div className="surface-heading">
            <div>
              <p className="eyebrow">Details</p>
              <h3>Project details</h3>
            </div>
            <p className="section-copy">
              Start with the repository Prompt Optimizer should track and reuse.
            </p>
          </div>

          <form className="config-form minimal-config-form" onSubmit={handleSubmit}>
            <label className="field-span-wide">
              Local project path
              <div className="path-picker-row">
                <input
                  value={localPath}
                  onChange={(event) => setLocalPath(event.target.value)}
                  placeholder="D:\projects\my-repo"
                  required
                />
                <button
                  className="secondary-button picker-button"
                  disabled={pickingDirectory}
                  onClick={handlePickDirectory}
                  type="button"
                >
                  {pickingDirectory ? "Opening..." : "Choose folder"}
                </button>
              </div>
              <small className="field-help">
                The local path is reused for commit refresh, diff retrieval, and saved
                prompt history.
              </small>
            </label>

            <label>
              Remote repository URL
              <input
                value={remoteUrl}
                onChange={(event) => setRemoteUrl(event.target.value)}
                placeholder="https://github.com/owner/repo"
              />
              <small className="field-help">
                Optional, but useful for remote commit refresh and repository context.
              </small>
            </label>

            <label>
              Preferred model
              <select
                value={preferredModel}
                onChange={(event) => setPreferredModel(event.target.value)}
              >
                {models.length ? (
                  models.map((model) => (
                    <option key={model} value={model}>
                      {model}
                    </option>
                  ))
                ) : (
                  <option value={defaultModel}>{defaultModel || "Load models first"}</option>
                )}
              </select>
              <small className="field-help">
                Current selection: {modelLabel}.
              </small>
            </label>

            <div className="config-actions">
              <button className="primary-button" disabled={saving} type="submit">
                {saving ? "Saving..." : "Save and open workspace"}
              </button>
            </div>
          </form>

          {status ? <p className="form-status config-status">{status}</p> : null}
        </section>
      </section>

      <aside className="config-dock">
        <div className="config-dock-header">
          <div>
            <p className="eyebrow">Saved workspaces</p>
            <h3>{projects.length ? `${projects.length} remembered` : "No saved projects"}</h3>
          </div>
          <span className="dock-meta">Recent</span>
        </div>
        <p className="dock-note">
          Reopen a repository without re-entering its path, remote URL, or model.
        </p>

        {recentProjects.length ? (
          <div className="config-project-list">
            {recentProjects.map((project) => (
              <button
                key={project.id}
                className="config-project-item"
                onClick={() => navigate(`/workspace/${project.id}`)}
                type="button"
              >
                <strong>{project.name}</strong>
                <span>{project.localPath}</span>
                <small>{project.preferredModel || "No preferred model"}</small>
              </button>
            ))}
          </div>
        ) : (
          <p className="empty-copy config-empty-copy">
            Save one project to keep its local path, remote URL, and preferred model
            ready for the workspace.
          </p>
        )}
      </aside>
    </main>
  );
}
