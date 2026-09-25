import { useState, useMemo } from 'react';
import { mockFiles, docTypeLabels, docTypeColors, statusLabels, formatBytes, formatDate, formatAmount } from '../store';
import { DocFile, DocType } from '../types';
import {
  Download, Search, Filter,
  FileSpreadsheet, ArrowUpDown, Eye, X
} from 'lucide-react';

export default function CardIndexPage() {
  const [search, setSearch] = useState('');
  const [filterType, setFilterType] = useState<string>('all');
  const [filterCity, setFilterCity] = useState<string>('all');
  const [sortField, setSortField] = useState<keyof DocFile>('doc_date');
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc');
  const [selectedFile, setSelectedFile] = useState<DocFile | null>(null);
  const [showFilters, setShowFilters] = useState(false);

  const cities = useMemo(() => {
    const set = new Set(mockFiles.map(f => f.city).filter(Boolean));
    return Array.from(set) as string[];
  }, []);

  const filteredFiles = useMemo(() => {
    let result = [...mockFiles];
    
    if (search) {
      const q = search.toLowerCase();
      result = result.filter(f =>
        f.original_name.toLowerCase().includes(q) ||
        f.customer?.toLowerCase().includes(q) ||
        f.contract_no?.toLowerCase().includes(q) ||
        f.doc_number?.toLowerCase().includes(q) ||
        f.description?.toLowerCase().includes(q)
      );
    }
    
    if (filterType !== 'all') {
      result = result.filter(f => f.doc_type === filterType);
    }
    
    if (filterCity !== 'all') {
      result = result.filter(f => f.city === filterCity);
    }

    result.sort((a, b) => {
      const aVal = a[sortField];
      const bVal = b[sortField];
      if (aVal === null && bVal === null) return 0;
      if (aVal === null) return 1;
      if (bVal === null) return -1;
      if (typeof aVal === 'string' && typeof bVal === 'string') {
        return sortDir === 'asc' ? aVal.localeCompare(bVal) : bVal.localeCompare(aVal);
      }
      if (typeof aVal === 'number' && typeof bVal === 'number') {
        return sortDir === 'asc' ? aVal - bVal : bVal - aVal;
      }
      return 0;
    });

    return result;
  }, [search, filterType, filterCity, sortField, sortDir]);

  const toggleSort = (field: keyof DocFile) => {
    if (sortField === field) {
      setSortDir(prev => prev === 'asc' ? 'desc' : 'asc');
    } else {
      setSortField(field);
      setSortDir('asc');
    }
  };

  const totalAmount = filteredFiles.reduce((s, f) => s + (f.amount || 0), 0);

  return (
    <div className="h-full flex flex-col">
      {/* Toolbar */}
      <div className="px-4 lg:px-6 py-4 border-b border-slate-200 bg-white">
        <div className="flex flex-col sm:flex-row gap-3">
          {/* Search */}
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Поиск по названию, контрагенту, номеру договора..."
              className="input-field pl-10"
            />
          </div>
          
          {/* Filter toggle */}
          <button
            onClick={() => setShowFilters(!showFilters)}
            className={`btn-secondary flex items-center gap-2 ${showFilters ? 'bg-primary-50 border-primary-200 text-primary-700' : ''}`}
          >
            <Filter className="w-4 h-4" />
            Фильтры
          </button>

          {/* Export */}
          <button className="btn-primary flex items-center gap-2">
            <FileSpreadsheet className="w-4 h-4" />
            Экспорт XLSX
          </button>
        </div>

        {/* Filters row */}
        {showFilters && (
          <div className="flex flex-wrap gap-3 mt-3 animate-fade-in">
            <div className="flex items-center gap-2">
              <label className="text-xs font-medium text-slate-600">Тип:</label>
              <select
                value={filterType}
                onChange={(e) => setFilterType(e.target.value)}
                className="input-field w-auto text-xs py-1.5"
              >
                <option value="all">Все типы</option>
                {Object.entries(docTypeLabels).map(([key, label]) => (
                  <option key={key} value={key}>{label}</option>
                ))}
              </select>
            </div>
            <div className="flex items-center gap-2">
              <label className="text-xs font-medium text-slate-600">Город:</label>
              <select
                value={filterCity}
                onChange={(e) => setFilterCity(e.target.value)}
                className="input-field w-auto text-xs py-1.5"
              >
                <option value="all">Все города</option>
                {cities.map(city => (
                  <option key={city} value={city}>{city}</option>
                ))}
              </select>
            </div>
            {(filterType !== 'all' || filterCity !== 'all') && (
              <button
                onClick={() => { setFilterType('all'); setFilterCity('all'); }}
                className="text-xs text-primary-600 hover:text-primary-700 flex items-center gap-1"
              >
                <X className="w-3 h-3" />
                Сбросить
              </button>
            )}
          </div>
        )}

        {/* Stats */}
        <div className="flex items-center gap-4 mt-3 text-xs text-slate-500">
          <span>Найдено: <strong className="text-slate-700">{filteredFiles.length}</strong> из {mockFiles.length}</span>
          <span>Общая сумма: <strong className="text-slate-700">{formatAmount(totalAmount)}</strong></span>
        </div>
      </div>

      {/* Table */}
      <div className="flex-1 overflow-auto">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 border-b border-slate-200 sticky top-0 z-10">
            <tr>
              {[
                { field: 'doc_type' as keyof DocFile, label: 'Тип' },
                { field: 'doc_number' as keyof DocFile, label: '№ документа' },
                { field: 'doc_date' as keyof DocFile, label: 'Дата' },
                { field: 'customer' as keyof DocFile, label: 'Контрагент' },
                { field: 'contract_no' as keyof DocFile, label: 'Договор' },
                { field: 'city' as keyof DocFile, label: 'Город' },
                { field: 'amount' as keyof DocFile, label: 'Сумма' },
                { field: 'status' as keyof DocFile, label: 'Статус' },
              ].map(col => (
                <th
                  key={col.field}
                  className="px-4 py-3 text-left text-xs font-semibold text-slate-600 cursor-pointer hover:text-slate-900 select-none"
                  onClick={() => toggleSort(col.field)}
                >
                  <div className="flex items-center gap-1">
                    {col.label}
                    <ArrowUpDown className="w-3 h-3 text-slate-400" />
                  </div>
                </th>
              ))}
              <th className="px-4 py-3 text-left text-xs font-semibold text-slate-600">Файл</th>
              <th className="px-4 py-3 w-10"></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {filteredFiles.map(file => (
              <tr key={file.id} className="hover:bg-slate-50 transition-colors">
                <td className="px-4 py-3">
                  <span className={`badge ${docTypeColors[file.doc_type]}`}>
                    {docTypeLabels[file.doc_type]}
                  </span>
                </td>
                <td className="px-4 py-3 font-medium text-slate-800">{file.doc_number || '—'}</td>
                <td className="px-4 py-3 text-slate-600">{file.doc_date ? formatDate(file.doc_date) : '—'}</td>
                <td className="px-4 py-3 text-slate-700 max-w-[200px] truncate">{file.customer || '—'}</td>
                <td className="px-4 py-3 text-slate-600">№{file.contract_no || '—'}</td>
                <td className="px-4 py-3 text-slate-600">{file.city || '—'}</td>
                <td className="px-4 py-3 font-medium text-slate-800">{formatAmount(file.amount)}</td>
                <td className="px-4 py-3">
                  <span className={`badge ${
                    file.status === 'done' ? 'badge-success' :
                    file.status === 'processing' ? 'badge-warning' :
                    file.status === 'failed' ? 'badge-danger' :
                    'badge-info'
                  }`}>
                    {statusLabels[file.status]}
                  </span>
                </td>
                <td className="px-4 py-3">
                  <div className="flex items-center gap-1.5">
                    <span className="text-xs text-slate-500">{file.original_name.slice(0, 20)}...</span>
                    <span className="text-[10px] text-slate-400">({formatBytes(file.size_bytes)})</span>
                  </div>
                </td>
                <td className="px-4 py-3">
                  <button
                    onClick={() => setSelectedFile(file)}
                    className="p-1.5 rounded-lg hover:bg-slate-100 transition-colors"
                  >
                    <Eye className="w-4 h-4 text-slate-500" />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* File detail modal */}
      {selectedFile && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 backdrop-blur-sm p-4" onClick={() => setSelectedFile(null)}>
          <div className="bg-white rounded-2xl shadow-2xl max-w-lg w-full max-h-[80vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between p-5 border-b border-slate-100">
              <h3 className="text-lg font-semibold text-slate-900">Карточка документа</h3>
              <button onClick={() => setSelectedFile(null)} className="p-1.5 rounded-lg hover:bg-slate-100">
                <X className="w-5 h-5 text-slate-500" />
              </button>
            </div>
            <div className="p-5 space-y-4">
              <div className="flex items-center gap-3">
                <span className={`badge text-sm px-3 py-1 ${docTypeColors[selectedFile.doc_type]}`}>
                  {docTypeLabels[selectedFile.doc_type]}
                </span>
                <span className={`badge ${
                  selectedFile.status === 'done' ? 'badge-success' : 'badge-warning'
                }`}>
                  {statusLabels[selectedFile.status]}
                </span>
              </div>
              
              <div className="grid grid-cols-2 gap-3">
                {[
                  ['Имя файла', selectedFile.original_name],
                  ['Формат', selectedFile.format.toUpperCase()],
                  ['Размер', formatBytes(selectedFile.size_bytes)],
                  ['Номер', selectedFile.doc_number || '—'],
                  ['Дата документа', selectedFile.doc_date ? formatDate(selectedFile.doc_date) : '—'],
                  ['Контрагент', selectedFile.customer || '—'],
                  ['Договор', `№${selectedFile.contract_no || '—'}`],
                  ['Дата договора', selectedFile.contract_date ? formatDate(selectedFile.contract_date) : '—'],
                  ['Город', selectedFile.city || '—'],
                  ['Сумма', formatAmount(selectedFile.amount)],
                  ['OCR точность', selectedFile.ocr_confidence ? `${(selectedFile.ocr_confidence * 100).toFixed(0)}%` : '—'],
                  ['Источник', selectedFile.source],
                ].map(([label, value]) => (
                  <div key={label}>
                    <p className="text-xs text-slate-500">{label}</p>
                    <p className="text-sm font-medium text-slate-800">{value}</p>
                  </div>
                ))}
              </div>

              <div className="pt-3 border-t border-slate-100">
                <p className="text-xs text-slate-500">Описание</p>
                <p className="text-sm text-slate-700">{selectedFile.description || '—'}</p>
              </div>

              <div className="flex gap-2 pt-3">
                <button className="btn-primary flex-1 flex items-center justify-center gap-2">
                  <Download className="w-4 h-4" />
                  Скачать оригинал
                </button>
                <button className="btn-secondary flex-1 flex items-center justify-center gap-2">
                  <FileSpreadsheet className="w-4 h-4" />
                  Воспроизвести
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
