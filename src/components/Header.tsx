import { User, Page } from '../types';
import { Menu, Bell } from 'lucide-react';
import { useState } from 'react';

interface HeaderProps {
  user: User;
  onLogout: () => void;
  onToggleSidebar: () => void;
  currentPage: Page;
}

const pageTitles: Record<Page, string> = {
  chat: 'Чат с агентом',
  card: 'Картотека документов',
  files: 'Управление файлами',
  admin: 'Администрирование',
};

export default function Header({ user, onLogout, onToggleSidebar, currentPage }: HeaderProps) {
  const [showNotif, setShowNotif] = useState(false);

  return (
    <header className="h-16 bg-white border-b border-slate-200 flex items-center justify-between px-4 lg:px-6 flex-shrink-0">
      <div className="flex items-center gap-4">
        <button
          onClick={onToggleSidebar}
          className="p-2 rounded-lg hover:bg-slate-100 transition-colors"
        >
          <Menu className="w-5 h-5 text-slate-600" />
        </button>
        <div>
          <h2 className="text-lg font-semibold text-slate-900">{pageTitles[currentPage]}</h2>
          <p className="text-xs text-slate-500 hidden sm:block">Локальный ИИ-агент • Офлайн</p>
        </div>
      </div>

      <div className="flex items-center gap-2">
        {/* Online indicator */}
        <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-green-50 border border-green-200">
          <div className="w-2 h-2 rounded-full bg-green-500 animate-pulse" />
          <span className="text-xs font-medium text-green-700 hidden sm:inline">Система работает</span>
        </div>

        {/* Notifications */}
        <div className="relative">
          <button
            onClick={() => setShowNotif(!showNotif)}
            className="p-2 rounded-lg hover:bg-slate-100 transition-colors relative"
          >
            <Bell className="w-5 h-5 text-slate-600" />
            <span className="absolute top-1 right-1 w-2 h-2 rounded-full bg-red-500" />
          </button>
          {showNotif && (
            <div className="absolute right-0 top-12 w-72 bg-white rounded-xl shadow-lg border border-slate-200 z-50 animate-fade-in">
              <div className="p-3 border-b border-slate-100">
                <p className="text-sm font-medium text-slate-900">Уведомления</p>
              </div>
              <div className="p-3 space-y-2 max-h-64 overflow-y-auto">
                <div className="p-2 rounded-lg bg-blue-50 border border-blue-100">
                  <p className="text-xs text-blue-800">Файл «КС-2_Договор_123.pdf» обработан</p>
                  <p className="text-[10px] text-blue-600 mt-0.5">2 мин назад</p>
                </div>
                <div className="p-2 rounded-lg bg-amber-50 border border-amber-100">
                  <p className="text-xs text-amber-800">OCR confidence 0.72 — требуется проверка</p>
                  <p className="text-[10px] text-amber-600 mt-0.5">5 мин назад</p>
                </div>
                <div className="p-2 rounded-lg bg-green-50 border border-green-100">
                  <p className="text-xs text-green-800">Индексация завершена (8 документов)</p>
                  <p className="text-[10px] text-green-600 mt-0.5">10 мин назад</p>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Logout */}
        <button
          onClick={onLogout}
          className="p-2 rounded-lg hover:bg-red-50 transition-colors group"
          title="Выйти"
        >
          <svg className="w-5 h-5 text-slate-400 group-hover:text-red-500 transition-colors" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
          </svg>
        </button>
      </div>
    </header>
  );
}
