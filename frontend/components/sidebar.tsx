"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  FolderOpen,
  Upload,
  Search,
  Settings,
  Archive,
  LogOut,
  Bell,
} from "lucide-react";
import { useAuth } from "@/lib/auth";
import { formatBytes } from "@/lib/format";

const NAV_ITEMS = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/documents", label: "Documents", icon: FolderOpen },
  { href: "/upload", label: "Upload", icon: Upload },
  { href: "/search", label: "Search", icon: Search },
];

export function Sidebar() {
  const pathname = usePathname();
  const { user, tenant, signOut } = useAuth();

  const storagePercent = tenant
    ? Math.min(100, Math.round((tenant.storageUsedBytes / tenant.storageLimitBytes) * 100))
    : 0;

  return (
    <aside className="sidebar w-64 flex-shrink-0 flex flex-col h-screen sticky top-0">
      {/* Logo */}
      <div className="px-6 py-5 border-b border-slate-700">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-blue-600 flex items-center justify-center flex-shrink-0">
            <Archive className="w-4 h-4 text-white" />
          </div>
          <div>
            <p className="text-white text-sm font-semibold leading-tight">DataWiz</p>
            <p className="text-slate-400 text-xs">Digital Archive</p>
          </div>
        </div>
      </div>

      {/* Tenant pill */}
      <div className="px-4 py-3 border-b border-slate-700">
        <div className="bg-slate-800 rounded-lg px-3 py-2">
          <p className="text-slate-300 text-xs font-medium truncate">{tenant?.name ?? "—"}</p>
          <p className="text-slate-500 text-xs capitalize">{tenant?.plan ?? "—"} plan</p>
        </div>
      </div>

      {/* Nav */}
      <nav className="flex-1 px-3 py-4 space-y-1 overflow-y-auto">
        {NAV_ITEMS.map(({ href, label, icon: Icon }) => {
          const active =
            pathname === href ||
            (href !== "/dashboard" && pathname.startsWith(href));
          return (
            <Link
              key={href}
              href={href}
              className={`sidebar-link flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium ${
                active ? "active" : ""
              }`}
            >
              <Icon className="w-4 h-4 flex-shrink-0" />
              {label}
            </Link>
          );
        })}

        <div className="pt-4 border-t border-slate-700 mt-4">
          <Link
            href="/settings"
            className={`sidebar-link flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium ${
              pathname === "/settings" ? "active" : ""
            }`}
          >
            <Settings className="w-4 h-4 flex-shrink-0" />
            Settings
          </Link>
        </div>
      </nav>

      {/* Storage meter */}
      <div className="px-4 py-3 border-t border-slate-700">
        <div className="mb-2 flex items-center justify-between">
          <span className="text-slate-400 text-xs">Storage</span>
          <span className="text-slate-300 text-xs font-medium">{storagePercent}%</span>
        </div>
        <div className="h-1.5 bg-slate-700 rounded-full overflow-hidden">
          <div
            className="h-full bg-blue-500 rounded-full transition-all"
            style={{ width: `${storagePercent}%` }}
          />
        </div>
        <p className="text-slate-500 text-xs mt-1">
          {tenant
            ? `${formatBytes(tenant.storageUsedBytes)} / ${formatBytes(tenant.storageLimitBytes)}`
            : "—"}
        </p>
      </div>

      {/* User row */}
      <div className="px-4 py-3 border-t border-slate-700 flex items-center gap-3">
        <div className="w-8 h-8 rounded-full bg-blue-600 flex items-center justify-center flex-shrink-0">
          <span className="text-white text-xs font-semibold">
            {user?.avatarInitials ?? "?"}
          </span>
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-slate-200 text-xs font-medium truncate">
            {user?.name ?? "—"}
          </p>
          <p className="text-slate-500 text-xs capitalize">{user?.role ?? "—"}</p>
        </div>
        <div className="flex items-center gap-1">
          <button className="p-1.5 rounded-md hover:bg-slate-700 text-slate-400 hover:text-slate-200 transition-colors">
            <Bell className="w-3.5 h-3.5" />
          </button>
          <button
            onClick={signOut}
            className="p-1.5 rounded-md hover:bg-slate-700 text-slate-400 hover:text-slate-200 transition-colors"
            title="Sign out"
          >
            <LogOut className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>
    </aside>
  );
}
