export type DocType = 'ks2' | 'ks3' | 'ks6' | 'ttn' | 'ds' | 'id' | 'invoice' | 'contract' | 'other';

export type FileStatus = 'pending' | 'processing' | 'done' | 'failed' | 'description_only';

export interface DocFile {
  id: number;
  sha256: string;
  original_name: string;
  format: string;
  size_bytes: number;
  city: string | null;
  customer: string | null;
  contract_no: string | null;
  contract_date: string | null;
  doc_type: DocType;
  doc_number: string | null;
  doc_date: string | null;
  amount: number | null;
  status: FileStatus;
  ocr_confidence: number | null;
  description: string | null;
  source: string;
  created_at: string;
  updated_at: string;
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'agent' | 'system';
  content: string;
  files?: DocFile[];
  confidence?: number;
  grounded?: boolean;
  timestamp: string;
  isTyping?: boolean;
}

export interface Job {
  id: number;
  file_id: number | null;
  kind: string;
  priority: number;
  status: 'queued' | 'processing' | 'done' | 'failed';
  attempts: number;
  last_error: string | null;
  created_at: string;
}

export interface HealthStatus {
  status: 'ok' | 'degraded' | 'error';
  db: string;
  chroma: string;
  ollama: string;
}

export interface User {
  username: string;
  role: 'user' | 'admin';
}

export type Page = 'chat' | 'card' | 'files' | 'admin';
