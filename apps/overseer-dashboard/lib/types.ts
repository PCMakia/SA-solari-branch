export type QueueStatus =
  | "PENDING"
  | "RUNNING"
  | "NEEDS_REPAIR"
  | "COMPLETED"
  | "ABORTED";

export interface TaskSpec {
  id: string;
  command: string;
  args: string[];
  runtime?: string;
  url?: string;
}

export interface QueueRecord {
  id: string;
  status: QueueStatus;
  tasks: TaskSpec[];
  current_step_index: number;
  retry_counts: Record<string, number>;
  history: Array<{
    task_id: string;
    status: string;
    returncode: number | null;
    stdout: string;
    stderr: string;
    timestamp: string;
  }>;
  workspace: string;
  last_error: Record<string, unknown> | null;
  max_retries: number;
  parent_queue_id?: string | null;
  stream_mode?: string;
  label?: string;
}

export interface OverseerSnapshot {
  state_path: string;
  backend: string;
  aggregate_status: QueueStatus | "IDLE";
  active_queue_id: string | null;
  queues: QueueRecord[];
  completed_steps: number;
  total_steps: number;
  timestamp: string;
}
