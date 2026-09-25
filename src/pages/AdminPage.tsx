import { useState } from 'react';
import { mockFiles, mockJobs, mockHealth } from '../store';
import {
  Activity, Database, Cpu, HardDrive, RefreshCw, Clock, Server,
  BarChart3, Settings, Shield, Zap, Eye
} from 'lucide-react';

export default function AdminPage() {
  const [activeTab, setActiveTab] = useState<'overview' | 'jobs' | 'logs' | 'settings'>('overview');

  const healthItems = [
    { label: 'База данных', status: mockHealth.db, icon: Database },
    { label: 'ChromaDB', status: mockHealth.chroma, icon: HardDrive },
    { label: 'Ollama (LLM)', status: mockHealth.ollama, icon: Cpu },
    { label: 'Система', status: mockHealth.status, icon: Server },
  ];

  const metrics = {
    totalFiles: mockFiles.length,
    totalChunks: 156,
    avgConfidence: 0.89,
    hallucinationRate: 0.02,
    avgResponseTime: '2.3с',
    precision: 0.94,
    recall: 0.91,
    f1Score: 0.925,
  };

  const logs = [
    { time: '10:32:15', level: 'info', message: 'Файл «КС-2_Договор_123.pdf» обработан (ingest done)' },
    { time: '10:31:42', level: 'info', message: 'Классификация завершена: doc_type=ks2, confidence=0.94' },
    { time: '10:31:30', level: 'info', message: 'OCR завершён: mean_confidence=0.94' },
    { time: '10:30:55', level: 'info', message: 'Начата обработка файла «КС-2_Договор_123.pdf»' },
    { time: '10:28:00', level: 'warn', message: 'OCR confidence 0.72 для «Скан_ИД_объект.jpg» — ниже порога 0.80' },
    { time: '10:25:00', level: 'info', message: 'Индексация ChromaDB: 156 чанков, модель multilingual-e5-small' },
    { time: '10:20:00', level: 'info', message: 'Запуск системы. Ollama подключена: qwen2.5:1.5b-instruct-q4_K_M' },
    { time: '10:19:55', level: 'info', message: 'SQLite инициализирован: 8 записей в files' },
    { time: '10:19:50', level: 'info', message: 'Миграции БД применены успешно' },
    { time: '10:19:45', level: 'info', message: 'Конфигурация загружена: config/config.yaml' },
  ];

  return (
    <div className="h-full flex flex-col overflow-hidden">
      {/* Tabs */}
      <div className="px-4 lg:px-6 pt-4 pb-0 border-b border-slate-200 bg-white">
        <div className="flex gap-1">
          {[
            { id: 'overview' as const, label: 'Обзор', icon: Activity },
            { id: 'jobs' as const, label: 'Задачи', icon: Clock },
            { id: 'logs' as const, label: 'Логи', icon: BarChart3 },
            { id: 'settings' as const, label: 'Настройки', icon: Settings },
          ].map(tab => {
            const Icon = tab.icon;
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium rounded-t-lg border-b-2 transition-colors ${
                  activeTab === tab.id
                    ? 'border-primary-500 text-primary-700 bg-primary-50/50'
                    : 'border-transparent text-slate-500 hover:text-slate-700'
                }`}
              >
                <Icon className="w-4 h-4" />
                {tab.label}
              </button>
            );
          })}
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-4 lg:p-6">
        {activeTab === 'overview' && (
          <div className="space-y-6 animate-fade-in">
            {/* Health status */}
            <div>
              <h3 className="text-sm font-semibold text-slate-700 mb-3 flex items-center gap-2">
                <Activity className="w-4 h-4" />
                Состояние системы
              </h3>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
                {healthItems.map(item => {
                  const Icon = item.icon;
                  return (
                    <div key={item.label} className="card p-4">
                      <div className="flex items-center justify-between mb-2">
                        <Icon className="w-5 h-5 text-slate-400" />
                        <span className={`badge ${
                          item.status === 'ok' ? 'badge-success' : 'badge-danger'
                        }`}>
                          {item.status === 'ok' ? 'OK' : 'Ошибка'}
                        </span>
                      </div>
                      <p className="text-sm font-medium text-slate-800">{item.label}</p>
                      <div className="mt-2 flex items-center gap-1.5">
                        <div className={`w-2 h-2 rounded-full ${item.status === 'ok' ? 'bg-green-500' : 'bg-red-500'}`} />
                        <span className="text-xs text-slate-500">
                          {item.status === 'ok' ? 'Работает' : 'Недоступно'}
                        </span>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Metrics */}
            <div>
              <h3 className="text-sm font-semibold text-slate-700 mb-3 flex items-center gap-2">
                <BarChart3 className="w-4 h-4" />
                Метрики качества
              </h3>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                <div className="card p-4 text-center">
                  <p className="text-2xl font-bold text-primary-600">{(metrics.precision * 100).toFixed(0)}%</p>
                  <p className="text-xs text-slate-500 mt-1">Precision</p>
                </div>
                <div className="card p-4 text-center">
                  <p className="text-2xl font-bold text-accent-600">{(metrics.recall * 100).toFixed(0)}%</p>
                  <p className="text-xs text-slate-500 mt-1">Recall</p>
                </div>
                <div className="card p-4 text-center">
                  <p className="text-2xl font-bold text-green-600">{(metrics.f1Score * 100).toFixed(1)}%</p>
                  <p className="text-xs text-slate-500 mt-1">F1-Score</p>
                </div>
                <div className="card p-4 text-center">
                  <p className="text-2xl font-bold text-red-600">{(metrics.hallucinationRate * 100).toFixed(1)}%</p>
                  <p className="text-xs text-slate-500 mt-1">Галлюцинации</p>
                </div>
              </div>
            </div>

            {/* System info */}
            <div>
              <h3 className="text-sm font-semibold text-slate-700 mb-3 flex items-center gap-2">
                <Server className="w-4 h-4" />
                Информация о системе
              </h3>
              <div className="card overflow-hidden">
                <table className="w-full text-sm">
                  <tbody className="divide-y divide-slate-100">
                    {[
                      ['Версия', '2.0'],
                      ['Модель LLM', 'qwen2.5:1.5b-instruct-q4_K_M'],
                      ['Модель эмбеддингов', 'multilingual-e5-small (384d)'],
                      ['Реранкер', 'ms-marco-MiniLM-L-6-v2'],
                      ['Векторное хранилище', 'ChromaDB'],
                      ['База данных', 'SQLite'],
                      ['Документов в базе', mockFiles.length.toString()],
                      ['Чанков проиндексировано', metrics.totalChunks.toString()],
                      ['Среднее время ответа', metrics.avgResponseTime],
                      ['Средняя OCR-точность', `${(metrics.avgConfidence * 100).toFixed(0)}%`],
                    ].map(([label, value]) => (
                      <tr key={label} className="hover:bg-slate-50">
                        <td className="px-4 py-2.5 text-slate-500 font-medium">{label}</td>
                        <td className="px-4 py-2.5 text-slate-800">{value}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Actions */}
            <div>
              <h3 className="text-sm font-semibold text-slate-700 mb-3">Действия</h3>
              <div className="flex flex-wrap gap-2">
                <button className="btn-primary flex items-center gap-2">
                  <RefreshCw className="w-4 h-4" />
                  Переиндексация
                </button>
                <button className="btn-secondary flex items-center gap-2">
                  <Zap className="w-4 h-4" />
                  Очистить кэш
                </button>
                <button className="btn-secondary flex items-center gap-2">
                  <Database className="w-4 h-4" />
                  Бэкап БД
                </button>
              </div>
            </div>
          </div>
        )}

        {activeTab === 'jobs' && (
          <div className="animate-fade-in">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-sm font-semibold text-slate-700">Очередь задач</h3>
              <button className="btn-secondary text-sm flex items-center gap-2">
                <RefreshCw className="w-4 h-4" />
                Обновить
              </button>
            </div>
            <div className="card overflow-hidden">
              <table className="w-full text-sm">
                <thead className="bg-slate-50 border-b border-slate-200">
                  <tr>
                    <th className="px-4 py-3 text-left text-xs font-semibold text-slate-600">ID</th>
                    <th className="px-4 py-3 text-left text-xs font-semibold text-slate-600">Тип</th>
                    <th className="px-4 py-3 text-left text-xs font-semibold text-slate-600">Приоритет</th>
                    <th className="px-4 py-3 text-left text-xs font-semibold text-slate-600">Статус</th>
                    <th className="px-4 py-3 text-left text-xs font-semibold text-slate-600">Попытки</th>
                    <th className="px-4 py-3 text-left text-xs font-semibold text-slate-600">Создана</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {mockJobs.map(job => (
                    <tr key={job.id} className="hover:bg-slate-50">
                      <td className="px-4 py-3 font-mono text-xs text-slate-600">#{job.id}</td>
                      <td className="px-4 py-3">
                        <span className="badge badge-info">{job.kind}</span>
                      </td>
                      <td className="px-4 py-3 text-slate-600">{job.priority}</td>
                      <td className="px-4 py-3">
                        <span className={`badge ${
                          job.status === 'done' ? 'badge-success' :
                          job.status === 'processing' ? 'badge-warning' :
                          job.status === 'failed' ? 'badge-danger' : 'badge-info'
                        }`}>
                          {job.status}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-slate-600">{job.attempts}</td>
                      <td className="px-4 py-3 text-slate-500 text-xs">
                        {new Date(job.created_at).toLocaleString('ru-RU')}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {activeTab === 'logs' && (
          <div className="animate-fade-in">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-sm font-semibold text-slate-700">Системные логи</h3>
              <span className="text-xs text-slate-500">Последние {logs.length} записей</span>
            </div>
            <div className="card overflow-hidden">
              <div className="divide-y divide-slate-100 font-mono text-xs">
                {logs.map((log, i) => (
                  <div key={i} className="px-4 py-2.5 flex items-start gap-3 hover:bg-slate-50">
                    <span className="text-slate-400 flex-shrink-0">{log.time}</span>
                    <span className={`flex-shrink-0 px-1.5 py-0.5 rounded text-[10px] font-bold uppercase ${
                      log.level === 'info' ? 'bg-blue-100 text-blue-700' :
                      log.level === 'warn' ? 'bg-amber-100 text-amber-700' :
                      'bg-red-100 text-red-700'
                    }`}>
                      {log.level}
                    </span>
                    <span className="text-slate-700">{log.message}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {activeTab === 'settings' && (
          <div className="animate-fade-in space-y-6">
            <div>
              <h3 className="text-sm font-semibold text-slate-700 mb-3 flex items-center gap-2">
                <Cpu className="w-4 h-4" />
                LLM конфигурация
              </h3>
              <div className="card p-4 space-y-3">
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <div>
                    <label className="text-xs font-medium text-slate-600 block mb-1">Основная модель</label>
                    <input className="input-field text-xs" defaultValue="qwen2.5:1.5b-instruct-q4_K_M" readOnly />
                  </div>
                  <div>
                    <label className="text-xs font-medium text-slate-600 block mb-1">Лёгкая модель</label>
                    <input className="input-field text-xs" defaultValue="gemma2:2b-instruct-q4_K_M" readOnly />
                  </div>
                  <div>
                    <label className="text-xs font-medium text-slate-600 block mb-1">Ollama URL</label>
                    <input className="input-field text-xs" defaultValue="http://localhost:11434" readOnly />
                  </div>
                  <div>
                    <label className="text-xs font-medium text-slate-600 block mb-1">Таймаут (сек)</label>
                    <input className="input-field text-xs" defaultValue="60" readOnly />
                  </div>
                </div>
              </div>
            </div>

            <div>
              <h3 className="text-sm font-semibold text-slate-700 mb-3 flex items-center gap-2">
                <Eye className="w-4 h-4" />
                OCR конфигурация
              </h3>
              <div className="card p-4 space-y-3">
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <div>
                    <label className="text-xs font-medium text-slate-600 block mb-1">Языки</label>
                    <input className="input-field text-xs" defaultValue="rus, eng" readOnly />
                  </div>
                  <div>
                    <label className="text-xs font-medium text-slate-600 block mb-1">Мин. точность</label>
                    <input className="input-field text-xs" defaultValue="0.80" readOnly />
                  </div>
                  <div>
                    <label className="text-xs font-medium text-slate-600 block mb-1">Порог отклонения</label>
                    <input className="input-field text-xs" defaultValue="0.50" readOnly />
                  </div>
                </div>
              </div>
            </div>

            <div>
              <h3 className="text-sm font-semibold text-slate-700 mb-3 flex items-center gap-2">
                <Shield className="w-4 h-4" />
                Валидация и безопасность
              </h3>
              <div className="card p-4 space-y-3">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm font-medium text-slate-700">Groundrails (защита от галлюцинаций)</p>
                    <p className="text-xs text-slate-500">Проверка каждого ответа на соответствие источникам</p>
                  </div>
                  <div className="w-10 h-5 rounded-full bg-green-500 relative cursor-pointer">
                    <div className="absolute right-0.5 top-0.5 w-4 h-4 rounded-full bg-white shadow" />
                  </div>
                </div>
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm font-medium text-slate-700">A2A протокол</p>
                    <p className="text-xs text-slate-500">Взаимодействие с другими агентами</p>
                  </div>
                  <div className="w-10 h-5 rounded-full bg-green-500 relative cursor-pointer">
                    <div className="absolute right-0.5 top-0.5 w-4 h-4 rounded-full bg-white shadow" />
                  </div>
                </div>
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm font-medium text-slate-700">Watchdog (мониторинг папок)</p>
                    <p className="text-xs text-slate-500">Автоматическая обработка новых файлов</p>
                  </div>
                  <div className="w-10 h-5 rounded-full bg-slate-300 relative cursor-pointer">
                    <div className="absolute left-0.5 top-0.5 w-4 h-4 rounded-full bg-white shadow" />
                  </div>
                </div>
              </div>
            </div>

            <div className="p-3 rounded-lg bg-amber-50 border border-amber-200">
              <p className="text-xs text-amber-800">
                <strong>Примечание:</strong> Настройки доступны только для чтения в демо-режиме. 
                Для изменения редактируйте файл <code className="bg-amber-100 px-1 rounded">config/config.yaml</code>
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
