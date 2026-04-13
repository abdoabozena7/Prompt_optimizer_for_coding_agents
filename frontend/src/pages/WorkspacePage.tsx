import {
  FormEvent,
  startTransition,
  useDeferredValue,
  useEffect,
  useMemo,
  useState,
} from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  analyzeProject,
  fetchDefaultSelection,
  fetchDiff,
  fetchDiffSummary,
  fetchProjectDetail,
  fetchProjects,
  finalizeProject,
  refreshProject,
} from "../api";
import type { AnalysisPayload, Project, SyncSnapshot } from "../types";

type PromptDraft = {
  commitHash: string;
  prompt: string;
};

type ClarificationDraft = {
  question: string;
  selected_option: string;
  custom_text: string;
};

type StatusTone = "neutral" | "success" | "error";
type ParsedEvidence = {
  kind: string;
  title: string;
  summary: string;
  content: string;
};
type WorkspaceStage = "prepare" | "results";

function buildPromptDrafts(
  sync: SyncSnapshot,
  previous: PromptDraft[],
): PromptDraft[] {
  const previousMap = new Map(previous.map((item) => [item.commitHash, item.prompt]));
  return sync.missedCommits.map((commit) => ({
    commitHash: commit.fullHash,
    prompt: previousMap.get(commit.fullHash) ?? "",
  }));
}

function buildClarificationState(analysis: AnalysisPayload): ClarificationDraft[] {
  return analysis.followupQuestions.map((question) => ({
    question: question.question,
    selected_option: question.options[0] ?? "",
    custom_text: "",
  }));
}

function parseEvidenceBlock(raw: string): ParsedEvidence {
  const lines = raw.split("\n");
  const readField = (label: string) =>
    lines
      .find((line) => line.startsWith(`${label}:`))
      ?.slice(label.length + 1)
      .trim() ?? "";
  const contentIndex = lines.findIndex((line) => line.startsWith("Content:"));
  const content =
    contentIndex >= 0
      ? [
          lines[contentIndex].slice("Content:".length).trimStart(),
          ...lines.slice(contentIndex + 1),
        ]
          .join("\n")
          .trim()
      : raw.trim();

  return {
    kind: readField("Kind") || "evidence",
    title: readField("Title") || "Retrieved evidence",
    summary: readField("Summary"),
    content,
  };
}

export function WorkspacePage() {
  const { projectId = "" } = useParams();
  const navigate = useNavigate();
  const [project, setProject] = useState<Project | null>(null);
  const [sync, setSync] = useState<SyncSnapshot | null>(null);
  const [selectedCommits, setSelectedCommits] = useState<string[]>([]);
  const [previewCommit, setPreviewCommit] = useState("");
  const [previewSummary, setPreviewSummary] = useState("");
  const [diffText, setDiffText] = useState("");
  const [diffCommitHash, setDiffCommitHash] = useState("");
  const [isDiffExpanded, setIsDiffExpanded] = useState(false);
  const [currentPrompt, setCurrentPrompt] = useState("");
  const [missedPromptDrafts, setMissedPromptDrafts] = useState<PromptDraft[]>([]);
  const [analysis, setAnalysis] = useState<AnalysisPayload | null>(null);
  const [clarifiedIntent, setClarifiedIntent] = useState("");
  const [clarificationAnswers, setClarificationAnswers] = useState<
    ClarificationDraft[]
  >([]);
  const [finalPrompt, setFinalPrompt] = useState("");
  const [status, setStatus] = useState("");
  const [statusTone, setStatusTone] = useState<StatusTone>("neutral");
  const [workspaceStage, setWorkspaceStage] = useState<WorkspaceStage>("prepare");
  const [loading, setLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [isSelectingDefault, setIsSelectingDefault] = useState(false);
  const [isLoadingDiff, setIsLoadingDiff] = useState(false);
  const [isLoadingSummary, setIsLoadingSummary] = useState(false);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [isGenerating, setIsGenerating] = useState(false);
  const [isBackgroundRefreshing, setIsBackgroundRefreshing] = useState(false);
  const deferredPrompt = useDeferredValue(currentPrompt);
  const working = isAnalyzing || isGenerating;

  function applyWorkspaceState(nextProject: Project, nextSync: SyncSnapshot) {
    startTransition(() => {
      setProject(nextProject);
      setSync(nextSync);
      setSelectedCommits((current) =>
        current.filter((hash) =>
          nextSync.commits.some((commit) => commit.fullHash === hash),
        ).length
          ? current.filter((hash) =>
              nextSync.commits.some((commit) => commit.fullHash === hash),
            )
          : nextSync.defaultSelectedCommitHashes,
      );
      setPreviewCommit(
        (current) =>
          nextSync.commits.some((commit) => commit.fullHash === current)
            ? current
            : nextSync.defaultSelectedCommitHashes[0] || "",
      );
      setMissedPromptDrafts((current) => buildPromptDrafts(nextSync, current));
    });
  }

  async function loadWorkspace() {
    if (!projectId) {
      return;
    }

    try {
      const response = await fetchProjectDetail(projectId);
      applyWorkspaceState(response.project, response.sync);
      setStatus("");
      setStatusTone("neutral");
    } catch (caught) {
      const message =
        caught instanceof Error ? caught.message : "Failed to load the workspace.";

      if (message === "Project not found.") {
        try {
          const projectPayload = await fetchProjects();
          const fallbackProject = [...projectPayload.projects].sort((left, right) =>
            right.updatedAt.localeCompare(left.updatedAt),
          )[0];

          if (fallbackProject) {
            navigate(`/workspace/${fallbackProject.id}`, { replace: true });
            return;
          }
        } catch {
          // Fall through to the regular empty state.
        }
      }

      setStatus(message);
      setStatusTone("error");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadWorkspace();
  }, [projectId]);

  useEffect(() => {
    setWorkspaceStage("prepare");
  }, [projectId]);

  useEffect(() => {
    if (!projectId) {
      return;
    }

    const interval = window.setInterval(() => {
      setIsBackgroundRefreshing(true);
      void refreshProject(projectId)
        .then((response) => {
          applyWorkspaceState(response.project, response.sync);
        })
        .catch(() => undefined)
        .finally(() => setIsBackgroundRefreshing(false));
    }, 45000);

    return () => window.clearInterval(interval);
  }, [projectId]);

  useEffect(() => {
    if (!projectId || !previewCommit) {
      return;
    }

    setIsDiffExpanded(false);
    if (diffCommitHash && diffCommitHash !== previewCommit) {
      setDiffText("");
      setDiffCommitHash("");
    }
    setIsLoadingSummary(true);
    void fetchDiffSummary(projectId, previewCommit)
      .then((response) => setPreviewSummary(response.summary))
      .catch(() => setPreviewSummary(""))
      .finally(() => setIsLoadingSummary(false));
  }, [diffCommitHash, previewCommit, projectId]);

  const promptCompletion = useMemo(
    () => missedPromptDrafts.filter((item) => item.prompt.trim()).length,
    [missedPromptDrafts],
  );
  const clarificationsComplete = useMemo(
    () =>
      clarificationAnswers.length > 0 &&
      clarificationAnswers.every(
        (item) => item.selected_option.trim() || item.custom_text.trim(),
      ),
    [clarificationAnswers],
  );

  const activeTaskLabel = isGenerating
    ? "Generating final prompt..."
    : isAnalyzing
      ? "Analyzing intent..."
      : isLoadingDiff
        ? "Loading selected diff..."
        : isLoadingSummary
          ? "Loading commit summary..."
          : isSelectingDefault
            ? "Selecting missed commits..."
            : isRefreshing
              ? "Refreshing commits..."
              : isBackgroundRefreshing
                ? "Syncing commits in background..."
                : "";

  const latestMissedCommit = sync?.missedCommits[0] ?? null;
  const selectedOlderMissedCommits = useMemo(() => {
    if (!sync?.missedCommits.length) {
      return [];
    }

    return sync.missedCommits.slice(1).filter((commit) =>
      selectedCommits.includes(commit.fullHash),
    );
  }, [selectedCommits, sync]);
  const selectedOlderPromptDrafts = useMemo(() => {
    const promptMap = new Map(
      missedPromptDrafts.map((draft) => [draft.commitHash, draft.prompt]),
    );

    return selectedOlderMissedCommits.map((commit) => ({
      commit,
      prompt: promptMap.get(commit.fullHash) ?? "",
    }));
  }, [missedPromptDrafts, selectedOlderMissedCommits]);
  const selectedOlderPromptCount = selectedOlderPromptDrafts.length;
  const selectedOlderPromptCompletion = selectedOlderPromptDrafts.filter((item) =>
    item.prompt.trim(),
  ).length;
  const parsedEvidence = useMemo(
    () => analysis?.retrievedEvidence.map((item) => parseEvidenceBlock(item)) ?? [],
    [analysis],
  );
  const selectedCommitCount = selectedCommits.length;

  async function handleRefresh() {
    if (!projectId) {
      return;
    }

    setIsRefreshing(true);
    setStatus("Refreshing commits...");
    setStatusTone("neutral");

    try {
      const response = await refreshProject(projectId);
      applyWorkspaceState(response.project, response.sync);
      setStatus("Commit list refreshed.");
      setStatusTone("success");
    } catch (caught) {
      setStatus(caught instanceof Error ? caught.message : "Refresh failed.");
      setStatusTone("error");
    } finally {
      setIsRefreshing(false);
    }
  }

  async function handleSelectAllMissed() {
    if (!projectId) {
      return;
    }

    setIsSelectingDefault(true);
    setStatus("Selecting the default missed commits...");
    setStatusTone("neutral");

    try {
      const response = await fetchDefaultSelection(projectId);
      setSelectedCommits(response.selectedCommitHashes);
      setStatus("Default missed commits selected.");
      setStatusTone("success");
    } catch (caught) {
      setStatus(
        caught instanceof Error ? caught.message : "Could not load default selection.",
      );
      setStatusTone("error");
    } finally {
      setIsSelectingDefault(false);
    }
  }

  async function handlePreviewDiff() {
    if (!projectId || !previewCommit) {
      return;
    }

    if (isDiffExpanded && diffCommitHash === previewCommit) {
      setIsDiffExpanded(false);
      return;
    }

    if (diffText && diffCommitHash === previewCommit) {
      setIsDiffExpanded(true);
      return;
    }

    setIsLoadingDiff(true);
    setStatus("Loading the selected diff...");
    setStatusTone("neutral");

    try {
      const response = await fetchDiff(projectId, previewCommit);
      setDiffText(response.diff);
      setDiffCommitHash(previewCommit);
      setIsDiffExpanded(true);
      setStatus("Diff preview ready.");
      setStatusTone("success");
    } catch (caught) {
      setStatus(caught instanceof Error ? caught.message : "Could not load the diff.");
      setStatusTone("error");
    } finally {
      setIsLoadingDiff(false);
    }
  }

  function toggleCommit(commitHash: string) {
    setSelectedCommits((current) =>
      current.includes(commitHash)
        ? current.filter((item) => item !== commitHash)
        : [...current, commitHash],
    );
  }

  function updatePromptDraft(commitHash: string, prompt: string) {
    setMissedPromptDrafts((current) =>
      current.map((item) =>
        item.commitHash === commitHash ? { ...item, prompt } : item,
      ),
    );
  }

  async function handleAnalyze(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!projectId) {
      return;
    }

    setIsAnalyzing(true);
    setFinalPrompt("");
    setStatus("Analyzing intent and retrieved evidence...");
    setStatusTone("neutral");

    try {
      const response = await analyzeProject(projectId, {
        current_prompt: currentPrompt,
        missed_prompts: selectedOlderPromptDrafts.map((item) => item.prompt),
        selected_commit_hashes: selectedCommits,
      });
      setAnalysis(response.analysis);
      setClarifiedIntent(response.analysis.userIntent);
      setClarificationAnswers(buildClarificationState(response.analysis));
      setWorkspaceStage("results");
      setStatus(
        response.analysis.canGenerateFinalPrompt
          ? "Intent analysis ready."
          : "High-severity blind spots detected. Refine the intent before generating.",
      );
      setStatusTone(response.analysis.canGenerateFinalPrompt ? "success" : "error");
    } catch (caught) {
      setStatus(caught instanceof Error ? caught.message : "Analysis failed.");
      setStatusTone("error");
    } finally {
      setIsAnalyzing(false);
    }
  }

  async function handleFinalize() {
    if (!projectId || !analysis) {
      return;
    }

    setIsGenerating(true);
    setStatus("Generating the final prompt...");
    setStatusTone("neutral");

    try {
      const response = await finalizeProject(projectId, {
        current_prompt: currentPrompt,
        missed_prompts: selectedOlderPromptDrafts.map((item) => item.prompt),
        selected_commit_hashes: selectedCommits,
        clarified_intent: clarifiedIntent,
        analysis_result: {
          agent_intent: analysis.agentIntent,
          user_intent: clarifiedIntent || analysis.userIntent,
          missing_info: analysis.missingInfo,
          blind_spots: analysis.blindSpots,
          can_generate_final_prompt: analysis.canGenerateFinalPrompt,
        },
        clarification_answers: clarificationAnswers,
      });
      setFinalPrompt(response.finalPrompt);
      applyWorkspaceState(response.project, response.sync);
      setStatus("Final prompt generated and project memory updated.");
      setStatusTone("success");
    } catch (caught) {
      setStatus(caught instanceof Error ? caught.message : "Generation failed.");
      setStatusTone("error");
    } finally {
      setIsGenerating(false);
    }
  }

  if (loading) {
    return (
      <main className="workspace-shell">
        <section className="panel loading-panel" aria-busy="true">
          <div className="loading-indicator">
            <span className="loading-dot" aria-hidden="true" />
            <div>
              <strong>Loading workspace</strong>
              <p className="loading-copy">
                Fetching the saved project, recent commits, and default selection.
              </p>
            </div>
          </div>
        </section>
      </main>
    );
  }

  if (!project || !sync) {
    return (
      <main className="workspace-shell">
        <section className="panel loading-panel">
          <div>
            <strong>{status || "Workspace unavailable."}</strong>
            <p className="loading-copy">
              The app could not load this workspace. You can return to config or open
              another saved project.
            </p>
          </div>
        </section>
        <Link to="/">Back to config</Link>
      </main>
    );
  }

  return (
    <main className="workspace-shell">
      <section className="workspace-header">
        <div>
          <p className="eyebrow">Workspace</p>
          <h2>{project.name}</h2>
          <p className="lede">{project.localPath}</p>
        </div>
        <div className="workspace-header-side">
          {activeTaskLabel ? (
            <div className="activity-badge" aria-live="polite">
              <span className="loading-dot small" aria-hidden="true" />
              <span>{activeTaskLabel}</span>
            </div>
          ) : null}
          <div className="workspace-actions">
            <button
              className="secondary-button"
              disabled={isRefreshing || working}
              onClick={handleRefresh}
              type="button"
            >
              {isRefreshing ? "Refreshing..." : "Refresh commits"}
            </button>
            <Link className="secondary-link" to="/">
              Edit config
            </Link>
          </div>
        </div>
      </section>

      {status ? (
        <div className={`status-banner ${statusTone}`} aria-live="polite">
          {status}
        </div>
      ) : null}

      <section className="workspace-stage-bar">
        <button
          className={
            workspaceStage === "prepare"
              ? "workspace-stage-button active"
              : "workspace-stage-button"
          }
          onClick={() => setWorkspaceStage("prepare")}
          type="button"
        >
          1. Setup
        </button>
        <button
          className={
            workspaceStage === "results"
              ? "workspace-stage-button active"
              : "workspace-stage-button"
          }
          disabled={!analysis}
          onClick={() => setWorkspaceStage("results")}
          type="button"
        >
          2. Results
        </button>
      </section>

      {workspaceStage === "prepare" ? (
        <section className="workspace-grid">
          <aside className="panel commit-panel">
            <div className="section-heading">
              <p className="eyebrow">Diff Picker</p>
              <h3>
                {sync.missedCommitCount} missed commit
                {sync.missedCommitCount === 1 ? "" : "s"}
              </h3>
            </div>

            <div className="action-row">
              <button
                className="secondary-button"
                disabled={isSelectingDefault || working}
                onClick={handleSelectAllMissed}
                type="button"
              >
                {isSelectingDefault ? "Selecting..." : "Select all missed"}
              </button>
              <button
                className="secondary-button"
                disabled={working}
                onClick={() => setSelectedCommits([])}
                type="button"
              >
                Clear selection
              </button>
            </div>

            <div className="sync-note">
              {latestMissedCommit
                ? "The main prompt field is for the newest missed commit. Older prompt notes only appear for the commits you select below."
                : "No missed commits are waiting for prompt notes right now."}
            </div>

            <div className="commit-list">
              {sync.commits.map((commit) => (
                <div className="commit-row" key={commit.fullHash}>
                  <input
                    checked={selectedCommits.includes(commit.fullHash)}
                    onChange={() => toggleCommit(commit.fullHash)}
                    type="checkbox"
                  />
                  <button
                    className={
                      previewCommit === commit.fullHash
                        ? "commit-preview active"
                        : "commit-preview"
                    }
                    onClick={() => setPreviewCommit(commit.fullHash)}
                    type="button"
                  >
                    <span>{commit.subject}</span>
                    <small>
                      {commit.shortHash} | {commit.author}
                    </small>
                  </button>
                </div>
              ))}
            </div>

            {isLoadingSummary ? (
              <div className="summary-box loading-box" aria-busy="true">
                <span className="loading-dot small" aria-hidden="true" />
                <span>Summarizing the selected commit...</span>
              </div>
            ) : previewSummary ? (
              <p className="summary-box">{previewSummary}</p>
            ) : null}

            <button
              className="secondary-button"
              disabled={isLoadingDiff || working}
              onClick={handlePreviewDiff}
              type="button"
            >
              {isLoadingDiff
                ? "Loading diff..."
                : isDiffExpanded && diffCommitHash === previewCommit
                  ? "Hide full diff"
                  : "Show full diff"}
            </button>

            {isLoadingDiff ? (
              <div className="diff-box diff-box-loading" aria-busy="true">
                <div className="loading-indicator">
                  <span className="loading-dot" aria-hidden="true" />
                  <div>
                    <strong>Loading full diff</strong>
                    <p className="loading-copy">
                      Pulling the selected commit diff into the preview panel.
                    </p>
                  </div>
                </div>
              </div>
            ) : diffText && isDiffExpanded && diffCommitHash === previewCommit ? (
              <div className="diff-disclosure">
                <div className="diff-disclosure-header">
                  <strong>Full diff</strong>
                  <button
                    className="ghost-button"
                    onClick={() => setIsDiffExpanded(false)}
                    type="button"
                  >
                    Collapse
                  </button>
                </div>
                <pre className="diff-box">{diffText}</pre>
              </div>
            ) : null}
          </aside>

          <section className="panel intent-panel">
            <div className="section-heading">
              <p className="eyebrow">Intent Intake</p>
              <h3>Choose the commits, then describe the newest prompt once.</h3>
            </div>

            <form className="intent-form" onSubmit={handleAnalyze}>
              <div className="setup-summary-strip">
                <div className="setup-summary-item">
                  <span>Selected commits</span>
                  <strong>{selectedCommitCount}</strong>
                </div>
                <div className="setup-summary-item">
                  <span>Newest commit</span>
                  <strong>{latestMissedCommit?.shortHash || "None"}</strong>
                </div>
                <div className="setup-summary-item">
                  <span>Older notes</span>
                  <strong>{selectedOlderPromptCount}</strong>
                </div>
              </div>

              <label>
                {latestMissedCommit
                  ? `Latest prompt for ${latestMissedCommit.subject}`
                  : "Current user intent or latest prompt"}
                <textarea
                  className="prompt-area"
                  onChange={(event) => setCurrentPrompt(event.target.value)}
                  placeholder={
                    latestMissedCommit
                      ? "Describe what the user asked for in the newest selected commit."
                      : "Describe what the user actually wants."
                  }
                  rows={7}
                  value={currentPrompt}
                />
              </label>

              {!!selectedOlderMissedCommits.length ? (
                <div className="missing-prompts">
                  <div className="section-heading compact">
                    <p className="eyebrow">Older Selected Commits</p>
                    <h3>
                      {selectedOlderPromptCompletion}/{selectedOlderPromptCount} filled
                    </h3>
                  </div>
                  {selectedOlderPromptDrafts.map(({ commit, prompt }) => (
                    <label key={commit.fullHash}>
                      {commit.subject}
                      <small>
                        {commit.shortHash} | {commit.date}
                      </small>
                      <textarea
                        className="support-area"
                        onChange={(event) =>
                          updatePromptDraft(commit.fullHash, event.target.value)
                        }
                        placeholder="Optional note for what the user was asking in this older commit."
                        rows={4}
                        value={prompt}
                      />
                    </label>
                  ))}
                  <small>
                    Older selected prompt notes are optional context. The newest missed
                    commit always uses the main prompt field above.
                  </small>
                </div>
              ) : sync.missedCommits.length > 1 ? (
                <div className="missing-prompts">
                  <div className="section-heading compact">
                    <p className="eyebrow">Older Selected Commits</p>
                    <h3>None selected</h3>
                  </div>
                  <small>
                    Select an older missed commit from the left if you want to attach an
                    extra prompt note to it.
                  </small>
                </div>
              ) : null}

              <button
                className="primary-button"
                disabled={working || !deferredPrompt.trim()}
                type="submit"
              >
                {isAnalyzing ? "Analyzing..." : "Analyze intent"}
              </button>
            </form>
          </section>
        </section>
      ) : (
        <section className="results-layout">
          <aside className="panel results-sidebar">
            <div className="section-heading">
              <p className="eyebrow">Result Summary</p>
              <h3>Review intent and generate the final prompt.</h3>
            </div>
            <div className="results-metrics">
              <div className="results-metric">
                <span>Selected commits</span>
                <strong>{selectedCommitCount}</strong>
              </div>
              <div className="results-metric">
                <span>Blind spots</span>
                <strong>{analysis?.blindSpots.length ?? 0}</strong>
              </div>
              <div className="results-metric">
                <span>Evidence items</span>
                <strong>{parsedEvidence.length}</strong>
              </div>
            </div>
            <button
              className="secondary-button"
              onClick={() => setWorkspaceStage("prepare")}
              type="button"
            >
              Back to setup
            </button>
          </aside>

          <section className="panel results-main">
            {analysis ? (
              <div className="analysis-stack">
                {isGenerating ? (
                  <div className="analysis-progress" aria-live="polite">
                    <span className="loading-dot small" aria-hidden="true" />
                    <span>Generating the final prompt from the confirmed intent...</span>
                  </div>
                ) : null}

                <div className="analysis-block">
                  <p className="eyebrow">Detected Intent</p>
                  <label>
                    Confirm or refine the user intent
                    <textarea
                      onChange={(event) => setClarifiedIntent(event.target.value)}
                      rows={4}
                      value={clarifiedIntent}
                    />
                  </label>
                </div>

                <div className="analysis-block">
                  <p className="eyebrow">Agent Read</p>
                  <p>{analysis.agentIntent}</p>
                </div>

                {!!analysis.blindSpots.length ? (
                  <div className="analysis-block">
                    <p className="eyebrow">Blind Spots</p>
                    <div className="blind-spot-list">
                      {analysis.blindSpots.map((blindSpot) => (
                        <div
                          className={`blind-spot ${blindSpot.severity}`}
                          key={`${blindSpot.title}-${blindSpot.reason}`}
                        >
                          <strong>{blindSpot.title}</strong>
                          <span>{blindSpot.reason}</span>
                          <small>{blindSpot.severity.toUpperCase()}</small>
                        </div>
                      ))}
                    </div>
                  </div>
                ) : null}

                {!!analysis.missingInfo.length ? (
                  <div className="analysis-block">
                    <p className="eyebrow">Missing Points</p>
                    <ul className="plain-list">
                      {analysis.missingInfo.map((item) => (
                        <li key={item}>{item}</li>
                      ))}
                    </ul>
                  </div>
                ) : null}

                {!!analysis.retrievedEvidence.length ? (
                  <div className="analysis-block">
                    <p className="eyebrow">Retrieved Evidence</p>
                    <div className="evidence-list">
                      {parsedEvidence.map((item, index) => (
                        <details className="evidence-card" key={`${index}-${item.title}`}>
                          <summary className="evidence-summary">
                            <div className="evidence-summary-main">
                              <span className="evidence-kind">{item.kind}</span>
                              <strong>{item.title}</strong>
                              {item.summary ? <small>{item.summary}</small> : null}
                            </div>
                            <span className="evidence-toggle">Details</span>
                          </summary>
                          <pre className="evidence-box">{item.content}</pre>
                        </details>
                      ))}
                    </div>
                  </div>
                ) : null}

                {clarificationAnswers.map((answer, index) => (
                  <div className="analysis-block" key={answer.question}>
                    <p className="eyebrow">Clarification {index + 1}</p>
                    <div className="clarification-card">
                      <strong className="clarification-question">
                        {answer.question}
                      </strong>
                      <div className="clarification-options">
                        {analysis.followupQuestions[index]?.options.map((option) => (
                          <button
                            key={option}
                            className={
                              option === answer.selected_option
                                ? "clarification-option active"
                                : "clarification-option"
                            }
                            onClick={() =>
                              setClarificationAnswers((current) =>
                                current.map((item, itemIndex) =>
                                  itemIndex === index
                                    ? { ...item, selected_option: option }
                                    : item,
                                ),
                              )
                            }
                            type="button"
                          >
                            {option}
                          </button>
                        ))}
                      </div>
                    </div>
                    <label>
                      Optional note
                      <input
                        onChange={(event) =>
                          setClarificationAnswers((current) =>
                            current.map((item, itemIndex) =>
                              itemIndex === index
                                ? { ...item, custom_text: event.target.value }
                                : item,
                            ),
                          )
                        }
                        value={answer.custom_text}
                      />
                    </label>
                  </div>
                ))}

                <button
                  className="primary-button"
                  disabled={
                    working ||
                    (!analysis.canGenerateFinalPrompt && !clarificationsComplete)
                  }
                  onClick={handleFinalize}
                  type="button"
                >
                  {isGenerating ? "Generating..." : "Generate final prompt"}
                </button>
              </div>
            ) : null}

            {finalPrompt ? (
              <div className="analysis-block final-block">
                <p className="eyebrow">Final Prompt</p>
                <pre className="final-prompt">{finalPrompt}</pre>
              </div>
            ) : null}
          </section>
        </section>
      )}
    </main>
  );
}
