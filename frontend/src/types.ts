export type Project = {
  id: string;
  name: string;
  localPath: string;
  remoteUrl: string;
  preferredModel: string;
  createdAt: string;
  updatedAt: string;
  lastSeenRemoteCommit: string;
  lastProcessedCommit: string;
  promptHistoryCount: number;
};

export type Commit = {
  fullHash: string;
  shortHash: string;
  author: string;
  date: string;
  subject: string;
  summary: string;
};

export type SyncSnapshot = {
  commits: Commit[];
  missedCommits: Commit[];
  missedCommitCount: number;
  promptRequestCount: number;
  defaultSelectedCommitHashes: string[];
  shouldCompactMissedPrompts: boolean;
  compactionThreshold: number;
};

export type ClarificationQuestion = {
  question: string;
  options: string[];
};

export type BlindSpot = {
  title: string;
  reason: string;
  severity: string;
};

export type AnalysisPayload = {
  agentIntent: string;
  userIntent: string;
  missingInfo: string[];
  blindSpots: BlindSpot[];
  followupQuestions: ClarificationQuestion[];
  canGenerateFinalPrompt: boolean;
  retrievedEvidence: string[];
};
