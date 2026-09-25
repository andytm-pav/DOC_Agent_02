import { useState, useRef, useEffect } from 'react';
import { ChatMessage, DocFile } from '../types';
import { initialMessages, mockFiles, docTypeLabels, docTypeColors, formatBytes, formatDate } from '../store';
import {
  Send, Paperclip, Bot, User, FileText, Download,
  X, CheckCircle, AlertTriangle, Sparkles
} from 'lucide-react';

export default function ChatPage() {
  const [messages, setMessages] = useState<ChatMessage[]>(initialMessages);
  const [input, setInput] = useState('');
  const [isTyping, setIsTyping] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [uploadedFiles, setUploadedFiles] = useState<File[]>([]);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const simulateResponse = (query: string) => {
    setIsTyping(true);
    
    setTimeout(() => {
      let response: ChatMessage;
      
      if (query.toLowerCase().includes('кс-2') || query.toLowerCase().includes('кс2') || query.toLowerCase().includes('кс 2')) {
        const ks2Files = mockFiles.filter(f => f.doc_type === 'ks2');
        response = {
          id: Date.now().toString(),
          role: 'agent',
          content: `Найдено ${ks2Files.length} документов КС-2:\n\n${ks2Files.map(f => `• **${f.doc_number}** — ${f.customer}, ${f.city} от ${formatDate(f.doc_date || '')}, сумма: ${f.amount?.toLocaleString('ru-RU')} ₽ [file_id:${f.id}]`).join('\n')}`,
          files: ks2Files,
          confidence: 0.92,
          grounded: true,
          timestamp: new Date().toISOString()
        };
      } else if (query.toLowerCase().includes('нет данных') || query.toLowerCase().includes('тtn 999') || query.toLowerCase().includes('тtn №999')) {
        response = {
          id: Date.now().toString(),
          role: 'agent',
          content: 'НЕТ ДАННЫХ\n\nВ загруженных документах не найдена информация по вашему запросу. Проверьте, загружен ли соответствующий документ.',
          confidence: 0.15,
          grounded: true,
          timestamp: new Date().toISOString()
        };
      } else if (query.toLowerCase().includes('картотек') || query.toLowerCase().includes('экспорт')) {
        response = {
          id: Date.now().toString(),
          role: 'agent',
          content: 'Картотека подготовлена для экспорта. Нажмите кнопку «Экспорт в XLSX» в разделе Картотека для скачивания файла с 15 колонками и автофильтром.\n\nВсего документов: 8\nДоговоров: 3\nГородов: 3',
          confidence: 0.98,
          grounded: true,
          timestamp: new Date().toISOString()
        };
      } else if (query.toLowerCase().includes('договор') && query.match(/\d+/)) {
        const contractNum = query.match(/\d+/)?.[0];
        const files = mockFiles.filter(f => f.contract_no === contractNum);
        if (files.length > 0) {
          response = {
            id: Date.now().toString(),
            role: 'agent',
            content: `По договору №${contractNum} найдено ${files.length} документов:\n\n${files.map(f => `• ${docTypeLabels[f.doc_type]} — ${f.doc_number || 'б/н'} от ${formatDate(f.doc_date || '')} [file_id:${f.id}]`).join('\n')}\n\nОбщая сумма: ${files.reduce((s, f) => s + (f.amount || 0), 0).toLocaleString('ru-RU')} ₽`,
            files: files,
            confidence: 0.95,
            grounded: true,
            timestamp: new Date().toISOString()
          };
        } else {
          response = {
            id: Date.now().toString(),
            role: 'agent',
            content: `НЕТ ДАННЫХ\n\nДоговор №${contractNum} не найден в базе документов.`,
            confidence: 0.1,
            grounded: true,
            timestamp: new Date().toISOString()
          };
        }
      } else if (query.toLowerCase().includes('загруз') || query.toLowerCase().includes('файл')) {
        response = {
          id: Date.now().toString(),
          role: 'agent',
          content: 'Для загрузки файлов перетащите их в область чата или нажмите кнопку 📎. Поддерживаемые форматы: PDF, DOCX, XLSX, PPTX, JPG, PNG, EML, ZIP.\n\nПосле загрузки файл будет:\n• Распознан (OCR для изображений)\n• Классифицирован\n• Проиндексирован для поиска',
          confidence: 1.0,
          grounded: true,
          timestamp: new Date().toISOString()
        };
      } else {
        response = {
          id: Date.now().toString(),
          role: 'agent',
          content: 'Я могу помочь с:\n• Поиском документов по номеру договора, типу, городу\n• Ответами на вопросы по содержимому документов\n• Экспортом картотеки\n• Воспроизведением документов в других форматах\n\nПопробуйте спросить: «Покажи все КС-2 по договору 123»',
          confidence: 0.85,
          grounded: true,
          timestamp: new Date().toISOString()
        };
      }

      setMessages(prev => [...prev, response]);
      setIsTyping(false);
    }, 1500 + Math.random() * 1000);
  };

  const handleSend = () => {
    if (!input.trim() && uploadedFiles.length === 0) return;

    const userMsg: ChatMessage = {
      id: Date.now().toString(),
      role: 'user',
      content: input || `Загружено файлов: ${uploadedFiles.length}`,
      timestamp: new Date().toISOString()
    };

    setMessages(prev => [...prev, userMsg]);
    setInput('');
    setUploadedFiles([]);
    simulateResponse(input);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const files = Array.from(e.dataTransfer.files);
    if (files.length > 0) {
      setUploadedFiles(prev => [...prev, ...files]);
      
      // Simulate file processing
      const fileMsg: ChatMessage = {
        id: Date.now().toString(),
        role: 'system',
        content: `Файл «${files[0].name}» добавлен в обработку. Формат: ${files[0].name.split('.').pop()?.toUpperCase()}. Ожидание распознавания...`,
        timestamp: new Date().toISOString()
      };
      setMessages(prev => [...prev, fileMsg]);

      setTimeout(() => {
        const doneMsg: ChatMessage = {
          id: (Date.now() + 1).toString(),
          role: 'system',
          content: `✓ Файл «${files[0].name}» обработан: распознан как КС-2, договор №123, Москва. Индексация завершена.`,
          timestamp: new Date().toISOString()
        };
        setMessages(prev => [...prev, doneMsg]);
      }, 2000);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const renderMessage = (msg: ChatMessage) => {
    if (msg.role === 'system') {
      return (
        <div key={msg.id} className="flex justify-center animate-fade-in">
          <div className="px-4 py-2 rounded-full bg-slate-100 border border-slate-200 text-xs text-slate-600 max-w-[80%] text-center">
            {msg.content}
          </div>
        </div>
      );
    }

    if (msg.role === 'user') {
      return (
        <div key={msg.id} className="flex justify-end animate-fade-in">
          <div className="flex items-end gap-2 max-w-[80%]">
            <div className="chat-bubble-user">
              <p className="text-sm whitespace-pre-wrap">{msg.content}</p>
            </div>
            <div className="w-7 h-7 rounded-full bg-primary-100 flex items-center justify-center flex-shrink-0">
              <User className="w-4 h-4 text-primary-600" />
            </div>
          </div>
        </div>
      );
    }

    return (
      <div key={msg.id} className="flex justify-start animate-fade-in">
        <div className="flex items-start gap-2 max-w-[85%]">
          <div className="w-7 h-7 rounded-full bg-gradient-to-br from-primary-500 to-accent-600 flex items-center justify-center flex-shrink-0 mt-0.5">
            <Bot className="w-4 h-4 text-white" />
          </div>
          <div className="space-y-2">
            <div className="chat-bubble-agent">
              <div className="text-sm whitespace-pre-wrap">
                {msg.content.split('\n').map((line, i) => {
                  // Bold
                  const parts = line.split(/(\*\*.*?\*\*)/g);
                  return (
                    <span key={i}>
                      {parts.map((part, j) => {
                        if (part.startsWith('**') && part.endsWith('**')) {
                          return <strong key={j}>{part.slice(2, -2)}</strong>;
                        }
                        return <span key={j}>{part}</span>;
                      })}
                      {i < msg.content.split('\n').length - 1 && <br />}
                    </span>
                  );
                })}
              </div>
            </div>
            
            {/* Confidence & grounded indicator */}
            {msg.confidence !== undefined && (
              <div className="flex items-center gap-3 px-1">
                <div className="flex items-center gap-1">
                  {msg.confidence > 0.8 ? (
                    <CheckCircle className="w-3 h-3 text-green-500" />
                  ) : msg.confidence > 0.5 ? (
                    <AlertTriangle className="w-3 h-3 text-amber-500" />
                  ) : (
                    <AlertTriangle className="w-3 h-3 text-red-500" />
                  )}
                  <span className="text-[10px] text-slate-500">
                    Уверенность: {(msg.confidence * 100).toFixed(0)}%
                  </span>
                </div>
                {msg.grounded && (
                  <span className="text-[10px] text-green-600 font-medium">✓ Подтверждено источниками</span>
                )}
              </div>
            )}

            {/* Attached files */}
            {msg.files && msg.files.length > 0 && (
              <div className="space-y-1.5">
                {msg.files.map(file => (
                  <div key={file.id} className="flex items-center gap-2 px-3 py-2 rounded-lg bg-slate-50 border border-slate-100">
                    <FileText className="w-4 h-4 text-slate-400 flex-shrink-0" />
                    <div className="flex-1 min-w-0">
                      <p className="text-xs font-medium text-slate-700 truncate">{file.original_name}</p>
                      <div className="flex items-center gap-2 mt-0.5">
                        <span className={`badge ${docTypeColors[file.doc_type]}`}>
                          {docTypeLabels[file.doc_type]}
                        </span>
                        <span className="text-[10px] text-slate-500">{formatBytes(file.size_bytes)}</span>
                      </div>
                    </div>
                    <button className="p-1 rounded hover:bg-slate-200 transition-colors">
                      <Download className="w-3.5 h-3.5 text-slate-500" />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    );
  };

  return (
    <div
      className={`h-full flex flex-col ${dragOver ? 'bg-primary-50/50' : ''} transition-colors duration-200`}
      onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
      onDragLeave={() => setDragOver(false)}
      onDrop={handleDrop}
    >
      {/* Drag overlay */}
      {dragOver && (
        <div className="absolute inset-0 z-50 flex items-center justify-center bg-primary-500/10 backdrop-blur-sm pointer-events-none">
          <div className="flex flex-col items-center gap-3 p-8 rounded-2xl bg-white shadow-xl border-2 border-dashed border-primary-400">
            <Paperclip className="w-10 h-10 text-primary-500" />
            <p className="text-lg font-medium text-primary-700">Перетащите файлы сюда</p>
            <p className="text-sm text-slate-500">PDF, DOCX, XLSX, JPG, PNG, EML, ZIP</p>
          </div>
        </div>
      )}

      {/* Messages area */}
      <div className="flex-1 overflow-y-auto px-4 lg:px-6 py-4 space-y-4">
        {messages.map(renderMessage)}
        
        {/* Typing indicator */}
        {isTyping && (
          <div className="flex justify-start animate-fade-in">
            <div className="flex items-start gap-2">
              <div className="w-7 h-7 rounded-full bg-gradient-to-br from-primary-500 to-accent-600 flex items-center justify-center flex-shrink-0">
                <Bot className="w-4 h-4 text-white" />
              </div>
              <div className="chat-bubble-agent">
                <div className="flex items-center gap-1.5 py-1">
                  <div className="w-2 h-2 rounded-full bg-slate-400 typing-dot" />
                  <div className="w-2 h-2 rounded-full bg-slate-400 typing-dot" />
                  <div className="w-2 h-2 rounded-full bg-slate-400 typing-dot" />
                </div>
              </div>
            </div>
          </div>
        )}
        
        <div ref={messagesEndRef} />
      </div>

      {/* Uploaded files preview */}
      {uploadedFiles.length > 0 && (
        <div className="px-4 lg:px-6 pb-2">
          <div className="flex flex-wrap gap-2">
            {uploadedFiles.map((file, idx) => (
              <div key={idx} className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-primary-50 border border-primary-200 animate-fade-in">
                <FileText className="w-3.5 h-3.5 text-primary-600" />
                <span className="text-xs font-medium text-primary-700">{file.name}</span>
                <button
                  onClick={() => setUploadedFiles(prev => prev.filter((_, i) => i !== idx))}
                  className="p-0.5 rounded hover:bg-primary-200 transition-colors"
                >
                  <X className="w-3 h-3 text-primary-600" />
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Input area */}
      <div className="border-t border-slate-200 bg-white px-4 lg:px-6 py-3">
        <div className="flex items-end gap-2">
          <button
            onClick={() => fileInputRef.current?.click()}
            className="p-2.5 rounded-lg hover:bg-slate-100 transition-colors text-slate-500 hover:text-slate-700"
            title="Прикрепить файл"
          >
            <Paperclip className="w-5 h-5" />
          </button>
          <input
            ref={fileInputRef}
            type="file"
            multiple
            className="hidden"
            onChange={(e) => {
              if (e.target.files) {
                setUploadedFiles(prev => [...prev, ...Array.from(e.target.files!)]);
              }
            }}
          />
          <div className="flex-1 relative">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Задайте вопрос или перетащите файл..."
              className="w-full px-4 py-2.5 rounded-xl border border-slate-200 bg-slate-50 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent focus:bg-white transition-all min-h-[42px] max-h-32"
              rows={1}
            />
          </div>
          <button
            onClick={handleSend}
            disabled={!input.trim() && uploadedFiles.length === 0}
            className="p-2.5 rounded-xl bg-primary-600 hover:bg-primary-700 text-white transition-colors disabled:opacity-50 disabled:cursor-not-allowed shadow-sm"
          >
            <Send className="w-5 h-5" />
          </button>
        </div>
        <div className="flex items-center justify-between mt-2 px-1">
          <div className="flex items-center gap-1.5">
            <Sparkles className="w-3 h-3 text-primary-500" />
            <span className="text-[10px] text-slate-500">Модель: qwen2.5:1.5b • Локально</span>
          </div>
          <span className="text-[10px] text-slate-400">Enter — отправить, Shift+Enter — перенос</span>
        </div>
      </div>
    </div>
  );
}
