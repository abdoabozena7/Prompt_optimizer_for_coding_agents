import type { AnalysisPayload, Commit, Project, SyncSnapshot } from "./types";

type JsonValue = Record<string, unknown>;

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
    ...init,
  });

  const body = (await response.json()) as JsonValue;
  if (!response.ok) {
    throw new Error(String(body.detail ?? "Request failed"));
  }

  return body as T;
}

function normalizeCommit(raw: Record<string, unknown>): Commit {
  return {
    fullHash: String(raw.fullHash ?? raw.full_hash ?? ""),
    shortHash: String(raw.shortHash ?? raw.short_hash ?? ""),
    author: String(raw.author ?? ""),
    date: String(raw.date ?? ""),
    subject: String(raw.subject ?? ""),
    summary: String(raw.summary ?? ""),
  };
}

function computeMissedCommitCount(
  commits: Commit[],
  project: Project,
  apiCount: number,
): number {
  if (apiCount > 0) {
    return apiCount;
  }

  if (!project.lastProcessedCommit) {
    return commits.length;
  }

  const index = commits.findIndex(
    (commit) => commit.fullHash === project.lastProcessedCommit,
  );
  return index >= 0 ? index : commits.length;
}

function normalizeSync(project: Project, raw: Record<string, unknown>): SyncSnapshot {
  const commits = Array.isArray(raw.commits)
    ? raw.commits.map((item: unknown) =>
        normalizeCommit(item as Record<string, unknown>),
      )
    : [];
  const rawMissedCommits = raw.missedCommits ?? raw.missed_commits;
  const apiMissedCommits = Array.isArray(rawMissedCommits)
    ? rawMissedCommits.map((item: unknown) =>
        normalizeCommit(item as Record<string, unknown>),
      )
    : [];
  const rawMissedCount = Number(raw.missedCommitCount ?? raw.missed_commit_count ?? 0);
  const missedCommitCount = computeMissedCommitCount(commits, project, rawMissedCount);
  const missedCommits =
    apiMissedCommits.length > 0 || missedCommitCount === 0
      ? apiMissedCommits
      : commits.slice(0, missedCommitCount);
  const rawDefaultSelection =
    raw.defaultSelectedCommitHashes ?? raw.default_selected_commit_hashes;
  const defaultSelectedFromApi = Array.isArray(rawDefaultSelection)
    ? rawDefaultSelection.map((item: unknown) => String(item))
    : [];
  const defaultSelectedCommitHashes =
    defaultSelectedFromApi.length > 0
      ? defaultSelectedFromApi
      : missedCommits.length > 0
        ? missedCommits.map((commit: Commit) => commit.fullHash)
        : commits[0]
          ? [commits[0].fullHash]
          : [];

  return {
    commits,
    missedCommits,
    missedCommitCount,
    promptRequestCount:
      Number(raw.promptRequestCount ?? raw.prompt_request_count ?? missedCommitCount) ||
      missedCommitCount,
    defaultSelectedCommitHashes,
    shouldCompactMissedPrompts: Boolean(
      raw.shouldCompactMissedPrompts ?? raw.should_compact_missed_prompts ?? false,
    ),
    compactionThreshold: Number(
      raw.compactionThreshold ?? raw.compaction_threshold ?? 4,
    ),
  };
}

export function fetchProjects() {
  return request<{ projects: Project[] }>("/api/projects");
}

export function fetchModels() {
  return request<{ models: string[]; defaultModel: string }>("/api/models");
}

export function pickProjectDirectory() {
  return request<{ path: string }>("/api/system/pick-project-directory", {
    method: "POST",
  });
}

export function saveProject(payload: {
  local_path: string;
  remote_url: string;
  preferred_model: string;
}) {
  return request<{ project: Project }>("/api/projects", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function fetchProjectDetail(projectId: string) {
  return request<{ project: Project; sync: Record<string, unknown> }>(
    `/api/projects/${projectId}`,
  ).then((response) => ({
    project: response.project,
    sync: normalizeSync(response.project, response.sync),
  }));
}

export function refreshProject(projectId: string) {
  return request<{ project: Project; sync: Record<string, unknown> }>(
    `/api/projects/${projectId}/refresh`,
    {
      method: "POST",
    },
  ).then((response) => ({
    project: response.project,
    sync: normalizeSync(response.project, response.sync),
  }));
}

export function fetchDefaultSelection(projectId: string) {
  return request<{ selectedCommitHashes: string[] }>(
    `/api/projects/${projectId}/selection/default`,
  );
}

export function fetchDiff(projectId: string, commitHash: string) {
  return request<{ commitHash: string; diff: string }>(
    `/api/projects/${projectId}/diff/${commitHash}`,
  );
}

export function fetchDiffSummary(projectId: string, commitHash: string) {
  return request<{ commitHash: string; summary: string }>(
    `/api/projects/${projectId}/diff-summary/${commitHash}`,
  );
}

export function analyzeProject(projectId: string, payload: JsonValue) {
  return request<{
    analysis: AnalysisPayload;
    sync: SyncSnapshot;
    selectedModel: string;
    usedFallbackModel: boolean;
  }>(`/api/projects/${projectId}/analyze`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function finalizeProject(projectId: string, payload: JsonValue) {
  return request<{
    finalPrompt: string;
    project: Project;
    sync: SyncSnapshot;
    selectedModel: string;
    usedFallbackModel: boolean;
  }>(`/api/projects/${projectId}/finalize`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
