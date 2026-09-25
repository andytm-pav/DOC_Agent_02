import type { DocFile, ChatMessage, Job, HealthStatus, User } from './types';

export const mockFiles: DocFile[] = [
  {
    id: 1, sha256: 'a1b2c3d4', original_name: 'КС-2_Договор_123_Январь.pdf',
    format: 'pdf', size_bytes: 2456789, city: 'Москва', customer: 'ООО "СтройИнвест"',
    contract_no: '123', contract_date: '2024-01-15', doc_type: 'ks2',
    doc_number: 'КС-2/001', doc_date: '2024-01-31', amount: 1250000,
    status: 'done', ocr_confidence: 0.94, description: 'Акт о приёмке выполненных работ',
    source: 'user', created_at: '2024-01-31T10:00:00Z', updated_at: '2024-01-31T10:01:30Z'
  },
  {
    id: 2, sha256: 'e5f6g7h8', original_name: 'КС-3_Договор_123_Январь.pdf',
    format: 'pdf', size_bytes: 1890432, city: 'Москва', customer: 'ООО "СтройИнвест"',
    contract_no: '123', contract_date: '2024-01-15', doc_type: 'ks3',
    doc_number: 'КС-3/001', doc_date: '2024-01-31', amount: 1250000,
    status: 'done', ocr_confidence: 0.91, description: 'Справка о стоимости выполненных работ',
    source: 'user', created_at: '2024-01-31T10:05:00Z', updated_at: '2024-01-31T10:06:20Z'
  },
  {
    id: 3, sha256: 'i9j0k1l2', original_name: 'Договор_123_СтройИнвест.docx',
    format: 'docx', size_bytes: 567890, city: 'Москва', customer: 'ООО "СтройИнвест"',
    contract_no: '123', contract_date: '2024-01-15', doc_type: 'contract',
    doc_number: 'Д-123', doc_date: '2024-01-15', amount: null,
    status: 'done', ocr_confidence: null, description: 'Договор подряда №123',
    source: 'user', created_at: '2024-01-15T09:00:00Z', updated_at: '2024-01-15T09:01:00Z'
  },
  {
    id: 4, sha256: 'm3n4o5p6', original_name: 'ДС_№1_к_договору_123.pdf',
    format: 'pdf', size_bytes: 345678, city: 'Москва', customer: 'ООО "СтройИнвест"',
    contract_no: '123', contract_date: '2024-01-15', doc_type: 'ds',
    doc_number: 'ДС-1', doc_date: '2024-02-10', amount: 350000,
    status: 'done', ocr_confidence: 0.88, description: 'Дополнительное соглашение №1',
    source: 'user', created_at: '2024-02-10T14:00:00Z', updated_at: '2024-02-10T14:01:15Z'
  },
  {
    id: 5, sha256: 'q7r8s9t0', original_name: 'ТТН_№456_бетон.xlsx',
    format: 'xlsx', size_bytes: 123456, city: 'Санкт-Петербург', customer: 'АО "БетонСтрой"',
    contract_no: '456', contract_date: '2024-03-01', doc_type: 'ttn',
    doc_number: 'ТТН-000456', doc_date: '2024-03-15', amount: 890000,
    status: 'done', ocr_confidence: null, description: 'Товарно-транспортная накладная',
    source: 'user', created_at: '2024-03-15T11:00:00Z', updated_at: '2024-03-15T11:00:45Z'
  },
  {
    id: 6, sha256: 'u1v2w3x4', original_name: 'Скан_ИД_объект.jpg',
    format: 'jpg', size_bytes: 4567890, city: 'Казань', customer: 'МУП "ГорСтрой"',
    contract_no: '789', contract_date: '2024-02-20', doc_type: 'id',
    doc_number: 'ИД-001', doc_date: '2024-03-01', amount: null,
    status: 'done', ocr_confidence: 0.72, description: 'Исполнительная документация (скан)',
    source: 'watcher', created_at: '2024-03-01T08:30:00Z', updated_at: '2024-03-01T08:32:00Z'
  },
  {
    id: 7, sha256: 'y5z6a7b8', original_name: 'КС-2_Договор_456_Март.pdf',
    format: 'pdf', size_bytes: 2100000, city: 'Санкт-Петербург', customer: 'АО "БетонСтрой"',
    contract_no: '456', contract_date: '2024-03-01', doc_type: 'ks2',
    doc_number: 'КС-2/002', doc_date: '2024-03-31', amount: 2340000,
    status: 'done', ocr_confidence: 0.96, description: 'Акт о приёмке выполненных работ',
    source: 'user', created_at: '2024-03-31T16:00:00Z', updated_at: '2024-03-31T16:01:20Z'
  },
  {
    id: 8, sha256: 'c9d0e1f2', original_name: 'Счёт-фактура_№78_СтройИнвест.pdf',
    format: 'pdf', size_bytes: 678901, city: 'Москва', customer: 'ООО "СтройИнвест"',
    contract_no: '123', contract_date: '2024-01-15', doc_type: 'invoice',
    doc_number: 'СФ-078', doc_date: '2024-02-28', amount: 1600000,
    status: 'done', ocr_confidence: 0.89, description: 'Счёт-фактура',
    source: 'user', created_at: '2024-02-28T12:00:00Z', updated_at: '2024-02-28T12:01:00Z'
  },
];

export const mockJobs: Job[] = [
  { id: 1, file_id: 6, kind: 'ingest', priority: 1, status: 'done', attempts: 1, last_error: null, created_at: '2024-03-01T08:30:00Z' },
  { id: 2, file_id: 7, kind: 'ingest', priority: 1, status: 'done', attempts: 1, last_error: null, created_at: '2024-03-31T16:00:00Z' },
  { id: 3, file_id: null, kind: 'reindex', priority: 3, status: 'done', attempts: 1, last_error: null, created_at: '2024-04-01T00:00:00Z' },
  { id: 4, file_id: null, kind: 'embed', priority: 5, status: 'queued', attempts: 0, last_error: null, created_at: '2024-04-01T10:00:00Z' },
];

export const mockHealth: HealthStatus = {
  status: 'ok',
  db: 'ok',
  chroma: 'ok',
  ollama: 'ok'
};

export const mockUser: User = {
  username: 'admin',
  role: 'admin'
};

export const initialMessages: ChatMessage[] = [
  {
    id: '1',
    role: 'system',
    content: 'Добро пожаловать в систему «Документовед». Я помогу вам с документами: загрузите файлы, задавайте вопросы, выгружайте картотеку.',
    timestamp: new Date().toISOString()
  },
  {
    id: '2',
    role: 'agent',
    content: 'В базе 8 документов по 3 договорам. Готов отвечать на вопросы.',
    timestamp: new Date().toISOString()
  }
];

export const docTypeLabels: Record<string, string> = {
  ks2: 'КС-2',
  ks3: 'КС-3',
  ks6: 'КС-6',
  ttn: 'ТТН',
  ds: 'ДС',
  id: 'ИД',
  invoice: 'Счёт-фактура',
  contract: 'Договор',
  other: 'Прочее'
};

export const docTypeColors: Record<string, string> = {
  ks2: 'bg-blue-100 text-blue-700',
  ks3: 'bg-indigo-100 text-indigo-700',
  ks6: 'bg-violet-100 text-violet-700',
  ttn: 'bg-emerald-100 text-emerald-700',
  ds: 'bg-amber-100 text-amber-700',
  id: 'bg-rose-100 text-rose-700',
  invoice: 'bg-cyan-100 text-cyan-700',
  contract: 'bg-slate-100 text-slate-700',
  other: 'bg-gray-100 text-gray-700'
};

export const statusLabels: Record<string, string> = {
  pending: 'Ожидает',
  processing: 'Обработка',
  done: 'Готов',
  failed: 'Ошибка',
  description_only: 'Только описание'
};

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return bytes + ' Б';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' КБ';
  return (bytes / (1024 * 1024)).toFixed(1) + ' МБ';
}

export function formatDate(dateStr: string): string {
  const d = new Date(dateStr);
  return d.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric' });
}

export function formatAmount(amount: number | null): string {
  if (amount === null) return '—';
  return new Intl.NumberFormat('ru-RU', { style: 'currency', currency: 'RUB', maximumFractionDigits: 0 }).format(amount);
}
