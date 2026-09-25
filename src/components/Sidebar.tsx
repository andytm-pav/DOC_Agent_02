import { Page, User } from '../types';
import {
  MessageSquare, Database, FileText, Settings, Bot
} from 'lucide-react';

interface SidebarProps {
  currentPage: Page;
  onNavigate: (page: Page) => void;
  isOpen: boolean;
  user: User;
}

const navItems: { page: Page; label: string; icon: typeof MessageSquare; adminOnly?: boolean }[] = [
  { page: 'chat', label: 'Чат', icon: MessageSquare },
  { page: 'card', label: 'Картотека', icon: Database },
  { page: 'files', label: 'Файлы', icon: FileText },
  { page: 'admin', label: 'Администрирование', icon: Settings, adminOnly: true },
];

export default function Sidebar({ currentPage, onNavigate, isOpen, user }: SidebarProps) {
  return (
    <aside
      className={`${
        isOpen ? 'w-64' : 'w-16'
      } flex flex-col bg-white border-r border-slate-200 transition-all duration-300 ease-in-out relative`}
    >
      {/* Logo */}
      <div className="flex items-center gap-3 px-4 h-16 border-b border-slate-100">
        <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-primary-500 to-accent-600 flex items-center justify-center flex-shrink-0">
          <Bot className="w-5 h-5 text-white" />
        </div>
        {isOpen && (
          <div className="animate-fade-in overflow-hidden">
            <h1 className="text-sm font-bold text-slate-900 whitespace-nowrap">Документовед</h1>
            <p className="text-[10px] text-slate-500 whitespace-nowrap">ИИ-агент v2.0</p>
          </div>
        )}
      </div>

      {/* Navigation */}
      <nav className="flex-1 px-2 py-4 space-y-1">
        {navItems.map((item) => {
          if (item.adminOnly && user.role !== 'admin') return null;
          const Icon = item.icon;
          const isActive = currentPage === item.page;
          return (
            <button
              key={item.page}
              onClick={() => onNavigate(item.page)}
              className={`sidebar-item w-full ${
                isActive ? 'sidebar-item-active' : 'sidebar-item-inactive'
              }`}
              title={!isOpen ? item.label : undefined}
            >
              <Icon className="w-5 h-5 flex-shrink-0" />
              {isOpen && <span className="whitespace-nowrap">{item.label}</span>}
            </button>
          );
        })}
      </nav>

      {/* User info */}
      <div className="px-3 py-3 border-t border-slate-100">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-full bg-slate-200 flex items-center justify-center flex-shrink-0">
            <span className="text-xs font-medium text-slate-600">
              {user.username[0].toUpperCase()}
            </span>
          </div>
          {isOpen && (
            <div className="animate-fade-in overflow-hidden flex-1 min-w-0">
              <p className="text-xs font-medium text-slate-700 truncate">{user.username}</p>
              <p className="text-[10px] text-slate-500 capitalize">{user.role === 'admin' ? 'Администратор' : 'Пользователь'}</p>
            </div>
          )}
        </div>
      </div>
    </aside>
  );
}
