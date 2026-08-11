"use client";

import { useState } from "react";
import { AuthProvider } from "@/lib/auth";
import { Sidebar } from "@/components/sidebar";
import { Menu, X, Archive } from "lucide-react";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  return (
    <AuthProvider>
      <div className="flex flex-col md:flex-row h-full min-h-screen">
        {/* Mobile Top Header (< md) */}
        <header className="md:hidden flex items-center justify-between px-4 py-3 bg-slate-900 border-b border-slate-800 text-white sticky top-0 z-30">
          <div className="flex items-center gap-2.5">
            <div className="w-7 h-7 rounded-lg bg-blue-600 flex items-center justify-center flex-shrink-0">
              <Archive className="w-3.5 h-3.5 text-white" />
            </div>
            <div>
              <p className="text-white text-xs font-semibold leading-tight">DataWiz</p>
              <p className="text-slate-400 text-[10px]">Digital Archive</p>
            </div>
          </div>
          <button
            onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
            className="p-2 rounded-lg text-slate-300 hover:bg-slate-800 focus:outline-none"
            aria-label="Toggle Navigation Menu"
          >
            {mobileMenuOpen ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
          </button>
        </header>

        {/* Desktop Sidebar (persistent on md: and above) */}
        <Sidebar />

        {/* Mobile Sidebar Overlay/Drawer (< md) */}
        {mobileMenuOpen && (
          <div className="md:hidden fixed inset-0 z-40 flex">
            {/* Backdrop */}
            <div
              className="fixed inset-0 bg-slate-900/80 backdrop-blur-sm transition-opacity"
              onClick={() => setMobileMenuOpen(false)}
            />
            {/* Slide-out Sidebar */}
            <div className="relative flex-1 flex flex-col max-w-xs w-full bg-slate-900 z-50 shadow-xl">
              <Sidebar
                className="w-full h-full border-r border-slate-800"
                onNavigate={() => setMobileMenuOpen(false)}
              />
            </div>
          </div>
        )}

        {/* Main Content */}
        <main className="flex-1 overflow-y-auto min-w-0">{children}</main>
      </div>
    </AuthProvider>
  );
}
