import { useState } from 'react';
import { Page, User } from './types';
import { mockUser } from './store';
import LoginPage from './pages/LoginPage';
import ChatPage from './pages/ChatPage';
import CardIndexPage from './pages/CardIndexPage';
import FilesPage from './pages/FilesPage';
import AdminPage from './pages/AdminPage';
import DocsPage from './pages/DocsPage';
import Sidebar from './components/Sidebar';
import Header from './components/Header';

export default function App() {
  const [user, setUser] = useState<User | null>(null);
  const [currentPage, setCurrentPage] = useState<Page>('chat');
  const [sidebarOpen, setSidebarOpen] = useState(true);

  if (!user) {
    return <LoginPage onLogin={setUser} />;
  }

  const renderPage = () => {
    switch (currentPage) {
      case 'chat': return <ChatPage />;
      case 'card': return <CardIndexPage />;
      case 'files': return <FilesPage />;
      case 'admin': return <AdminPage />;
      case 'docs': return <DocsPage />;
      default: return <ChatPage />;
    }
  };

  return (
    <div className="flex h-screen overflow-hidden bg-slate-50">
      <Sidebar
        currentPage={currentPage}
        onNavigate={setCurrentPage}
        isOpen={sidebarOpen}
        user={user}
      />
      <div className="flex-1 flex flex-col min-w-0">
        <Header
          user={user}
          onLogout={() => setUser(null)}
          onToggleSidebar={() => setSidebarOpen(!sidebarOpen)}
          currentPage={currentPage}
        />
        <main className="flex-1 overflow-hidden">
          {renderPage()}
        </main>
      </div>
    </div>
  );
}
