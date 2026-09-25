import { useState } from 'react';
import { mockFiles, docTypeLabels, docTypeColors, statusLabels, formatBytes, formatDate } from '../store';
import {
  Upload, FileText, Image, FileSpreadsheet, Mail, Archive,
  RefreshCw, Eye, Download, Search, Grid3X3, List
} from 'lucide-react';

const formatIcons: Record<string, typeof FileText> = {
  pdf: FileText,
  docx: FileSpreadsheet,
  xlsx: FileSpreadsheet,
  jpg: Image,
  png: Image,
  eml: Mail,
  zip: Archive,
};

const formatColors: Record<string, string> = {
  pdf: 'bg-red-100 text-red-600',
  docx: 'bg-blue-100 text-blue-600',
  xlsx: 'bg-green-100 text-green-600',
  jpg: 'bg-purple-100 text-purple-600',
  png: 'bg-purple-100 text-purple-600',
  eml: 'bg-amber-100 text-amber-600',
  zip: 'bg-slate-100 text-slate-600',
};

export default function FilesPage() {
  const [viewMode, setViewMode] = useState<'grid' | 'list'>('grid');
  const [search, setSearch] = useState('');
  const [dragOver, setDragOver] = useState(false);

  const filteredFiles = mockFiles.filter(f =>
    f.original_name.toLowerCase().includes(search.toLowerCase())
  );

  const stats = {
    total: mockFiles.length,
    totalSize: mockFiles.reduce((s, f) => s + f.size_bytes, 0),
    byType: mockFiles.reduce((acc, f) => {
      acc[f.doc_type] = (acc[f.doc_type] || 0) + 1;
      return acc;
    }, {} as Record<string, number>),
  };

  return (
    <div className="h-full flex flex-col">
      {/* Upload area */}
      <div
        className={`mx-4 lg:mx-6 mt-4 p-6 rounded-xl border-2 border-dashed transition-all duration-200 ${
          dragOver
            ? 'border-primary-400 bg-primary-50'
            : 'border-slate-200 bg-slate-50 hover:border-slate-300'
        }`}
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => { e.preventDefault(); setDragOver(false); }}
      >
        <div className="flex flex-col items-center text-center">
          <div className="w-12 h-12 rounded-xl bg-primary-100 flex items-center justify-center mb-3">
            <Upload className="w-6 h-6 text-primary-600" />
          </div>
          <p className="text-sm font-medium text-slate-700">Перетащите файлы для загрузки</p>
          <p className="text-xs text-slate-500 mt-1">PDF, DOCX, XLSX, PPTX, JPG, PNG, EML, ZIP • до 500 МБ</p>
          <button className="btn-primary mt-3 text-sm">
            Выбрать файлы
          </button>
        </div>
      </div>

      {/* Stats */}
      <div className="px-4 lg:px-6 py-4 grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div className="card p-3">
          <p className="text-xs text-slate-500">Всего файлов</p>
          <p className="text-xl font-bold text-slate-900">{stats.total}</p>
        </div>
        <div className="card p-3">
          <p className="text-xs text-slate-500">Объём</p>
          <p className="text-xl font-bold text-slate-900">{formatBytes(stats.totalSize)}</p>
        </div>
        <div className="card p-3">
          <p className="text-xs text-slate-500">Распознано</p>
          <p className="text-xl font-bold text-green-600">{mockFiles.filter(f => f.status === 'done').length}</p>
        </div>
        <div className="card p-3">
          <p className="text-xs text-slate-500">Типов документов</p>
          <p className="text-xl font-bold text-slate-900">{Object.keys(stats.byType).length}</p>
        </div>
      </div>

      {/* Toolbar */}
      <div className="px-4 lg:px-6 pb-3 flex items-center gap-3">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Поиск файлов..."
            className="input-field pl-10"
          />
        </div>
        <div className="flex items-center bg-slate-100 rounded-lg p-0.5">
          <button
            onClick={() => setViewMode('grid')}
            className={`p-1.5 rounded-md transition-colors ${viewMode === 'grid' ? 'bg-white shadow-sm' : 'hover:bg-slate-200'}`}
          >
            <Grid3X3 className="w-4 h-4 text-slate-600" />
          </button>
          <button
            onClick={() => setViewMode('list')}
            className={`p-1.5 rounded-md transition-colors ${viewMode === 'list' ? 'bg-white shadow-sm' : 'hover:bg-slate-200'}`}
          >
            <List className="w-4 h-4 text-slate-600" />
          </button>
        </div>
      </div>

      {/* Files grid/list */}
      <div className="flex-1 overflow-y-auto px-4 lg:px-6 pb-4">
        {viewMode === 'grid' ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
            {filteredFiles.map(file => {
              const Icon = formatIcons[file.format] || FileText;
              const colorClass = formatColors[file.format] || 'bg-slate-100 text-slate-600';
              return (
                <div key={file.id} className="card p-4 hover:shadow-md transition-shadow group">
                  <div className="flex items-start justify-between mb-3">
                    <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${colorClass}`}>
                      <Icon className="w-5 h-5" />
                    </div>
                    <span className={`badge ${docTypeColors[file.doc_type]}`}>
                      {docTypeLabels[file.doc_type]}
                    </span>
                  </div>
                  <h4 className="text-sm font-medium text-slate-800 truncate mb-1" title={file.original_name}>
                    {file.original_name}
                  </h4>
                  <div className="flex items-center gap-2 text-xs text-slate-500 mb-3">
                    <span>{formatBytes(file.size_bytes)}</span>
                    <span>•</span>
                    <span>{formatDate(file.created_at)}</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className={`badge ${
                      file.status === 'done' ? 'badge-success' :
                      file.status === 'processing' ? 'badge-warning' : 'badge-danger'
                    }`}>
                      {statusLabels[file.status]}
                    </span>
                    <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                      <button className="p-1.5 rounded hover:bg-slate-100" title="Просмотр">
                        <Eye className="w-3.5 h-3.5 text-slate-500" />
                      </button>
                      <button className="p-1.5 rounded hover:bg-slate-100" title="Скачать">
                        <Download className="w-3.5 h-3.5 text-slate-500" />
                      </button>
                      <button className="p-1.5 rounded hover:bg-slate-100" title="Переиндексировать">
                        <RefreshCw className="w-3.5 h-3.5 text-slate-500" />
                      </button>
                    </div>
                  </div>
                  {file.ocr_confidence && file.ocr_confidence < 0.8 && (
                    <div className="mt-2 px-2 py-1 rounded bg-amber-50 border border-amber-100">
                      <p className="text-[10px] text-amber-700">
                        ⚠ OCR: {(file.ocr_confidence * 100).toFixed(0)}% — требуется проверка
                      </p>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        ) : (
          <div className="space-y-2">
            {filteredFiles.map(file => {
              const Icon = formatIcons[file.format] || FileText;
              const colorClass = formatColors[file.format] || 'bg-slate-100 text-slate-600';
              return (
                <div key={file.id} className="card p-3 flex items-center gap-4 hover:shadow-sm transition-shadow">
                  <div className={`w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0 ${colorClass}`}>
                    <Icon className="w-4.5 h-4.5" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-slate-800 truncate">{file.original_name}</p>
                    <div className="flex items-center gap-2 mt-0.5">
                      <span className={`badge ${docTypeColors[file.doc_type]}`}>
                        {docTypeLabels[file.doc_type]}
                      </span>
                      <span className="text-xs text-slate-500">{formatBytes(file.size_bytes)}</span>
                      <span className="text-xs text-slate-400">{formatDate(file.created_at)}</span>
                    </div>
                  </div>
                  <span className={`badge ${
                    file.status === 'done' ? 'badge-success' :
                    file.status === 'processing' ? 'badge-warning' : 'badge-danger'
                  }`}>
                    {statusLabels[file.status]}
                  </span>
                  <div className="flex items-center gap-1">
                    <button className="p-1.5 rounded hover:bg-slate-100">
                      <Eye className="w-4 h-4 text-slate-500" />
                    </button>
                    <button className="p-1.5 rounded hover:bg-slate-100">
                      <Download className="w-4 h-4 text-slate-500" />
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
